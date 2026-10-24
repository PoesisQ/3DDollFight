"""Portable replay artifact for Unity Humanoid. Not a camera transport protocol."""

import numpy as np

from dollfight.kinematics import PARENTS, quaternion, rotation_y


def multiply(a, b):
    av, bv = np.asarray(a[:3]), np.asarray(b[:3])
    return np.r_[a[3] * bv + b[3] * av + np.cross(av, bv), a[3] * b[3] - av @ bv]


def vector(v):
    return dict(zip(("x", "y", "z"), map(float, v), strict=True))


def export_animation(run):
    frames = []
    for frame in run["frames"]:
        global_rotations = []
        for i, parent in enumerate(PARENTS):
            q = np.array(frame["rotations"][i])
            if parent >= 0:
                q = multiply(global_rotations[parent], q)
            q /= np.linalg.norm(q)
            global_rotations.append(q)
        frames.append(
            {
                "time": frame["t"],
                "root": vector(frame["root"]),
                "handClose": float(
                    frame.get("performance", {}).get(
                        "hand_close", frame.get("action_timing", {}).get("hand_close", 0.15)
                    )
                ),
                "rotations": [
                    dict(zip(("x", "y", "z", "w"), map(float, q), strict=True))
                    for q in global_rotations
                ],
            }
        )
    return {
        "version": "dollfight-humanoid-1",
        "coordinates": "stage_rh_y_up_meters",
        "rotationSpace": "global_delta_from_canonical_t_pose",
        "source": run["name"],
        "fps": run["fps"],
        "rest": [vector(p) for p in run["target_rest"]],
        "frames": frames,
    }


def export_duel(run):
    """Same arena roots/headings as Motion Lab, applied exactly once.

    Both output streams use the shared rehearsal clock, including repeated or
    remapped opponent indices. Canonical root X/Z is already represented by
    duel.positions, so adding it again would cause the old runaway translation.
    """
    duel = run["duel"]
    players = []
    for player, yaw in enumerate((np.pi / 2, -np.pi / 2)):
        source = run["frames"] if player == 0 else duel["opponent_frames"]
        frames = []
        heading = quaternion(rotation_y(yaw))
        for i, arena in enumerate(duel["frames"]):
            frame = source[i if player == 0 else arena["opponent_frame"]]
            rotations = np.array(frame["rotations"], dtype=float)
            rotations[0] = multiply(heading, rotations[0])
            root = np.array(arena["positions"][player], dtype=float)
            root[1] += frame["root"][1]
            frames.append({**frame, "t": arena["t"], "root": root, "rotations": rotations})
        players.append(export_animation({**run, "frames": frames}))
    timeline = {
        "version": "dollfight-duel-1",
        "duration": run["duration"],
        "fps": run["fps"],
        "source": "CMU motion capture rehearsal; not live camera input",
        "frames": [
            {
                "time": f["t"],
                "round": f["round"],
                "health": f["health"],
                "distance": f["distance_m"],
                "intent": f.get("intent", [""])[0],
            }
            for f in duel["frames"]
        ],
    }
    return players, timeline
