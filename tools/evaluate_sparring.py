"""Evaluate all three rounds with the actual VRM proportions and warm the replay cache."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from dollfight.avatar_audit import HUMAN_BONES, EmbeddedGLB
from dollfight.server import replay_run

ROOT = Path(__file__).resolve().parents[1]


def actual_config():
    path = ROOT / "data/avatars/local/nozomi-hybrid.vrm"
    model = EmbeddedGLB(path.read_bytes())
    human = model.doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    skin = model.doc["skins"][0]
    ibm = model.accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    rest = np.array([-ibm[skin["joints"].index(human[n]["node"]), :3, 3] for n in HUMAN_BONES])
    return {
        "source": "cmu_sparring",
        "transition_blend": True,
        "noise_mm": 0,
        "dropout": 0,
        "cutoff": 1.7,
        "smoothing": True,
        "constraints": True,
        "foot_lock": True,
        "profile": "standard",
        "movement_enabled": True,
        "movement_gain": 1,
        "initial_gap": 1.8,
        "seed": 42,
        "target_rest": rest.round(6).tolist(),
    }


def evaluate(run):
    duel = run["duel"]
    positions = np.array([f["positions"] for f in duel["frames"]])
    foot_speeds = []
    for stream in (run["frames"], duel["opponent_frames"]):
        for prev, cur in zip(stream, stream[1:], strict=False):
            for side, ankle in enumerate((13, 17)):
                if prev["contacts"][side] and cur["contacts"][side]:
                    foot_speeds.append(
                        np.linalg.norm(np.array(cur["avatar"][ankle]) - prev["avatar"][ankle])
                        / (cur["t"] - prev["t"])
                    )
    return {
        "duration_s": run["duration"],
        "frames_per_player": len(run["frames"]),
        "independent_streams": duel["paired"],
        "rounds": duel["rounds"],
        "distance_range_m": [
            min(f["distance_m"] for f in duel["frames"]),
            max(f["distance_m"] for f in duel["frames"]),
        ],
        "root_step_max_m": float(np.max(np.linalg.norm(np.diff(positions, axis=0), axis=2))),
        "arena_xz_span_m": np.ptp(positions[..., [0, 2]], axis=0).tolist(),
        "separation_clamped_frames": sum(f["separation_limited"] for f in duel["frames"]),
        "estimated_support_speed_p50_p95_mps": np.quantile(foot_speeds, [0.5, 0.95]).tolist(),
        "combat_summary": duel["summary"],
        "combat_events": duel["events"],
        "processing_metrics": run["metrics"],
        "avatar_sha256": {
            name: hashlib.sha256(
                (ROOT / f"data/avatars/local/{name}-hybrid.vrm").read_bytes()
            ).hexdigest()
            for name in ("nozomi", "mizore")
        },
        "limits": [
            "Authored public-mocap rehearsal, not live camera input or autonomous gameplay.",
            "Attack windows are independent replay annotations, not recognition ground truth.",
            "Foot support is estimated; speed is not an independent foot-slide accuracy score.",
            "CPU pipeline timing excludes rendering, capture and network.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/sparring-report.json")
    parser.add_argument("--frames", type=Path, default=ROOT / "outputs/sparring-latest.json")
    args = parser.parse_args()
    run = replay_run(actual_config(), include_duel=True)
    report = evaluate(run)
    for path, value in ((args.output, report), (args.frames, run)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=None, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "combat_events"}, indent=2))
