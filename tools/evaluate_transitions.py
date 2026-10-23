"""Measure join discontinuities on the edited canonical mocap, before sensor smoothing."""

import json
from pathlib import Path

import numpy as np

from dollfight.transitions import DT, compose_flow


def main():
    hard, smooth = compose_flow(False), compose_flow(True)
    entries = []
    for transition in smooth["transitions"]:
        i = transition["frame"]
        entry = dict(transition)
        for label, clip in (("hard", hard), ("inertial", smooth)):
            points = clip["points"]
            entry[label + "_max_joint_step_mm"] = round(
                float(np.linalg.norm(points[i] - points[i - 1], axis=1).max()) * 1000, 2
            )
            entry[label + "_root_velocity_jump_mps"] = round(
                float(np.linalg.norm(points[i, 0] - 2 * points[i - 1, 0] + points[i - 2, 0])) / DT,
                6,
            )
        entries.append(entry)
    report = {
        "scope": "Five offline joins of CMU clips, canonical skeleton, 30 Hz. "
        "Not a live-user accuracy or perceptual-naturalness score.",
        "method": "same chosen source frames; root yaw/position alignment; "
        "C1 inertial offsets; foot IK",
        "transitions": entries,
    }
    destination = Path("outputs/transition-evaluation.json")
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
