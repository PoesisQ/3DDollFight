"""Review annotations for public mocap, NOT classifier predictions or accuracy labels.

Intervals were chosen from foot lift, extension and return in the CMU sequences.
They are authored game hit windows, not biomechanical measurements. They never
enter ActionRecognizer; only the replay combat adapter consumes them.
"""

import numpy as np

from dollfight.kinematics import unit

# start of preparation, start/end of contact window, end of recovery, limb
TIMINGS = {
    "cmu_roundhouse": [
        (0.43, 0.90, 1.12, 1.87, "right"),
        (3.13, 3.60, 3.82, 4.43, "left"),
        (5.93, 6.33, 6.57, 7.27, "right"),
        (8.83, 9.27, 9.50, 10.20, "left"),
    ],
    "cmu_front_kick": [
        (2.57, 3.03, 3.22, 3.77, "right"),
        (4.30, 4.77, 4.97, 5.57, "left"),
        (6.27, 6.67, 6.87, 7.43, "right"),
    ],
    "cmu_side_kick": [
        (2.35, 2.80, 3.04, 3.70, "right"),
        (4.55, 4.96, 5.18, 5.90, "right"),
        (6.83, 7.25, 7.48, 8.15, "right"),
        (10.40, 10.80, 11.06, 11.70, "left"),
        (12.65, 13.04, 13.29, 13.98, "left"),
    ],
    "cmu_spin_kick": [(0.38, 1.12, 1.42, 2.50, "left")],
    "cmu_lunge_punch": [
        (2.05, 2.38, 2.64, 3.45, "right"),
        (4.03, 4.43, 4.70, 5.42, "left"),
        (6.17, 6.56, 6.82, 7.50, "right"),
    ],
}
REFERENCE_TYPES = {
    "cmu_front_kick": ("kick", "前踢"),
    "cmu_roundhouse": ("roundhouse_kick", "回旋踢"),
    "cmu_side_kick": ("side_kick", "侧踹"),
    "cmu_spin_kick": ("spin_kick", "腾空旋踢"),
    "cmu_lunge_punch": ("straight", "踏步冲拳"),
}
PHASE_LABELS = {
    "ready": "就绪",
    "startup": "前摇 / 无伤害",
    "active": "有效攻击窗口",
    "recovery": "后摇 / 出招锁定",
}

REVIEW_CHAPTERS = {
    "cmu_boxing": [
        {
            "time_s": 2.3,
            "label": "拳击 · 蹬地与转髋",
            "detail": "CMU 拳击连续动作；观察脚、髋、躯干与手的先后关系，无逐拳真值。",
        },
        {
            "time_s": 13.3,
            "label": "侧身与出拳",
            "detail": "观察头部相对骨盆的侧移；身体侧倾和整个人横移是不同的量。",
        },
        {
            "time_s": 22.6,
            "label": "降低重心与换步",
            "detail": "观察屈膝、髋部下降、上身前倾与脚步；连续拳击片段，无独立闪避标签。",
        },
    ]
}


def reference_actions(name):
    result = []
    for i, (start, active, end, recovery, side) in enumerate(TIMINGS.get(name, [])):
        action_type, action_label = REFERENCE_TYPES[name]
        action = side + "_" + action_type
        label = ("左" if side == "left" else "右") + action_label
        result.append(
            {
                "id": f"reference-{i}",
                "action": action,
                "label": label,
                "time_s": start,
                "active_at": active,
                "active_end": end,
                "recovery_end": recovery,
                "basis": "authored_reference",
                "timing": {
                    "startup": active - start,
                    "active": end - active,
                    "recovery": recovery - end,
                },
            }
        )
    return result


def timing_at(actions, time_s):
    for action in actions:
        if action["time_s"] <= time_s < action["recovery_end"]:
            phase = (
                "startup"
                if time_s < action["active_at"]
                else ("active" if time_s < action["active_end"] else "recovery")
            )
            return {
                "phase": phase,
                "phase_label": PHASE_LABELS[phase],
                "label": action["label"],
                "basis": action["basis"],
                "hand_close": float(
                    min(
                        1,
                        (time_s - action["time_s"]) / 0.18,
                        (action["recovery_end"] - time_s) / 0.25,
                    )
                ),
            }
    return (
        {
            "phase": "ready",
            "phase_label": PHASE_LABELS["ready"],
            "label": "动作间歇",
            "basis": "authored_reference",
        }
        if actions
        else None
    )


def body_diagnostics(points, previous, dt):
    hip = points[11] - points[15]
    chest = points[5] - points[8]
    hip_yaw, chest_yaw = np.arctan2(-hip[2], hip[0]), np.arctan2(-chest[2], chest[0])
    twist = (chest_yaw - hip_yaw + np.pi) % (2 * np.pi) - np.pi
    lean = np.arccos(np.clip(unit(points[2] - points[0])[1], -1, 1))
    velocity = (
        np.zeros((2, 3))
        if previous is None
        else (points[[13, 17]] - previous[[13, 17]]) / max(dt, 1e-3)
    )
    support = (points[[13, 17], 1] < 0.19) & (np.linalg.norm(velocity, axis=1) < 0.45)
    label = (
        "双脚支撑"
        if support.all()
        else "左脚支撑"
        if support[0]
        else ("右脚支撑" if support[1] else "换步 / 腾空 / 支撑未确认")
    )
    return {
        "hip_chest_deg": round(float(np.rad2deg(twist)), 1),
        "lean_deg": round(float(np.rad2deg(lean)), 1),
        "support": label,
        "support_feet": support.tolist(),
    }
