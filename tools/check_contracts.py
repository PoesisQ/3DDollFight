"""Check the small synthetic fixtures from any working directory."""

import json
from pathlib import Path

from dollfight.contracts import validate_message


def main() -> None:
    fixture_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    fixtures = sorted(fixture_dir.glob("*.json"))
    if not fixtures:
        raise RuntimeError("No fixtures found")
    for path in fixtures:
        validate_message(json.loads(path.read_text(encoding="utf-8")))
        print(f"PASS {path.name}")
    print(f"Validated {len(fixtures)} synthetic protocol fixtures; no camera was used.")


if __name__ == "__main__":
    main()
