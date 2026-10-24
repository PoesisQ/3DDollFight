"""Rebuild pinned browser dependencies; optionally download original CMU files."""

import argparse
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = [
    {
        "name": "three",
        "version": "0.180.0",
        "url": "https://registry.npmjs.org/three/-/three-0.180.0.tgz",
        "sha256": "ad66d724565ee29a2467277fa84daa5ed0211d6b8d446e9ef29f6bae0cd14144",
        "members": {
            "build/three.module.min.js": "three.module.min.js",
            "build/three.core.min.js": "three.core.min.js",
            "examples/jsm/controls/OrbitControls.js": "OrbitControls.js",
            "examples/jsm/loaders/GLTFLoader.js": "GLTFLoader.js",
            "examples/jsm/utils/BufferGeometryUtils.js": "BufferGeometryUtils.js",
            "LICENSE": "THREE-LICENSE.txt",
        },
    },
    {
        "name": "@pixiv/three-vrm",
        "version": "3.5.5",
        "url": "https://registry.npmjs.org/@pixiv/three-vrm/-/three-vrm-3.5.5.tgz",
        "sha256": "6f0102f987bc8abc9b9e78ef5b3259ea9f0dc51e30bf51d32aea6218394ea755",
        "members": {
            "lib/three-vrm.module.min.js": "three-vrm.module.min.js",
            "LICENSE": "three-vrm-LICENSE.txt",
        },
    },
]


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "DollFight-course/0.4"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def vendor(packages, cache=None):
    target = ROOT / "apps/motion-lab/vendor"
    records = []
    for package in packages:
        archive_name = "vrm.tgz" if package["name"].startswith("@") else "three.tgz"
        blob = (cache / archive_name).read_bytes() if cache else fetch(package["url"])
        if hashlib.sha256(blob).hexdigest() != package["sha256"]:
            raise ValueError(f"Archive hash mismatch: {package['name']}")
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            for member, filename in package["members"].items():
                data = archive.extractfile("package/" + member).read()
                patch = None
                if filename == "GLTFLoader.js":
                    patch = "Flatten ../utils/BufferGeometryUtils.js to ./BufferGeometryUtils.js"
                    data = data.replace(
                        b"../utils/BufferGeometryUtils.js", b"./BufferGeometryUtils.js"
                    )
                (target / filename).write_bytes(data)
                records.append(
                    {
                        "file": filename,
                        "package": package["name"],
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "patch": patch,
                    }
                )
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "packages": [{k: v for k, v in p.items() if k != "members"} for p in packages],
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="Verified three.tgz / vrm.tgz cache")
    parser.add_argument("--cmu", action="store_true", help="Also fetch original ASF/AMC")
    args = parser.parse_args()
    vendor(PACKAGES, args.cache)
    if args.cmu:
        raw = ROOT / "data/raw/cmu"
        raw.mkdir(parents=True, exist_ok=True)
        for subject, filenames in (
            ("14", ("14.asf", "14_01.amc")),
            (
                "135",
                (
                    "135.asf",
                    "135_02.amc",
                    "135_04.amc",
                    "135_05.amc",
                    "135_07.amc",
                    "135_09.amc",
                    "135_10.amc",
                    "135_11.amc",
                ),
            ),
            ("08", ("08.asf", "08_04.amc")),
            ("76", ("76.asf", "76_01.amc", "76_04.amc", "76_09.amc")),
            ("88", ("88.asf", "88_06.amc")),
            ("69", ("69.asf", "69_42.amc")),
        ):
            for filename in filenames:
                destination = raw / filename
                if destination.exists():
                    continue
                data = fetch(f"https://mocap.cs.cmu.edu/subjects/{subject}/{filename}")
                destination.write_bytes(data)
                print(filename, len(data), hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
