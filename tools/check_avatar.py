"""Offline GLB/VRM intake check. Does not modify or upload the asset."""

import argparse
import json
from pathlib import Path

from dollfight.avatar_audit import audit_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = audit_file(args.asset)
    except (OSError, ValueError) as exc:
        report = {
            "file": args.asset.name,
            "errors": [str(exc)],
            "motion_lab_structural_candidate": False,
            "visual_quality_verified": False,
        }
    text = json.dumps(report, ensure_ascii=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
