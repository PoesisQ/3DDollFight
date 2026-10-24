"""Offline mocap composition with velocity-preserving inertial offsets and foot IK.

This edits captured clips; it is not live motion matching or a physics simulator.
Join intervals are manually selected. Authored attack intervals stay separate from recognition.
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from dollfight.kinematics import (
    PARENTS,
    Retargeter,
    leg_ik_hint,
    quaternion,
    rest_pose,
    rotation_y,
    swing_rotation,
    two_bone_ik,
)
from dollfight.motion_reference import reference_actions

ROOT = Path(__file__).resolve().parents[2]
FPS = 30
DT = 1 / FPS
PLAN = (
    ("cmu_boxing", 1.5, 5.2, "拳击 · 全身发力"),
    ("cmu_front_kick", 1.6, 4.1, "收架 → 前踢"),
    ("cmu_low_block", 1.0, 4.0, "回收 → 下段格挡"),
    ("cmu_roundhouse", 5.0, 7.9, "换重心 → 回旋踢"),
    ("cmu_knife_guard", 0.5, 3.2, "落脚 → 手刀防御"),
    ("cmu_boxing", 13.0, 16.5, "回架 → 拳击"),
)
FOOTWORK_PLAN = (
    ("cmu_walk", 0.10, 0.95, "前进接近 · 真人步态"),
    ("cmu_boxing", 1.5, 3.9, "落脚 → 护架出拳"),
    ("cmu_retreat_punch", 0.2, 2.7, "后退拉开 · 真人退步"),
    ("cmu_strafe", 0.8, 2.6, "侧移 · 重心换脚"),
    ("cmu_low_block", 1.0, 3.4, "收步 → 下段格挡"),
    ("cmu_strafe_right", 0.8, 2.6, "反向侧移 · 镜像真人步态"),
    ("cmu_backwalk", 8.4, 10.6, "退步调整距离 · 真人脚步"),
    ("cmu_front_kick", 1.6, 4.1, "支撑脚落稳 → 前踢回收"),
    ("cmu_backwalk", 8.4, 10.6, "退步脱离 · 非动作倒放"),
)


def multiply(a, b):
    a, b = np.asarray(a), np.asarray(b)
    v = a[..., 3:] * b[..., :3] + b[..., 3:] * a[..., :3] + np.cross(a[..., :3], b[..., :3])
    w = a[..., 3:] * b[..., 3:] - np.sum(a[..., :3] * b[..., :3], axis=-1, keepdims=True)
    return np.concatenate((v, w), axis=-1)


def inverse(q):
    return np.asarray(q) * [-1, -1, -1, 1]


def log_rotation(q):
    q = np.asarray(q)
    q = np.where(q[..., 3:] < 0, -q, q)
    length = np.linalg.norm(q[..., :3], axis=-1, keepdims=True)
    return q[..., :3] * (2 * np.arctan2(length, q[..., 3:]) / np.maximum(length, 1e-12))


def exp_rotation(v):
    angle = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.concatenate((v * np.sinc(angle / (2 * np.pi)) / 2, np.cos(angle / 2)), axis=-1)


def matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def fk(root, rotations, rest):
    points, globals_ = np.empty_like(rest), []
    for i, parent in enumerate(PARENTS):
        local = matrix(rotations[i])
        globals_.append(local if parent < 0 else globals_[parent] @ local)
        points[i] = (
            root if parent < 0 else points[parent] + globals_[parent] @ (rest[i] - rest[parent])
        )
    return points, globals_


def inertial_offset(offset, velocity, time, duration):
    """C1 Hermite decay: preserve initial offset/velocity, reach zero with zero velocity."""
    u = np.clip(time / duration, 0, 1)
    return offset * (1 - 3 * u * u + 2 * u * u * u) + velocity * duration * (
        u - 2 * u * u + u * u * u
    )


def constrain_feet(root, rotations, rest, anchors):
    rotations = rotations.copy()
    points, globals_ = fk(root, rotations, rest)
    for ankle, (anchor, weight) in anchors.items():
        hip, knee = ankle - 2, ankle - 1
        target = points[ankle] * (1 - weight) + anchor * weight
        k, a = two_bone_ik(
            points[hip],
            target,
            np.linalg.norm(rest[knee] - rest[hip]),
            np.linalg.norm(rest[ankle] - rest[knee]),
            leg_ik_hint(
                points[hip],
                points[knee],
                points[ankle],
                target,
                globals_[hip] @ np.array([0.0, 0.0, 1.0]),
            ),
        )
        hip_rot = swing_rotation(points[knee] - points[hip], k - points[hip]) @ globals_[hip]
        knee_rot = swing_rotation(points[ankle] - points[knee], a - k) @ globals_[knee]
        rotations[hip] = quaternion(globals_[PARENTS[hip]].T @ hip_rot)
        rotations[knee] = quaternion(hip_rot.T @ knee_rot)
        rotations[ankle] = quaternion(knee_rot.T @ globals_[ankle])
    return rotations


@lru_cache(maxsize=16)
def normalized_clip(name):
    if name == "cmu_strafe_right":
        points, _ = normalized_clip("cmu_strafe")
        order = [0, 1, 2, 3, 4, 8, 9, 10, 5, 6, 7, 15, 16, 17, 18, 11, 12, 13, 14]
        mirrored = points[:, order] * [-1, 1, 1]
        retarget = Retargeter(rest_pose(), target_rest=rest_pose(), foot_lock=True)
        result = [retarget.process(p, DT)[:2] for p in mirrored]
        return np.array([p for p, _ in result]), np.array([q for _, q in result])
    clip = json.loads((ROOT / f"data/samples/{name}.json").read_text(encoding="utf-8"))
    rest = rest_pose()
    retarget = Retargeter(clip["rest"], target_rest=rest, foot_lock=True)
    points, rotations = [], []
    for source in clip["points"]:
        p, q, _ = retarget.process(np.asarray(source), DT)
        points.append(p)
        rotations.append(q)
    return np.asarray(points), np.asarray(rotations)


def align(points, rotations, start, old_points, old_q, fixed_heading=False):
    old = matrix(old_q[0])
    new = matrix(rotations[start, 0])
    yaw = (
        0 if fixed_heading else np.arctan2(old[0, 2], old[2, 2]) - np.arctan2(new[0, 2], new[2, 2])
    )
    basis = rotation_y(yaw)
    origin = points[start, 0] * [1, 0, 1]
    aligned = (points - origin) @ basis.T + old_points[0] * [1, 0, 1]
    q = rotations.copy()
    q[:, 0] = multiply(quaternion(basis), rotations[:, 0])
    return aligned, q


def support(points, previous, rest):
    feet = points[[13, 17]]
    return (feet[:, 1] < rest[[13, 17], 1] + 0.065) & (
        np.linalg.norm(feet - previous[[13, 17]], axis=1) / DT < 0.45
    )


def compose_flow(blend=True, duration=0.6, footwork=False):
    rest = rest_pose()
    output, output_q, joins, chapters, actions = [], [], [], [], []
    for segment, (name, begin, end, label) in enumerate(FOOTWORK_PLAN if footwork else PLAN):
        points, rotations = normalized_clip(name)
        start, stop = round(begin * FPS), min(round(end * FPS), len(points))
        if output:
            # Choose a nearby stance with compatible pose, velocity and support.
            # Search is confined before the next annotated preparation interval.
            old_support = support(output[-1], output[-2], rest)
            choices = []
            for candidate in range(start, min(start + 9, stop - 2)):
                p, q = align(points, rotations, candidate, output[-1], output_q[-1], footwork)
                mismatch = np.linalg.norm(
                    (p[candidate] - p[candidate, 0]) - (output[-1] - output[-1][0]), axis=1
                )
                velocity = (p[candidate] - p[candidate - 1] - output[-1] + output[-2]) / DT
                new_support = support(p[candidate], p[candidate - 1], rest)
                cost = np.mean(mismatch) + 0.04 * np.mean(np.linalg.norm(velocity, axis=1))
                cost += 0.2 * np.sum(old_support != new_support)
                choices.append((cost, candidate))
            _, start = min(choices)
            points, rotations = align(points, rotations, start, output[-1], output_q[-1], footwork)
            predicted_q = multiply(multiply(output_q[-1], inverse(output_q[-2])), output_q[-1])
            offset = log_rotation(multiply(predicted_q, inverse(rotations[start])))
            before = log_rotation(multiply(output_q[-1], inverse(rotations[start - 1])))
            angular_velocity = (offset - before) / DT
            root_velocity = (output[-1][0] - output[-2][0]) / DT
            root_offset = output[-1][0] + root_velocity * DT - points[start, 0]
            root_delta = root_velocity - (points[start, 0] - points[start - 1, 0]) / DT
            eligible = old_support & support(points[start], points[start - 1], rest)
            anchors = {
                a: output[-1][a].copy() for a, yes in zip((13, 17), eligible, strict=True) if yes
            }
            releases = {}
            joins.append(
                {
                    "frame": len(output),
                    "time_s": len(output) / FPS,
                    "target": name,
                    "source_time": start / FPS,
                    "duration": duration,
                    "anchored_feet": list(anchors),
                    "selection_cost": float(min(choices)[0]),
                }
            )
        time_shift = len(output) / FPS - start / FPS
        chapters.append(
            {
                "time_s": len(output) / FPS,
                "label": label,
                "detail": "真人片段组合 · 人工选择连接区间，再匹配姿态、速度和支撑脚；"
                "非一次连续采集。",
            }
        )
        for action in reference_actions(name):
            if (
                start / FPS + (duration if segment else 0) <= action["time_s"]
                and action["recovery_end"] < stop / FPS
            ):
                action = {**action, "id": f"flow-{segment}-{action['id']}"}
                for key in ("time_s", "active_at", "active_end", "recovery_end"):
                    action[key] += time_shift
                actions.append(action)
        for i in range(start, stop):
            q, root = rotations[i].copy(), points[i, 0].copy()
            elapsed = (i - start) / FPS
            if segment and blend and elapsed < duration:
                q = multiply(
                    exp_rotation(inertial_offset(offset, angular_velocity, elapsed, duration)), q
                )
                q /= np.linalg.norm(q, axis=1, keepdims=True)
                root += inertial_offset(root_offset, root_delta, elapsed, duration)
                locked = {}
                current_support = support(points[i], points[i - 1], rest)
                for ankle, anchor in anchors.items():
                    side = 0 if ankle == 13 else 1
                    if not current_support[side] and ankle not in releases:
                        releases[ankle] = elapsed
                    release = min(duration - 0.16, releases.get(ankle, duration))
                    weight = float(np.clip((release + 0.16 - elapsed) / 0.16, 0, 1))
                    weight = weight * weight * (3 - 2 * weight)
                    locked[ankle] = (anchor, weight)
                q = constrain_feet(root, q, rest, locked)
            p, _ = fk(root, q, rest)
            output.append(p)
            output_q.append(q)
    return {
        "name": "cmu_footwork" if footwork else "cmu_flow",
        "source": "cmu_composed_mocap",
        "fps": FPS,
        "points": np.asarray(output),
        "rest": rest,
        "reference_actions": actions,
        "chapters": chapters,
        "transitions": joins,
        "description": (
            "真人前进 / 退步 / 双向侧移与拳踢组合；"
            if footwork
            else "真人拳击 / 前踢 / 格挡 / 回旋踢组合；"
        )
        + ("姿态与速度衔接 + 支撑脚 IK。" if blend else "硬切对照：保留姿态跳变。")
        + "非同一次采集，过渡是算法编辑。",
    }
