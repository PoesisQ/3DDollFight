"""Three-round, two-stream mocap rehearsal, not live players or a trained policy.

Captured poses retain their joint rotations; an authored combat trajectory edits
root travel. Short strides, contact IK and C1 inertial joins replace unconstrained
concatenation of metre-long walking/turning clips. Outcomes still use geometry.
"""

from functools import lru_cache

import numpy as np

from dollfight.kinematics import quaternion, rest_pose, rotation_y
from dollfight.motion_reference import reference_actions
from dollfight.transitions import (
    DT,
    FPS,
    constrain_feet,
    exp_rotation,
    fk,
    inertial_offset,
    inverse,
    log_rotation,
    matrix,
    multiply,
    normalized_clip,
)

ROUND_SECONDS = 30.0
ROUND_COUNT = 3

# duration, P1 motion, P2 motion, P1 forward/left goal, P2 goal, intent
EXCHANGES = (
    (2.0, "advance", "advance", (0.59, 0), (0.59, 0), "接近 · 短步进入拳距"),
    (3.2, "boxing_a", "guard", (0.59, 0.02), (0.59, -0.02), "试探拳 · 护架与回收"),
    (2.0, "retreat", "advance", (0.23, 0.02), (0.56, -0.02), "退步让距 · 对手跟进"),
    (3.4, "guard", "front_kick", (0.29, 0.02), (0.61, -0.02), "前踢 · 防守与后摇"),
    (2.0, "advance", "side", (0.40, -0.06), (0.36, 0.13), "再接近 · 小幅侧移"),
    (3.0, "roundhouse", "low_block", (0.40, -0.06), (0.34, 0.13), "转髋高踢 · 降低重心"),
    (2.0, "advance", "advance", (0.59, 0), (0.59, 0), "回架 · 双方再接近"),
    (3.4, "guard", "boxing_b", (0.59, 0), (0.59, 0), "连续拳 · 近身攻防"),
    (2.0, "side", "retreat", (0.38, 0.12), (0.18, -0.06), "横移找角度 · 退步脱离"),
    (3.0, "front_kick", "roundhouse", (0.46, 0.08), (0.40, -0.04), "踢击交换 · 保留前后摇"),
    (4.0, "retreat", "retreat", (0, 0), (0, 0), "拉开回架 · 下一回合"),
)

MOTIONS = {
    "advance": ("cmu_walk", 0.10, 0.95),
    "retreat": ("cmu_retreat_punch", 0.30, 1.5),
    "side": ("cmu_strafe", 0.8, 1.6),
    "boxing_a": ("cmu_boxing", 1.65, 4.85),
    "boxing_b": ("cmu_boxing", 4.5, 7.9),
    "guard": ("cmu_boxing", 20.4, 21.2),
    "front_kick": ("cmu_front_kick", 1.7, 4.1),
    "roundhouse": ("cmu_roundhouse", 5.0, 7.9),
    "low_block": ("cmu_low_block", 1.0, 3.8),
}


def smoothstep(t):
    t = np.clip(t, 0, 1)
    return t * t * t * (10 + t * (-15 + 6 * t))


def slerp_array(a, b, alpha):
    """Shortest quaternion interpolation, including near-identical rotations."""
    b = np.where(np.sum(a * b, axis=-1, keepdims=True) < 0, -b, b)
    delta = log_rotation(multiply(b, inverse(a)))
    return multiply(exp_rotation(delta * alpha), a)


