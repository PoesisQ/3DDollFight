"""Prepare the user-provided cloud PLY and verify its real platform alignment.

Run: uv run python tools/prepare_cloud.py [--source ../cloud.ply] [--inspect]
The original stays untouched; the complete SH0 scan becomes a local SPZ v4.
"""

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data/environments/cloud.json"
RUNTIME = ROOT / "unity/Assets/StreamingAssets/Environments/Cloud"
SPLAT = RUNTIME / "cloud.spz"
TOOL = ROOT / "tools/splat-transform"
CLI = TOOL / "node_modules/@playcanvas/splat-transform/bin/cli.mjs"
PARENTS = [-1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 13, 0, 15, 16, 17]
PROPERTIES = [
    "x",
    "y",
    "z",
    "f_dc_0",
    "f_dc_1",
    "f_dc_2",
    "opacity",
    "scale_0",
    "scale_1",
    "scale_2",
    "rot_0",
    "rot_1",
    "rot_2",
    "rot_3",
]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_source(path, config):
    with path.open("rb") as stream:
        lines = []
        for _ in range(128):
            line = stream.readline().decode("ascii").strip()
            lines.append(line)
            if line == "end_header":
                break
        expected = ["property float " + name for name in PROPERTIES]
        if (
            lines[:2] != ["ply", "format binary_little_endian 1.0"]
            or f"element vertex {config['source_points']}" not in lines
            or [line for line in lines if line.startswith("property ")] != expected
            or lines[-1] != "end_header"
        ):
            raise ValueError("Unexpected cloud PLY schema")
        points = np.fromfile(stream, dtype="<f4")
    if points.size != config["source_points"] * len(PROPERTIES):
        raise ValueError("Unexpected cloud PLY payload length")
    points = points.reshape(-1, len(PROPERTIES))
    if not np.isfinite(points).all() or np.any(np.linalg.norm(points[:, 10:14], axis=1) == 0):
        raise ValueError("Cloud PLY contains invalid splats")
    return points


def spz_info(path, config):
    with path.open("rb") as stream:
        header = stream.read(32)
    if len(header) != 32 or header[:4] != b"NGSP":
        raise ValueError("Expected an SPZ v4 header")
    version, count = struct.unpack_from("<II", header, 4)
    if version != 4 or count != config["source_points"] or header[12] != 0 or header[15] != 5:
        raise ValueError("SPZ must preserve every source point and SH0")
    return {
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "points": count,
        "sh_degree": header[12],
        "version": version,
    }


def replay_evidence(config):
    result = []
    for player in (1, 2):
        path = ROOT / f"unity/Assets/StreamingAssets/DollFight/player-{player}-motion.json"
        clip = json.loads(path.read_text(encoding="utf-8"))
        rest = np.array([[p[k] for k in "xyz"] for p in clip["rest"]])
        feet = []
        for frame in clip["frames"]:
            rotations = np.array([[q[k] for k in "xyzw"] for q in frame["rotations"]])
            points = np.zeros((19, 3))
            points[0] = [frame["root"][k] for k in "xyz"]
            for bone in range(1, 19):
                parent = PARENTS[bone]
                delta = rest[bone] - rest[parent]
                q = rotations[parent]
                cross = 2 * np.cross(q[:3], delta)
                points[bone] = points[parent] + delta + q[3] * cross + np.cross(q[:3], cross)
            feet.extend(points[[13, 14, 17, 18]])
        feet = np.array(feet)
        radius = float(np.linalg.norm(feet[:, [0, 2]], axis=1).max())
        surface = config["surface"]
        margin = surface["safe_interior_radius_world"] - radius - surface["shoe_allowance_world"]
        if margin <= 0:
            raise ValueError(f"Player {player} feet exceed the measured platform interior")
        result.append(
            {
                "player": player,
                "motion_sha256": digest(path),
                "frames": len(clip["frames"]),
                "feet_and_toes_min_stage": feet.min(axis=0).tolist(),
                "feet_and_toes_max_stage": feet.max(axis=0).tolist(),
                "maximum_horizontal_radius_m": radius,
                "margin_after_shoe_allowance_m": margin,
            }
        )
    return result


