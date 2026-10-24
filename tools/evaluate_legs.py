"""Compare leg geometry in saved replay runs; this is not a naturalness score."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from dollfight.kinematics import segment_basis

ROOT = Path(__file__).resolve().parents[1]


def summarize(run):
    players = []
    for frames in (run["frames"], run["duel"]["opponent_frames"]):
        points = np.array([f["avatar"] for f in frames])
        flags = []
        for hip, knee, ankle, toe in ((11, 12, 13, 14), (15, 16, 17, 18)):
            axis = points[:, ankle] - points[:, hip]
            axis /= np.linalg.norm(axis, axis=1)[:, None]
            pole = points[:, knee] - points[:, hip]
            pole -= axis * np.einsum("ij,ij->i", pole, axis)[:, None]
            foot = points[:, toe] - points[:, ankle]
            foot -= axis * np.einsum("ij,ij->i", foot, axis)[:, None]
            lengths = np.linalg.norm(pole, axis=1)
            cosine = np.einsum("ij,ij->i", pole, foot) / np.maximum(
                lengths * np.linalg.norm(foot, axis=1), 1e-9
            )
            # A foot and its knee pointing strongly opposite is a diagnostic
            # candidate. Straight knees have no reliable measured bend plane.
            ids = np.flatnonzero((cosine < -0.30) & (lengths > 0.05))
            flags.append({"count": len(ids), "times_s": [frames[i]["t"] for i in ids]})
        snapshots = []
        for time in (1.5, 8.3):
            frame = min(frames, key=lambda f: abs(f["t"] - time))
            p = np.asarray(frame["avatar"])
            basis = segment_basis(p[11] - p[15], p[1] - p[0])
            snapshots.append(
                {
                    "t": frame["t"],
                    "anatomical_lateral_foot_spacing_m": float((p[13] - p[17]) @ basis[:, 0]),
                    "legs_in_body_frame_m": ((p - p[0]) @ basis)[11:].round(5).tolist(),
                }
            )
        players.append({"opposed_knee_foot_candidates": flags, "reported_frames": snapshots})
    return {
        "players": players,
        "candidate_leg_samples": sum(
            f["count"] for p in players for f in p["opposed_knee_foot_candidates"]
        ),
        "total_leg_samples": len(run["frames"]) * 4,
        "limits": [
            "Geometric screening only, not independent ground truth or a naturalness rating.",
            "Toe direction is an imperfect prior during turns; candidates require visual review.",
            "Joint positions miss skin twist; regression tests also check full bone frames.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, default=ROOT / "outputs/sparring-latest.json")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/leg-review.json")
    args = parser.parse_args()
    report = {"current": summarize(json.loads(args.frames.read_text(encoding="utf-8")))}
    report["current"]["frames_sha256"] = hashlib.sha256(args.frames.read_bytes()).hexdigest()
    if args.baseline:
        report["baseline"] = summarize(json.loads(args.baseline.read_text(encoding="utf-8")))
        report["baseline"]["frames_sha256"] = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                k: {
                    "candidate_leg_samples": v["candidate_leg_samples"],
                    "total_leg_samples": v["total_leg_samples"],
                }
                for k, v in report.items()
            }
        )
    )
