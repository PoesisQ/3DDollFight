"""Three-round, two-stream mocap rehearsal, not live players or a trained policy.

Captured poses retain their joint rotations; an authored combat trajectory edits
root travel. Short strides, contact IK and C1 inertial joins replace unconstrained
concatenation of metre-long walking/turning clips. Outcomes still use geometry.
"""

from functools import lru_cache

import numpy as np

from dollfight.foot_contact import FootHeadingLock
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
    # 76_04 is a progressively deep forward duck, not an idle guard. Holding
    # its 30-degree pelvis pitch made every pause look like a prolonged bow.
    "guard": ("cmu_boxing", 1.75, 2.10),
    "front_kick": ("cmu_front_kick", 1.7, 4.1),
    "roundhouse": ("cmu_roundhouse", 5.0, 7.9),
    "low_block": ("cmu_low_block", 1.0, 3.8),
    "side_kick": ("cmu_side_kick", 4.1, 6.2),
    "spin_kick": ("cmu_spin_kick", 0.05, 3.10),
    "lunge_punch": ("cmu_lunge_punch", 1.7, 5.6),
    "empi": ("cmu_empi", 8.0, 11.4),
    "knife_guard": ("cmu_knife_guard", 0.5, 3.2),
}


def exchange_plan(rnd):
    """Different exchanges per round, with complete preparation and recovery."""
    changes = (
        {
            5: ("side_kick", "low_block", "侧踹 · 收膝、蹬伸与回收"),
            9: ("roundhouse", "front_kick", "回旋踢与前踢 · 横扫与直线送腿"),
        },
        {
            1: ("lunge_punch", "guard", "踏步双冲拳 · 蹬地与转髋"),
            3: ("guard", "side_kick", "反侧侧踹 · 护头等待回收"),
            5: ("roundhouse", "knife_guard", "回旋踢 · 转髋与手刀架防"),
            7: ("guard", "empi", "提手、冲拳与换步 · 连续套路"),
            9: ("roundhouse", "side_kick", "回旋踢与侧踹 · 两种发力路线"),
        },
        {
            3: ("guard", "roundhouse", "回旋踢 · 侧向扫击"),
            5: ("side_kick", "knife_guard", "侧踹 · 侧身蹬伸"),
            7: ("guard", "lunge_punch", "踏步冲拳 · 重心随出拳前送"),
            9: ("spin_kick", "retreat", "腾空旋踢 · 蓄力、转身与落地"),
        },
    )[rnd % 3]
    result = []
    for i, (duration, first, second, a, b, label) in enumerate(EXCHANGES):
        first, second, label = changes.get(i, (first, second, label))
        result.append((duration, first, second, a, b, label))
    return result


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
    if kind == "side_kick" and variant == 1:
        begin, end = 10.0, 12.1
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
        left = a["action"].startswith("left")
        joint = (13 if left else 17) if a["action"].endswith("kick") else (7 if left else 10)
        lo, hi = round((a["active_at"] - begin) * FPS), round((a["active_end"] - begin) * FPS)
        vectors = p[lo : hi + 1, joint] - p[lo : hi + 1, 0]
        direction = vectors[np.argmax(np.linalg.norm(vectors[:, [0, 2]], axis=1))]
        yaw = np.arctan2(direction[0], direction[2])
    elif kind.startswith("boxing") or kind == "empi":
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
    if kind.startswith("boxing") or kind == "empi":
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
                    "label": ("左" if side == "left" else "右")
                    + ("套路冲拳" if kind == "empi" else "拳击"),
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