def grounding_evidence(points, config):
    surface = config["surface"]
    center = np.array(surface["center_xy_ply"])
    low, high = surface["fit_z_range_ply"]
    mask = (
        (np.sum((points[:, :2] - center) ** 2, axis=1) < surface["fit_radius_ply"] ** 2)
        & (points[:, 2] > low)
        & (points[:, 2] < high)
        & (points[:, 6] > surface["fit_min_opacity_logit"])
    )
    top = points[mask, :3]
    design = np.column_stack((top[:, :2], np.ones(len(top))))
    plane = np.linalg.lstsq(design, top[:, 2], rcond=None)[0]
    if not np.allclose(plane, surface["plane_z_equals_ax_plus_by_plus_c"], atol=1e-6):
        raise ValueError("Measured platform plane differs from the scene alignment")
    heights = (
        (top - np.array(surface["origin_ply"]))
        @ np.array(surface["normal_ply"])
        * surface["scene_scale"]
    )
    return {
        "surface_points": len(top),
        "fitted_plane_z_equals_ax_plus_by_plus_c": plane.tolist(),
        "aligned_surface_height_percentiles_5_50_95_m": np.quantile(
            heights, [0.05, 0.5, 0.95]
        ).tolist(),
        "safe_platform_radius_m": surface["safe_interior_radius_world"],
        "replay_fk": replay_evidence(config),
        "verification_scope": (
            "All source foot/toe trajectories plus 0.30m shoe allowance. Actual retargeted "
            "avatar sole contacts also require native Unity capture inspection."
        ),
    }


def run(command):
    subprocess.run([str(item) for item in command], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--inspect", action="store_true", help="Render the source platform with the converter GPU"
    )
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    source = (args.source or ROOT.parent / config["source_filename"]).resolve()
    source_hash = digest(source)
    if source_hash != config["source_sha256"]:
        raise ValueError("cloud.ply differs from the recorded user-provided original")
    points = read_source(source, config)
    evidence = grounding_evidence(points, config)
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Install Node.js 22 or newer")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        raise RuntimeError(f"Node.js 22 or newer required; found {version}")
    if not CLI.is_file():
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if npm is None:
            raise RuntimeError("Install npm to prepare the pinned splat-transform CLI")
        run([npm, "ci", "--prefix", TOOL, "--no-audit", "--no-fund"])
    installed = json.loads((CLI.parents[1] / "package.json").read_text(encoding="utf-8"))["version"]
    if installed != config["converter_version"]:
        raise ValueError("Converter differs from the pinned version")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cache = RUNTIME / "provenance.json"
    cached = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    if (
        args.force
        or not SPLAT.is_file()
        or cached.get("source_sha256") != source_hash
        or cached.get("configuration_sha256") != digest(CONFIG_PATH)
        or cached.get("converted") != spz_info(SPLAT, config)
    ):
        temporary = SPLAT.with_name("cloud.preparing.spz")
        try:
            run([node, CLI, "--overwrite", "--gpu", "cpu", "--spz-version", "4", source, temporary])
            spz_info(temporary, config)
            temporary.replace(SPLAT)
        finally:
            temporary.unlink(missing_ok=True)
    provenance = {
        "source_filename": source.name,
        "source_sha256": source_hash,
        "configuration_sha256": digest(CONFIG_PATH),
        "provenance": config["provenance"],
        "converter_version": installed,
        "converted": spz_info(SPLAT, config),
        "grounding": evidence,
    }
    cache.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output = ROOT / "outputs/cloud"
    output.mkdir(parents=True, exist_ok=True)
    (output / "grounding.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    if args.inspect:
        run(
            [
                node,
                CLI,
                "--overwrite",
                "--gpu-backend",
                "d3d12",
                source,
                output / "platform-view.webp",
                "--camera-pos",
                "0,8,5",
                "--camera-target",
                "0,0,0",
                "--camera-up",
                "0,0,1",
                "--resolution",
                "1440x900",
            ]
        )
    if digest(source) != source_hash:
        raise ValueError("Original source changed during preparation")
    print(
        f"Cloud prepared: {config['source_points']:,} splats / SH0 / SPZ4; source SHA-256 verified"
    )
    margin = min(p["margin_after_shoe_allowance_m"] for p in evidence["replay_fk"])
    print(
        f"Measured disk: {evidence['surface_points']:,} surface splats; "
        f"minimum padded foot margin {margin:.3f} m"
    )


if __name__ == "__main__":
    main()
