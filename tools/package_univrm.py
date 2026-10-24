"""Repack the verified official UniVRM release as deterministic local UPM tarballs.

Usage: uv run --locked python tools/package_univrm.py <VRM-0.131.4_efd2.unitypackage>
Source bytes, .meta GUIDs and licenses are preserved; no vendor code is patched.
"""

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.131.4"
SOURCE = "https://github.com/vrm-c/UniVRM/releases/download/v0.131.4/VRM-0.131.4_efd2.unitypackage"
SOURCE_SHA256 = "8f91761bfe9cb498f29f7d66b5750e64909078569ffbb397ecbcfa1edd881f27"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Official release SHA-256 mismatch")
    packages = {"com.vrmc.gltf": {}, "com.vrmc.vrm": {}}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw)), mode="r:") as source:
        members = {member.name: member for member in source}
        for name in members:
            if not name.endswith("/pathname"):
                continue
            path = PurePosixPath(source.extractfile(members[name]).read().decode().strip())
            if path.is_absolute() or ".." in path.parts or path.parts[0] != "Packages":
                raise ValueError(f"Unexpected release path: {path}")
            package = path.parts[1]
            if package not in packages:
                raise ValueError(f"Unexpected package: {package}")
            relative = "/".join(path.parts[2:])
            if not relative:
                continue
            guid = name.split("/")[0]
            for source_suffix, output_suffix in (("asset", ""), ("asset.meta", ".meta")):
                member = members.get(f"{guid}/{source_suffix}")
                if member is not None and member.isfile():
                    packages[package][relative + output_suffix] = source.extractfile(member).read()
    destination = ROOT / "unity/Vendor"
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    license_text = (destination / "UniVRM-LICENSE.txt").read_bytes()
    if hashlib.sha256(license_text).hexdigest() != (
        "5cb01ebb60a7fa1885278a23e7f147f611b44686f772dd78835375365531cfb9"
    ):
        raise ValueError("Upstream MIT license SHA-256 mismatch")
    for name, files in packages.items():
        files["LICENSE.UniVRM.txt"] = license_text
        license_guid = hashlib.sha256((name + ":LICENSE.UniVRM.txt").encode()).hexdigest()[:32]
        files["LICENSE.UniVRM.txt.meta"] = (
            f"fileFormatVersion: 2\nguid: {license_guid}\nTextScriptImporter:\n"
            "  externalObjects: {}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
        ).encode()
        package_json = json.loads(files["package.json"])
        if package_json["name"] != name or package_json["version"] != VERSION:
            raise ValueError("Unexpected package identity")
        licenses = [
            path for path in files if "license" in path.lower() and not path.endswith(".meta")
        ]
        if not licenses:
            raise ValueError(f"No license bundled for {name}")
        target = destination / f"{name}-{VERSION}.tgz"
        with target.open("wb") as stream:
            with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as output:
                    for path, content in sorted(files.items()):
                        item = tarfile.TarInfo("package/" + path)
                        item.size = len(content)
                        item.mode = 0o644
                        output.addfile(item, io.BytesIO(content))
        records.append(
            {
                "file": target.name,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
                "files": len(files),
                "licenses": licenses,
            }
        )
    provenance = {
        "source": SOURCE,
        "source_sha256": SOURCE_SHA256,
        "upstream_commit": "efd20f62f1bf0ac3fcc34de1e497324c5197d146",
        "version": VERSION,
        "note": "Official release assets repacked unchanged, with upstream MIT license added.",
        "packages": records,
    }
    (destination / "univrm.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