def inertialize_track(roots, rotations, boundaries, duration=0.30):
    """Join edited samples using the outgoing-minus-incoming velocity.

    Keeping only outgoing velocity adds the new clip's velocity a second time
    and overshoots knees during step-to-guard transitions. This is offline
    composition, so the next incoming sample is available without live latency.
    """
    roots, rotations = np.array(roots), np.array(rotations)
    raw_roots, raw_q = roots.copy(), rotations.copy()
    for begin in boundaries:
        if begin < 2 or begin + 1 >= len(roots):
            continue
        incoming = multiply(raw_q[begin + 1], inverse(raw_q[begin]))
        outgoing = multiply(rotations[begin - 1], inverse(rotations[begin - 2]))
        predicted = multiply(outgoing, rotations[begin - 1])
        incoming_previous = multiply(inverse(incoming), raw_q[begin])
        offset = log_rotation(multiply(predicted, inverse(raw_q[begin])))
        previous_offset = log_rotation(multiply(rotations[begin - 1], inverse(incoming_previous)))
        velocity = (offset - previous_offset) / DT
        old_height_speed = (roots[begin - 1, 1] - roots[begin - 2, 1]) / DT
        new_height_speed = (raw_roots[begin + 1, 1] - raw_roots[begin, 1]) / DT
        height_offset = roots[begin - 1, 1] + old_height_speed * DT - raw_roots[begin, 1]
        for i in range(begin, min(len(roots), begin + round(duration * FPS))):
            elapsed = (i - begin) * DT
            rotations[i] = multiply(
                exp_rotation(inertial_offset(offset, velocity, elapsed, duration)), raw_q[i]
            )
            roots[i, 1] = raw_roots[i, 1] + inertial_offset(
                height_offset, old_height_speed - new_height_speed, elapsed, duration
            )
    return roots, rotations