@lru_cache(maxsize=32)
def excerpt(kind, variant=0):
    name, begin, end = MOTIONS[kind]
    if kind == "boxing_a" and variant == 2:
        begin, end = 7.5, 10.7
    if kind == "boxing_b" and variant == 2:
        begin, end = 13.0, 16.4
    if kind == "roundhouse" and variant == 1:
        begin, end = 7.9, 10.8
    if kind == "front_kick" and variant == 1:
        begin, end = 3.65, 6.05
    p, q = normalized_clip(name)
    start, stop = round(begin * FPS), round(end * FPS)
    p, q = p[start:stop].copy(), q[start:stop].copy()
    # Heading comes from a quiet entry window, never from accumulated last-pose
    # hip twist. Preserve the actual turn throughout a roundhouse.
    yaw = np.median([np.arctan2(matrix(r[0])[0, 2], matrix(r[0])[2, 2]) for r in q[:8]])
    attack_refs = [
        a for a in reference_actions(name) if begin <= a["time_s"] and a["recovery_end"] <= end
    ]
    if attack_refs:
        # A fighter stands obliquely. Align the recorded strike's travel to the
        # opponent, not the hips during that oblique preparation stance.
        a = attack_refs[0]
        joint = 13 if a["action"].startswith("left") else 17
        lo, hi = round((a["active_at"] - begin) * FPS), round((a["active_end"] - begin) * FPS)
        vectors = p[lo : hi + 1, joint] - p[lo : hi + 1, 0]
        direction = vectors[np.argmax(np.linalg.norm(vectors[:, [0, 2]], axis=1))]
        yaw = np.arctan2(direction[0], direction[2])
    elif kind.startswith("boxing"):
        reaches = (p[:, [7, 10]] - p[:, None, 0]).reshape(-1, 3)
        reaches = reaches[
            (reaches[:, 2] > 0.30) & (np.linalg.norm(reaches[:, [0, 2]], axis=1) > 0.4)
        ]
        if len(reaches):
            direction = np.median(reaches, axis=0)
            yaw = np.arctan2(direction[0], direction[2])
    basis = rotation_y(-yaw)
    p = p @ basis.T
    q[:, 0] = multiply(quaternion(basis), q[:, 0])
    refs = []
    for action in reference_actions(name):
        if begin <= action["time_s"] and action["recovery_end"] <= end:
            refs.append(
                {
                    **action,
                    **{
                        key: action[key] - begin
                        for key in ("time_s", "active_at", "active_end", "recovery_end")
                    },
                }
            )
    if kind.startswith("boxing"):
        # Replay-only timing annotation from extension extrema. This is kept
        # separate from the causal recognizer, whose event timing is also shown.
        # Starting a hit window after retraction made visually touching punches
        # miss; the rehearsal needs windows around the actual captured reach.
        peaks = []
        for side, joint in (("left", 7), ("right", 10)):
            reach = p[:, joint, 2] - p[:, 2, 2]
            for i in range(7, len(p) - 8):
                if reach[i] > 0.28 and reach[i] == np.max(reach[i - 5 : i + 6]):
                    if reach[i] - min(reach[i - 7], reach[i + 7]) > 0.07:
                        peaks.append((i, side, reach[i]))
        chosen = []
        for peak in sorted(peaks, key=lambda a: -a[2]):
            if all(abs(peak[0] - old[0]) >= 10 for old in chosen):
                chosen.append(peak)
        for index, (peak, side, _) in enumerate(sorted(chosen)):
            active = peak / FPS - 0.075
            refs.append(
                {
                    "id": f"extension-{index}",
                    "action": side + "_straight",
                    "label": ("左" if side == "left" else "右") + "拳击",
                    "time_s": active - 0.18,
                    "active_at": active,
                    "active_end": active + 0.15,
                    "recovery_end": active + 0.32,
                    "basis": "offline_extension_annotation",
                    "timing": {"startup": 0.18, "active": 0.15, "recovery": 0.17},
                }
            )
    return p, q, refs


def sample(p, q, at):
    i = min(int(at), len(p) - 1)
    j = min(i + 1, len(p) - 1)
    a = at - i
    return p[i] * (1 - a) + p[j] * a, slerp_array(q[i], q[j], a)


