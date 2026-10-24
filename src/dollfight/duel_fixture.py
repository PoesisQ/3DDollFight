"""Two authored joint streams. No attack labels/outcomes are passed to combat.

The schedule only generates input poses, like two recorded people; the solver,
recognizer and geometric resolver still have to derive all events independently.
"""

import numpy as np

from dollfight.kinematics import rest_pose, rotation_y, two_bone_ik
from dollfight.motions import ATTACKS, ease, pose_at

CHAPTERS = [
    {"time_s": 0, "label": "远距挥空", "detail": "识别到拳也不会凭空扣血"},
    {"time_s": 3.4, "label": "逼近 · 三段连招", "detail": "两人前进缩短距离，连续命中才累加连击"},
    {"time_s": 7.6, "label": "后撤与侧闪", "detail": "脚步或身体位移使攻击轨迹落空"},
    {"time_s": 11.5, "label": "高位 / 交叉格挡", "detail": "手臂实际接触攻击轨迹；护头不等于护腿"},
    {"time_s": 16.6, "label": "拨挡 · 反击", "detail": "短时间窗内向外拨拳，获得反击机会"},
    {"time_s": 21.2, "label": "转身鞭拳", "detail": "累计转角与手臂伸展联合识别，碰撞决定命中"},
    {"time_s": 25.0, "label": "旋转踢", "detail": "转体与抬腿联合识别，检查脚部扫过的空间"},
    {"time_s": 29.0, "label": "直拳 → 旋踢", "detail": "动作序列组成输入连招；仍可能被躲开或格挡"},
]

MOVEMENT = [
    [
        (0, 0, 0),
        (3.4, 0, 0),
        (4.6, 0.55, 0),
        (18.9, 0.55, 0),
        (19.4, 0.55, 0.28),
        (20.3, 0.55, 0.28),
        (21.1, 0.55, 0),
        (24.5, 0.55, 0),
        (25.2, 0.42, 0),
        (28.3, 0.42, 0),
        (29.2, 0.55, 0),
        (32, 0.55, 0),
        (34.5, 0, 0),
    ],
    [
        (0, 0, 0),
        (3.4, 0, 0),
        (4.6, 0.55, 0),
        (8.25, 0.55, 0),
        (9.05, 0.12, 0),
        (9.8, 0.55, 0),
        (10.25, 0.55, 0),
        (10.7, 0.55, -0.30),
        (11.0, 0.55, -0.30),
        (11.5, 0.55, 0),
        (32, 0.55, 0),
        (34.5, 0, 0),
    ],
]
BEATS = [
    [
        (1.2, 0.85, "left_straight"),
        (4.85, 0.65, "left_straight"),
        (5.55, 0.65, "right_straight"),
        (6.25, 0.8, "left_hook"),
        (8.25, 1.0, "left_straight"),
        (10.3, 0.85, "right_straight"),
        (12.0, 0.85, "right_straight"),
        (14.0, 1.0, "left_kick"),
        (15.3, 0.85, "left_straight"),
        (17.15, 0.85, "left_straight"),
        (21.8, 1.35, "right_spin_backfist"),
        (29.4, 0.55, "left_straight"),
        (30.0, 1.1, "right_spin_kick"),
    ],
    [(18.0, 0.75, "right_straight"), (19.4, 0.8, "left_straight"), (25.8, 1.4, "right_spin_kick")],
]
GUARDS = [
    [],
    [
        (11.6, 13.2, "high"),
        (13.6, 14.9, "high"),
        (15.0, 16.4, "cross"),
        (16.8, 17.35, "middle"),
        (17.35, 17.8, "parry_right"),
        (21.3, 22.2, "middle"),
    ],
]


def travel_at(time_s, player):
    keys = MOVEMENT[player]
    for a, b in zip(keys, keys[1:], strict=False):
        if a[0] <= time_s <= b[0]:
            u = ease((time_s - a[0]) / (b[0] - a[0]))
            return np.array(a[1:]) * (1 - u) + np.array(b[1:]) * u
    return np.array(keys[-1][1:] if time_s > keys[-1][0] else keys[0][1:])


