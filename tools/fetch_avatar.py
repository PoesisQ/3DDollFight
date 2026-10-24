"""Fetch the licensed official VRM sample. Explicit command; verified SHA-256."""

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "data/avatars/sample.json").read_text(encoding="utf-8"))
    destination = ROOT / "data/raw/avatars/sample.vrm"
    if (
        destination.exists()
        and hashlib.sha256(destination.read_bytes()).hexdigest() == manifest["sha256"]
    ):
        print("VRM sample already present; SHA-256 verified")
        return
    request = urllib.request.Request(
        manifest["url"], headers={"User-Agent": "DollFight-course/0.4"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        content = response.read(40 * 1024 * 1024 + 1)
    if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
        raise ValueError("VRM hash mismatch; existing asset has NOT been replaced")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    print(f"Downloaded {manifest['name']} ({len(content)} bytes); SHA-256 verified")


if __name__ == "__main__":
    main()