def compose_player(player, rounds):
    rest = rest_pose()
    roots, rotations, contacts, chapters, actions, metadata = [], [], [], [], [], []
    goal = np.zeros(2)
    guard_p, guard_q, _ = excerpt("guard")
    for rnd in range(rounds):
        for stage, (duration, first, second, goal_a, goal_b, label) in enumerate(EXCHANGES):
            actor = player ^ (rnd % 2)
            kind = (first, second)[actor]
            target = np.array((goal_a, goal_b)[actor], dtype=float)
            if rnd == 2:
                target[1] *= -1
            count = round(duration * FPS)
            p, q, refs = excerpt(kind, rnd)
            moving = kind in ("advance", "retreat", "side")
            if kind == "side" and target[1] < goal[1]:
                mirror = [0, 1, 2, 3, 4, 8, 9, 10, 5, 6, 7, 15, 16, 17, 18, 11, 12, 13, 14]
                p, q = p[:, mirror] * [-1, 1, 1], q[:, mirror] * [1, -1, -1, 1]
            begin = len(roots) / FPS
            if player == 0:
                chapters.append(
                    {
                        "time_s": begin,
                        "label": f"R{rnd + 1} · {label}",
                        "detail": "双人独立编排 · 真人动作经步幅与轨迹编辑；伤害由空间接触结算。",
                    }
                )
            # One short captured step, then settle into guard. Do not stretch a
            # 0.8-second walking step into four seconds of slow-motion skating.
            move_time = min(1.3, duration - 0.35) if moving else duration
            active_time = len(p) / FPS if not moving and kind != "guard" else move_time
            scale = duration / active_time if not moving and kind != "guard" else 1
            if kind not in ("guard", "advance", "retreat", "side"):
                for action in refs:
                    event = {**action, "id": f"r{rnd}-s{stage}-p{player}-{action['id']}"}
                    for key in ("time_s", "active_at", "active_end", "recovery_end"):
                        event[key] = begin + action[key] * scale
                    event["timing"] = {
                        key: value * scale for key, value in action["timing"].items()
                    }
                    actions.append(event)
            initial_goal = goal.copy()
            stride = (
                np.clip(
                    np.linalg.norm(target - goal)
                    / max(0.01, np.linalg.norm((p[-1, 0] - p[0, 0])[[0, 2]])),
                    0.35,
                    1.05,
                )
                if moving
                else 1
            )
            previous_source = None
            for k in range(count):
                t = k / FPS
                if kind == "guard" or (moving and t > move_time):
                    # Smooth ping-pong in a quiet captured guard window; no jump
                    # at its loop seam. This isn't generated attack motion.
                    phase = (1 - np.cos(t * np.pi / 1.2)) / 2
                    sp, sq = sample(guard_p, guard_q, phase * (len(guard_p) - 1))
                else:
                    phase = min(1, t / (move_time if moving else duration))
                    sp, sq = sample(p, q, phase * (len(p) - 1))
                    if moving:
                        # Mask only the arms: retain captured pelvis, spine,
                        # knees, feet and weight shift, but carry a fighting guard.
                        sq[5:11] = guard_q[len(guard_q) // 2, 5:11]
                path = initial_goal + smoothstep(t / move_time) * (target - initial_goal)
                root = np.array([path[1], sp[0, 1], path[0]])
                if moving and t <= move_time:
                    pose, _ = fk(root, sq, rest)
                    targets = {}
                    for ankle in (13, 17):
                        relative = pose[ankle] - root
                        neutral = rest[ankle] - rest[0]
                        axis = 0 if kind == "side" else 2
                        relative[axis] = neutral[axis] + (relative[axis] - neutral[axis]) * stride
                        targets[ankle] = (root + relative, 1)
                    sq = constrain_feet(root, sq, rest, targets)
                if kind not in ("guard", "advance", "retreat", "side"):
                    # Keep small local weight shifts, remove long capture-room
                    # travel. Zero displacement at both ends prevents drift.
                    u = t / duration
                    deviation = sp[0] - ((1 - u) * p[0, 0] + u * p[-1, 0])
                    root[[0, 2]] += np.clip(deviation[[0, 2]], -0.03, 0.03) * np.sin(np.pi * u)
                speed = (
                    np.full(2, 1.0)
                    if previous_source is None
                    else np.linalg.norm(sp[[13, 17]] - previous_source[[13, 17]], axis=1) / DT
                )
                contact = (sp[[13, 17], 1] < rest[[13, 17], 1] + 0.065) & (speed < 0.38)
                previous_source = sp
                # Inertialize every change of excerpt, including step -> guard.
                boundary = k == 0 or (moving and k == int(move_time * FPS) + 1)
                if boundary and rotations:
                    offset = log_rotation(multiply(rotations[-1], inverse(sq)))
                    velocity = (
                        log_rotation(multiply(rotations[-1], inverse(rotations[-2]))) / DT
                        if len(rotations) > 1
                        else np.zeros_like(offset)
                    )
                    height_offset = roots[-1][1] - root[1]
                    height_velocity = (roots[-1][1] - roots[-2][1]) / DT if len(roots) > 1 else 0
                    blend_start = t
                if (k or roots) and "blend_start" in locals() and 0 <= t - blend_start < 0.4:
                    sq = multiply(
                        exp_rotation(inertial_offset(offset, velocity, t - blend_start, 0.4)), sq
                    )
                    root[1] += inertial_offset(height_offset, height_velocity, t - blend_start, 0.4)
                roots.append(root)
                rotations.append(sq)
                contacts.append(contact)
                metadata.append(
                    {
                        "round": rnd + 1,
                        "round_time": round((begin + t) % ROUND_SECONDS, 4),
                        "intent": kind,
                        "label": label,
                        "hand_close": 0.8 if kind != "low_block" else 0.25,
                    }
                )
            goal = target
    return np.array(roots), np.array(rotations), np.array(contacts), actions, chapters, metadata


@lru_cache(maxsize=2)
def rehearsal_pair(rounds=ROUND_COUNT):
    """Both roots share a combat frame; contact anchors are world-space in it."""
    tracks = [compose_player(p, rounds) for p in range(2)]
    rest = rest_pose()
    output = []
    for player, (roots, rotations, contacts, actions, chapters, metadata) in enumerate(tracks):
        other = tracks[1 - player][0]
        yaw = -np.arctan2(roots[:, 0] + other[:, 0], 1.8 - roots[:, 2] - other[:, 2])
        points, anchors, weights = [], {}, np.zeros(2)
        for i, (root, q, contact) in enumerate(zip(roots, rotations, contacts, strict=True)):
            q = q.copy()
            q[0] = multiply(quaternion(rotation_y(yaw[i])), q[0])
            pose, _ = fk(root, q, rest)
            locked = {}
            for side, ankle in enumerate((13, 17)):
                if contact[side] and side not in anchors:
                    anchors[side] = pose[ankle].copy()
                    anchors[side][1] = rest[ankle, 1]
                weights[side] = np.clip(
                    weights[side] + DT / (0.08 if contact[side] else -0.10), 0, 1
                )
                if side in anchors:
                    if weights[side] > 0:
                        locked[ankle] = (anchors[side], float(smoothstep(weights[side])))
                    else:
                        del anchors[side]
            q = constrain_feet(root, q, rest, locked)
            pose, _ = fk(root, q, rest)
            # Inertial transitions can temporarily put a swinging foot below
            # the floor even when both endpoint poses are grounded.
            floor_targets = {}
            for ankle in (13, 17):
                if pose[ankle, 1] < rest[ankle, 1] - 0.015:
                    target = pose[ankle].copy()
                    target[1] = rest[ankle, 1] - 0.015
                    floor_targets[ankle] = (target, 1)
            if floor_targets:
                q = constrain_feet(root, q, rest, floor_targets)
                pose, _ = fk(root, q, rest)
            points.append(pose)
        output.append(
            {
                "name": "cmu_sparring",
                "source": "cmu_composed_mocap",
                "fps": FPS,
                "rest": rest,
                "points": np.array(points),
                "reference_actions": actions,
                "chapters": chapters,
                "performance": metadata,
                "description": f"{rounds} 回合 / {rounds * 30} 秒双人排练："
                "真实动捕 + 短步轨迹编辑 + 接地 IK。"
                "双方独立编排，非真人同时采集或自主对战；命中仍由碰撞计算。",
            }
        )
    return output


def rehearsal_clip(player=0):
    return rehearsal_pair()[player]
