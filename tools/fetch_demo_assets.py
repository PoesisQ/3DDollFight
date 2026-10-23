"""Fetch pinned rendering code and public CMU motion data; never run on app startup."""

import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DollFight-course-demo/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    target = ROOT / "apps" / "motion-lab" / "vendor"
    target.mkdir(parents=True, exist_ok=True)
    url = "https://registry.npmjs.org/three/-/three-0.180.0.tgz"
    blob = fetch(url)
    records = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member, name in [
            ("build/three.module.min.js", "three.module.min.js"),
            ("build/three.core.min.js", "three.core.min.js"),
            ("examples/jsm/controls/OrbitControls.js", "OrbitControls.js"),
            ("LICENSE", "THREE-LICENSE.txt"),
        ]:
            content = archive.extractfile("package/" + member).read()
            (target / name).write_bytes(content)
            records.append({"file": name, "sha256": hashlib.sha256(content).hexdigest()})
    (target / "manifest.json").write_text(
        json.dumps({"three_version": "0.180.0", "source": url, "files": records}, indent=2),
        encoding="utf-8",
    )
    print("Vendored Three.js 0.180.0 and its MIT license")
    raw = ROOT / "data" / "raw" / "cmu"
    raw.mkdir(parents=True, exist_ok=True)
    for filename in ("14.asf", "14_01.amc"):
        url = "https://mocap.cs.cmu.edu/subjects/14/" + filename
        try:
            content = fetch(url)
            (raw / filename).write_bytes(content)
            print(filename, len(content), hashlib.sha256(content).hexdigest())
        except Exception as exc:
            print(f"CMU download unavailable: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
