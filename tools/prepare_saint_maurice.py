"""Prepare the separately licensed local SOG scan for the two Unity scenes."""

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data/environments/saint-maurice.json"
RUNTIME = ROOT / "unity/Assets/StreamingAssets/Environments/SaintMaurice"
FULL = ROOT / "unity/Assets/LocalScenes/SaintMaurice/church-full.spz"
DUEL = RUNTIME / "church.spz"
CACHE = RUNTIME / "provenance.json"
TOOL = ROOT / "tools/splat-transform"
CLI = TOOL / "node_modules/@playcanvas/splat-transform/bin/cli.mjs"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def spz_info(path):
    with path.open("rb") as stream:
        header = stream.read(16)
    if len(header) != 16 or header[:4] != b"NGSP":
        raise ValueError(f"{path}: expected an SPZ v4 header")
    version, count = struct.unpack_from("<II", header, 4)
    if version != 4 or not 0 < count <= 9975598 or header[12] != 3:
        raise ValueError(f"{path}: unexpected SPZ version, point count or SH degree")
    return {"sha256": digest(path), "bytes": path.stat().st_size, "points": count, "sh": 3}


def write_provenance(config, source_hash):
    result = {
        "source_sha256": source_hash,
        "configuration_sha256": digest(CONFIG_PATH),
        "converter_version": config["converter_version"],
        "source_url": config["source_url"],
        "license": config["license"],
        "profiles": {"full": spz_info(FULL), "duel": spz_info(DUEL)},
    }
    if result["profiles"]["full"]["points"] != config["source_points"]:
        raise ValueError("The full preview must retain every source point")
    CACHE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run(command):
    subprocess.run([str(item) for item in command], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Original licensed SOG file")
    parser.add_argument("--force", action="store_true", help="Rebuild both local SPZ profiles")
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    source = (args.source or ROOT.parent / config["source_filename"]).resolve()
    if not source.is_file():
        raise FileNotFoundError(
            f"Place {config['source_filename']} beside the repository, or use --source"
        )
    source_hash = digest(source)
    if source_hash != config["source_sha256"]:
        raise ValueError(
            "SOG differs from the recorded source; review its provenance before replacing it"
        )
    with zipfile.ZipFile(source) as archive:
        meta = json.loads(archive.read("meta.json"))
        attribution = archive.read("license.txt").decode("utf-8")
    if meta.get("version") != 2 or meta.get("count") != config["source_points"]:
        raise ValueError("Unexpected SOG version or point count")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    FULL.parent.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "ATTRIBUTION.txt").write_text(attribution, encoding="utf-8")
    if not args.force and CACHE.is_file() and FULL.is_file() and DUEL.is_file():
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if (
            cached.get("source_sha256") == source_hash
            and cached.get("configuration_sha256") == digest(CONFIG_PATH)
            and cached.get("profiles", {}).get("full") == spz_info(FULL)
            and cached.get("profiles", {}).get("duel") == spz_info(DUEL)
        ):
            print("Saint Maurice profiles already prepared; source and SPZ SHA-256 verified")
            return
    node = shutil.which("node")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if node is None or npm is None:
        raise RuntimeError("Install Node.js 22 or newer, including npm")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        raise RuntimeError(f"Node.js 22 or newer is required; found {version}")
    if not CLI.is_file():
        run(
            [
                npm,
                "ci",
                "--prefix",
                TOOL,
                "--registry",
                "https://registry.npmjs.org",
                "--no-audit",
                "--no-fund",
            ]
        )
    base = [
        node,
        "--max-old-space-size=6144",
        CLI,
        "--overwrite",
        "--gpu",
        "cpu",
        "--spz-version",
        "4",
    ]
    for destination, actions in (
        (FULL, []),
        (DUEL, ["--filter-box", ",".join(map(str, config["duel_crop_playcanvas"]))]),
    ):
        temporary = destination.with_name(destination.stem + ".preparing.spz")
        try:
            run([*base, source, *actions, temporary])
            spz_info(temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    result = write_provenance(config, source_hash)
    print(
        f"Prepared {result['profiles']['full']['points']:,} full / "
        f"{result['profiles']['duel']['points']:,} duel points"
    )


if __name__ == "__main__":
    main()
