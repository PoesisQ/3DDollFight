"""Stage versioned VRM assets and a synchronized duel for the Unity project.

Run with uv run --locked python tools/prepare_unity.py. Generated StreamingAssets
are ignored: the authoritative meshes remain in Git LFS under data/avatars.
"""

import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path

import numpy as np

from dollfight.animation_export import export_duel, vector
from dollfight.server import replay_run

ROOT = Path(__file__).resolve().parents[1]
HUMAN = (
    "hips spine chest neck head leftUpperArm leftLowerArm leftHand "
    "rightUpperArm rightLowerArm rightHand leftUpperLeg leftLowerLeg leftFoot leftToes "
    "rightUpperLeg rightLowerLeg rightFoot rightToes"
).split()


def read_model(path):
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"{path}: missing binary asset; run git lfs pull")
    length = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + length])
    # These authored VRM 1.0 assets have unrotated T-pose nodes. Fail explicitly
    # rather than silently producing the wrong target for an arbitrary import.
    nodes = doc["nodes"]
    parents = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}

    def position(i):
        n = nodes[i]
        if "matrix" in n or n.get("rotation", [0, 0, 0, 1]) != [0, 0, 0, 1]:
            raise ValueError("Target extraction requires the authored unrotated VRM T-pose")
        if n.get("scale", [1, 1, 1]) != [1, 1, 1]:
            raise ValueError("Target extraction requires unit node scales")
        p = np.array(n.get("translation", [0, 0, 0]), dtype=float)
        return p + position(parents[i]) if i in parents else p

    mapping = doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    rest = np.array([position(mapping[name]["node"]) for name in HUMAN])
    cage = next(
        (
            n.get("extras", {}).get("dollfightCage")
            for n in nodes
            if n.get("extras", {}).get("dollfightCage")
        ),
        None,
    )
    if cage is None:
        raise ValueError("Expected the hybrid avatar's cloth control cage")
    config = {
        "segments": cage["segments"],
        "rows": cage["rows"],
        "rest": [vector(p) for p in cage["rest"]],
        "capsuleRadii": cage["capsuleRadii"],
    }
    return rest, config, hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replay", type=Path, help="Explicit existing Motion Lab run for comparison"
    )
    args = parser.parse_args()
    destination = ROOT / "unity/Assets/StreamingAssets/DollFight"
    destination.mkdir(parents=True, exist_ok=True)
    assets = []
    for name in ("nozomi", "mizore"):
        path = ROOT / f"data/avatars/local/{name}-hybrid.vrm"
        rest, cage, digest = read_model(path)
        shutil.copyfile(path, destination / f"{name}.vrm")
        write_json(destination / f"{name}-cloth.json", cage)
        assets.append({"name": name, "sha256": digest, "rest": rest.tolist()})
    if args.replay:
        run = json.loads(args.replay.read_text(encoding="utf-8"))
        np.testing.assert_allclose(run["target_rest"], assets[0]["rest"], atol=1e-4)
    else:
        run = replay_run(
            {
                "source": "cmu_sparring",
                "target_rest": assets[0]["rest"],
                "noise_mm": 0,
                "dropout": 0,
                # Match the authored rehearsal / Motion Lab defaults. The
                # generic 2.2 m camera-station gap makes every attack miss on
                # these shorter avatars despite otherwise valid animation.
                "initial_gap": 1.8,
                "movement_gain": 1.0,
            },
            include_duel=True,
        )
        if not run["duel"]["summary"].get("hit"):
            raise ValueError(
                "Default rehearsal has no scored contacts; check spacing and attack timing"
            )
    players, timeline = export_duel(run)
    for name, clip in zip(("nozomi", "mizore"), players, strict=True):
        write_json(destination / f"{name}-motion.json", clip)
    write_json(destination / "duel.json", timeline)
    write_json(
        destination / "provenance.json",
        {
            "version": "dollfight-unity-assets-1",
            "assets": assets,
            "source": run["source"],
            "config": run["config"],
            "duration": run["duration"],
            "frames": len(run["frames"]),
            "combat_summary": run["duel"]["summary"],
            "rounds": run["duel"]["rounds"],
            "note": "Offline public CMU rehearsal. Finger closure is a display prior.",
        },
    )
    print(f"Prepared {len(run['frames'])} paired frames / {run['duration']:.2f}s at {destination}")


if __name__ == "__main__":
    main()
