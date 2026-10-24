"""Portable replay artifact for Unity Humanoid. Not a camera transport protocol."""

import numpy as np

from dollfight.kinematics import PARENTS


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