def compose_player(player, rounds):
    rest = rest_pose()
    roots, rotations, contacts, chapters, actions, metadata = [], [], [], [], [], []
    boundaries = []
    goal = np.zeros(2)
    guard_p, guard_q, _ = excerpt("guard")
    for rnd in range(rounds):
        for stage, (duration, first, second, goal_a, goal_b, label) in enumerate(
            exchange_plan(rnd)
        ):
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
            move_time = min(len(p) / FPS, duration - 0.35) if moving else duration
            active_time = min(len(p) / FPS, duration) if kind != "guard" else duration
            if not moving and duration - active_time < 0.35:
                # Do not insert a 0.1 s guard that is interrupted by the next
                # exchange halfway through its inertial blend.
                active_time = duration
            # Keep preparation, impact and recovery at captured speed. Spare
            # exchange time belongs to guard, not slow-motion anticipation.
            scale = active_time / (len(p) / FPS)
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
                    0.12,
                    1.05,
                )
                if moving
                else 1
            )
            previous_source = None
            for k in range(count):
                t = k / FPS
                settling = (moving and t > move_time) or (not moving and t >= active_time)
                if kind == "guard" or settling:
                    # Dedicated planted defensive capture, not the stepping
                    # interval in the boxing take. Slow weight transfer closes
                    # the loop without reversing a lifted walking foot.
                    phase = (1 - np.cos(t * np.pi / 2.0)) / 2
                    sp, sq = sample(guard_p, guard_q, phase * (len(guard_p) - 1))
                else:
                    phase = min(1, t / (move_time if moving else active_time))
                    sp, sq = sample(p, q, phase * (len(p) - 1))
                    if moving:
                        # Mask only the arms: retain captured pelvis, spine,
                        # knees, feet and weight shift, but carry a fighting guard.
                        sq[5:11] = guard_q[len(guard_q) // 2, 5:11]
                path = initial_goal + smoothstep(t / move_time) * (target - initial_goal)
                root = np.array([path[1], sp[0, 1], path[0]])
                if kind == "guard" or settling:
                    # Remove the drift of this captured lean; preserve its
                    # small acceleration rather than repeatedly stepping back.
                    local_shift = sp[0] - ((1 - phase) * guard_p[0, 0] + phase * guard_p[-1, 0])
                    root[[0, 2]] += 0.025 * np.tanh(local_shift[[0, 2]] / 0.025)
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
                if kind not in ("guard", "advance", "retreat", "side") and not settling:
                    # Preserve the captured shift over the supporting leg. A
                    # smooth bound prevents travel accumulating across clips;
                    # the former 3 cm hard clamp erased most of the wind-up.
                    u = t / active_time
                    deviation = sp[0] - ((1 - u) * p[0, 0] + u * p[-1, 0])
                    root[[0, 2]] += (
                        0.12 * np.tanh(deviation[[0, 2]] / 0.12) * np.sin(np.pi * u) ** 2
                    )
                speed = (
                    np.full(2, 1.0)
                    if previous_source is None
                    else np.linalg.norm(sp[[13, 17]] - previous_source[[13, 17]], axis=1) / DT
                )
                contact = (sp[[13, 17], 1] < rest[[13, 17], 1] + 0.065) & (speed < 0.38)
                previous_source = sp
                # Inertialize every change of excerpt, including step -> guard.
                end_motion = move_time if moving else active_time
                boundary = k == 0 or (
                    settling and k == int(end_motion * FPS) + (1 if moving else 0)
                )
                if boundary and rotations:
                    boundaries.append(len(roots))
                roots.append(root)
                rotations.append(sq)
                contacts.append(contact)
                metadata.append(
                    {
                        "round": rnd + 1,
                        "round_time": round((begin + t) % ROUND_SECONDS, 4),
                        "intent": kind,
                        "label": label,
                        "hand_close": 0.65
                        if settling or kind == "guard"
                        else (0.15 if kind in ("low_block", "knife_guard") else 0.80),
                    }
                )
            goal = target
    roots, rotations = inertialize_track(roots, rotations, boundaries)
    return roots, rotations, np.array(contacts), actions, chapters, metadata


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
        previous_feet = None
        headings = [FootHeadingLock(), FootHeadingLock()]
        for i, (root, q, contact) in enumerate(zip(roots, rotations, contacts, strict=True)):
            q = q.copy()
            q[0] = multiply(quaternion(rotation_y(yaw[i])), q[0])
            pose, global_rotations = fk(root, q, rest)
            hinge_targets = {}
            for hip, knee, ankle in ((11, 12, 13), (15, 16, 17)):
                axis = pose[ankle] - pose[hip]
                pole = pose[knee] - pose[hip]
                pole -= axis * (pole @ axis) / (axis @ axis)
                if pole @ global_rotations[hip][:, 2] < -1e-5:
                    # Inertial decay may overshoot through a straight knee.
                    # Project back to its anatomical hinge half-plane while
                    # preserving the edited ankle target and both bone lengths.
                    hinge_targets[ankle] = (pose[ankle].copy(), 1)
            if hinge_targets:
                q = constrain_feet(root, q, rest, hinge_targets)
                pose, _ = fk(root, q, rest)
            feet = pose[[13, 17]].copy()
            # Captured contact labels no longer suffice after trajectory and
            # transition edits. An old guard anchor must not drag a new kick's
            # planted foot across the other leg. Observe the edited world pose
            # and only correct small residual motion while it remains planted.
            speed = (
                np.full(2, np.inf)
                if previous_feet is None
                else np.linalg.norm(feet - previous_feet, axis=1) / DT
            )
            previous_feet = feet
            locked = {}
            for side, ankle in enumerate((13, 17)):
                active = bool(contact[side] and speed[side] < 0.30)
                if side in anchors and np.linalg.norm(pose[ankle] - anchors[side]) > 0.10:
                    active = False
                if active and side not in anchors:
                    anchors[side] = pose[ankle].copy()
                    anchors[side][1] = rest[ankle, 1]
                weights[side] = np.clip(weights[side] + DT / (0.08 if active else -0.10), 0, 1)
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
            pose, global_rotations = fk(root, q, rest)
            for side, ankle in enumerate((13, 17)):
                correction = headings[side].update(
                    pose[ankle],
                    pose[ankle + 1],
                    rest[ankle],
                    rest[ankle + 1],
                    bool(contact[side] and speed[side] < 0.30),
                    DT,
                )
                q[ankle] = quaternion(
                    global_rotations[ankle - 1].T @ correction @ global_rotations[ankle]
                )
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
