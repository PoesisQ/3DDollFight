"""Replay the actual local VRM proportions through the mocap movement pipeline."""

import argparse
import json
from pathlib import Path

import numpy as np

from dollfight.avatar_audit import HUMAN_BONES, EmbeddedGLB
from dollfight.pipeline import make_run

ROOT = Path(__file__).resolve().parents[1]


def evaluate():
    model = EmbeddedGLB((ROOT / "data/avatars/local/nozomi.vrm").read_bytes())
    human = model.doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    skin = model.doc["skins"][0]
    # Local builder emits identity rest rotations, with world translations in IBM.
    inverse = model.accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    rest = [-inverse[skin["joints"].index(human[name]["node"]), :3, 3] for name in HUMAN_BONES]
    run = make_run(
        {
            "source": "cmu_footwork",
            "noise_mm": 0,
            "dropout": 0,
            "initial_gap": 3.2,
            "target_rest": np.array(rest).tolist(),
        },
        include_duel=True,
    )
    frames, duel = run["frames"], run["duel"]["frames"]
    roots = np.array([frame["root"] for frame in frames])
    speeds = []
    for previous, frame in zip(frames, frames[1:], strict=False):
        for side, ankle in enumerate((13, 17)):
            if previous["contacts"][side] and frame["contacts"][side]:
                delta = np.array(frame["avatar"][ankle]) - previous["avatar"][ankle]
                speeds.append(float(np.linalg.norm(delta) / (frame["t"] - previous["t"])))
    return {
        "source": "cmu_footwork",
        "target_avatar": "data/avatars/local/nozomi.vrm",
        "duration_s": run["duration"],
        "frames": len(frames),
        "initial_gap_m": 3.2,
        "root_xz_span_m": np.ptp(roots[:, [0, 2]], axis=0).tolist(),
        "station_clamped_frames": sum(any(m["clamped"] for m in f["movement"]) for f in duel),
        "separation_limited_frames": sum(f["separation_limited"] for f in duel),
        "processing_metrics": run["metrics"],
        "estimated_support_ankle_speed_mps_p50_p95": np.quantile(speeds, [0.5, 0.95]).tolist(),
        "estimated_support_samples": len(speeds),
        "note": "Support flags are algorithm estimates, not independent ground truth. "
        "Timing is single-person CPU replay; excludes camera, pose estimation, duel and rendering.",
        "assets": json.loads(
            (ROOT / "data/avatars/local/manifest.json").read_text(encoding="utf-8")
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/local-rig-motion.json")
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "assets"}, indent=2))