def duel_pose(time_s, player):
    points = pose_at(0)[0]
    action, amount, progress = None, 0.0, 0.0
    for start, duration, candidate in BEATS[player]:
        if start <= time_s < start + duration:
            action = candidate
            progress = (time_s - start) / duration
            amount = float(ease((progress - 0.12) / 0.30) * (1 - ease((progress - 0.62) / 0.32)))
            if "spin" in candidate:
                amount = float(
                    ease((progress - 0.12) / 0.22) * (1 - ease((progress - 0.82) / 0.18))
                )
    guard, guard_amount = "open", 0.0
    for start, end, kind in GUARDS[player]:
        if start <= time_s <= end:
            guard = kind
            guard_amount = float(
                ease((time_s - start) / 0.16) * (1 - ease((time_s - end + 0.12) / 0.12))
            )
    peak = None
    if action in ATTACKS:
        peak = pose_at(1.2 + (ATTACKS.index(action) + 0.5) * 1.5)[0]
    for side, shoulder, elbow, wrist in (("left", 5, 6, 7), ("right", 8, 9, 10)):
        sign = 1 if side == "left" else -1
        target = points[shoulder] + [sign * 0.015, -0.34, 0.15]
        if (
            action
            and action.startswith(side)
            and (peak is not None)
            and not action.endswith(("kick", "knee"))
        ):
            aimed = peak[wrist]
            if action.endswith("hook"):
                aimed = points[shoulder] + [-sign * 0.29, 0.02, 0.47]
            target = target * (1 - amount) + aimed * amount
        if action == side + "_spin_backfist":
            target = (
                target * (1 - amount) + (points[shoulder] + [-sign * 0.14, 0.01, 0.52]) * amount
            )
        if guard != "open":
            raised = points[shoulder] + [-sign * 0.08, -0.02, 0.28]
            if guard == "high":
                raised = points[shoulder] + [-sign * 0.08, 0.24, 0.27]
            elif guard == "cross":
                raised = points[2] + [-sign * 0.05, 0.16 if side == "left" else 0.11, 0.29]
            elif guard == "parry_" + side:
                raised = points[shoulder] + [sign * 0.14, 0.03, 0.25]
            target = target * (1 - guard_amount) + raised * guard_amount
        points[elbow], points[wrist] = two_bone_ik(
            points[shoulder], target, 0.29, 0.27, points[shoulder] + [sign * 0.30, -0.35, 0.08]
        )
    travel = travel_at(time_s, player)
    velocity = (travel_at(time_s + 0.01, player) - travel_at(time_s - 0.01, player)) / 0.02
    walk = min(1, np.linalg.norm(velocity) / 0.18)
    gait = 2 * np.pi * (travel[0] + travel[1]) / 0.45
    for side, hip, knee, ankle, toe in (("left", 11, 12, 13, 14), ("right", 15, 16, 17, 18)):
        sign = 1 if side == "left" else -1
        target = np.array([sign * 0.105, 0.09, 0.0])
        target += [0, 0.065 * max(0, sign * np.cos(gait)) * walk, 0.14 * sign * np.sin(gait) * walk]
        if action and action.startswith(side) and action.endswith(("kick", "knee")):
            aimed = peak[ankle] if peak is not None else np.array([0.0, 1.0, 0.83])
            target = target * (1 - amount) + aimed * amount
        points[knee], points[ankle] = two_bone_ik(
            points[hip],
            target,
            np.hypot(0.43, 0.015),
            np.hypot(0.43, 0.015),
            points[hip] + [0, 0.1, 0.8],
        )
        points[toe] = points[ankle] + [0, -0.05, 0.17]
    if action and "spin" in action:
        pelvis = points[0].copy()
        points = (points - pelvis) @ rotation_y(2 * np.pi * ease(progress / 0.80)).T + pelvis
    points += [travel[1], 0, travel[0]]
    return points


def duel_clip(player, fps=30):
    times = np.arange(35 * fps) / fps
    return {
        "name": "duel",
        "source": "paired_synthetic",
        "fps": fps,
        "points": np.array([duel_pose(t, player) for t in times]),
        "rest": rest_pose(),
        "description": "双人合成骨架：进退、侧闪、格挡、拨挡、旋转与组合；几何判定命中。",
    }
