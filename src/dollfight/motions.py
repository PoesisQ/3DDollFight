"""Deterministic, kinematically valid fixtures, separate from the recognizer."""

import numpy as np

from dollfight.kinematics import rest_pose, rotation_y, two_bone_ik, unit

ATTACKS = [
    "left_straight",
    "right_straight",
    "left_hook",
    "right_hook",
    "left_uppercut",
    "right_uppercut",
    "left_knee",
    "right_knee",
    "left_kick",
    "right_kick",
    "crouch",
    "dodge_left",
    "dodge_right",
]


def ease(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def pose_at(time_s, mode="showcase"):
    p = rest_pose()
    action = None
    amount = 0.0
    cycle = (time_s - 1.2) / 1.5
    if mode in ("showcase", "occlusion", "turn") and 0 <= cycle < len(ATTACKS):
        action = ATTACKS[int(cycle)]
        phase = cycle % 1
        amount = float(ease((phase - 0.12) / 0.30) * (1 - ease((phase - 0.62) / 0.32)))
    if mode == "punch":
        cycle = (time_s - 1.2) / 1.8
        if 0 <= cycle < 6:
            action = "left_straight" if int(cycle) % 2 == 0 else "right_straight"
            phase = cycle % 1
            amount = float(ease((phase - 0.12) / 0.30) * (1 - ease((phase - 0.62) / 0.32)))
    if action == "crouch":
        p[:12, 1] -= amount * 0.24
        p[15, 1] -= amount * 0.24
    if action and action.startswith("dodge"):
        shift = amount * (0.24 if action.endswith("left") else -0.24)
        p[1:11, 0] += shift * np.array([0.35, 0.75, 0.95, 1, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75])
    reference = rest_pose()
    for parent, child in ((0, 1), (1, 2), (2, 3), (3, 4), (2, 5), (2, 8)):
        length = np.linalg.norm(reference[child] - reference[parent])
        p[child] = p[parent] + unit(p[child] - p[parent]) * length
    for side, shoulder, elbow, wrist in (("left", 5, 6, 7), ("right", 8, 9, 10)):
        sign = 1 if side == "left" else -1
        target = p[shoulder] + [sign * 0.015, 0.02, 0.22]
        if action == side + "_straight":
            target += np.array([-sign * 0.04, 0.02, 0.33]) * amount
        elif action == side + "_hook":
            target += np.array([-sign * 0.43, 0.02, 0.18]) * amount
        elif action == side + "_uppercut":
            target += np.array([-sign * 0.03, 0.33, 0.14]) * amount
        p[elbow], p[wrist] = two_bone_ik(
            p[shoulder], target, 0.29, 0.27, p[shoulder] + [sign * 0.3, -0.4, 0.08]
        )
    for side, hip, knee, ankle, toe in (("left", 11, 12, 13, 14), ("right", 15, 16, 17, 18)):
        sign = 1 if side == "left" else -1
        target = np.array([sign * 0.105, 0.09, 0.0])
        if action == side + "_knee":
            target += np.array([0, 0.41, 0.28]) * amount
        elif action == side + "_kick":
            target += np.array([0, 0.71, 0.80]) * amount
        p[knee], p[ankle] = two_bone_ik(
            p[hip], target, np.hypot(0.43, 0.015), np.hypot(0.43, 0.015), p[hip] + [0, 0.1, 0.8]
        )
        p[toe] = p[ankle] + [0, -0.05, 0.17]
    if mode == "idle":
        p[:, 0] += 0.015 * np.sin(time_s * 1.2)
        p[4, 2] += 0.008 * np.sin(time_s * 2)
    if mode == "turn":
        p = p @ rotation_y(0.7 * np.sin(time_s * 0.3)).T
    return p, action if amount > 0.1 else None


def synthetic_clip(mode="showcase", fps=30):
    duration = 22.0 if mode in ("showcase", "occlusion", "turn") else 13.0
    times = np.arange(int(duration * fps)) / fps
    frames = [pose_at(t, mode) for t in times]
    return {
        "name": mode,
        "source": "synthetic",
        "fps": fps,
        "points": np.array([x[0] for x in frames]),
        "labels": [x[1] for x in frames],
        "rest": rest_pose(),
        "description": "程序生成的固定骨长轨迹；用于可控验证，不代表真人识别准确率。",
    }
