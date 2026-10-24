"""Deterministic ablations; this is a replay benchmark, not a camera accuracy test."""

import hashlib
import json
import platform
from pathlib import Path

from dollfight.motions import ATTACKS
from dollfight.pipeline import make_run

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "showcase_clean": {"source": "showcase", "noise_mm": 0},
    "showcase_noisy_raw": {
        "source": "showcase",
        "noise_mm": 15,
        "smoothing": False,
        "constraints": False,
    },
    "showcase_noisy_solved": {"source": "showcase", "noise_mm": 15},
    "showcase_dropout": {"source": "showcase", "noise_mm": 15, "dropout": 0.15},
    "occlusion": {"source": "occlusion", "noise_mm": 15},
    "noisy_idle": {"source": "idle", "noise_mm": 30},
    "cmu_clean": {"source": "cmu_boxing", "noise_mm": 0},
    "cmu_noisy": {"source": "cmu_boxing", "noise_mm": 15},
}


def main():
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seed": 42,
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "cases": {},
        "limitations": [
            "Synthetic action trajectories also informed the hand-written thresholds.",
            "CMU has no per-action labels here: event count is not accuracy.",
            "Time is CPU solver + recognizer + retargeter only, not end-to-end latency.",
            "Raw/solved error compares the same observed joints; missing error is separate.",
        ],
    }
    for name, config in CASES.items():
        run = make_run({**config, "seed": 42})
        actions = [event["action"] for event in run["events"]]
        result = {"config": run["config"], "metrics": run["metrics"], "actions": actions}
        if config["source"] == "showcase":
            result["expected_synthetic_sequence"] = ATTACKS
            result["exact_synthetic_sequence"] = actions == ATTACKS
        report["cases"][name] = result
        print(name, json.dumps(run["metrics"]), flush=True)
    path = ROOT / "outputs/evaluation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
