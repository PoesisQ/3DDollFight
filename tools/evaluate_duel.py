"""Reproducible paired-motion checks, including an ablation of root movement."""

import hashlib
import json
import platform
from pathlib import Path

from dollfight.duel import build_duel
from dollfight.pipeline import make_run

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = {
        "version": "0.4.0",
        "python": platform.python_version(),
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "cases": {},
        "limitations": [
            "Authored streams informed the rules: regression checks, not real-player accuracy.",
            "No camera, network, or live end-to-end latency is measured.",
            "Input combos and actual hit chains are evaluated separately.",
        ],
    }
    for noise in (0, 5):
        config = {"source": "duel", "noise_mm": noise, "seed": 42}
        p1, p2 = make_run(config), make_run(config, player=1)
        for enabled in (True, False):
            name = f"noise_{noise}mm_movement_{enabled}"
            settings = {**config, "movement_enabled": enabled}
            duel = build_duel(p1, p2, settings)
            report["cases"][name] = {
                "config": settings,
                "summary": duel["summary"],
                "health": duel["frames"][-1]["health"],
                "closest_root_distance_m": min(f["distance_m"] for f in duel["frames"]),
                "input_combos": [e for e in p1["events"] if e.get("combo")],
                "events": duel["events"],
            }
            print(name, duel["summary"], "HP", duel["frames"][-1]["health"], flush=True)
    path = ROOT / "outputs/duel-evaluation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
