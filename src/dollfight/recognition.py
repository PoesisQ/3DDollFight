"""Causal movement events with confidence gates, hysteresis and recovery.

No clip names, frame labels or expected action schedules enter this module.
"""

import numpy as np

from dollfight.kinematics import body_basis, unit

LABELS = {
    "left_side_kick": "左侧踹",
    "right_side_kick": "右侧踹",
    "left_roundhouse_kick": "左回旋踢",
    "right_roundhouse_kick": "右回旋踢",
    "left_spin_backfist": "左转身鞭拳",
    "right_spin_backfist": "右转身鞭拳",
    "left_spin_kick": "左旋转踢",
    "right_spin_kick": "右旋转踢",
    "left_straight": "左直拳",
    "right_straight": "右直拳",
    "left_hook": "左勾拳",
    "right_hook": "右勾拳",
    "left_uppercut": "左上勾拳",
    "right_uppercut": "右上勾拳",
    "left_knee": "左膝击",
    "right_knee": "右膝击",
    "left_kick": "左前踢",
    "right_kick": "右前踢",
    "crouch": "下蹲",
    "dodge_left": "左闪避",
    "dodge_right": "右闪避",
}

COMBOS = [
    (("left_straight", "right_straight", "left_hook"), "刺拳 → 直拳 → 摆拳"),
    (("right_straight", "left_straight", "right_uppercut"), "双直拳 → 上勾终结"),
    (("left_straight", "right_spin_kick"), "直拳牵制 → 旋踢"),
    (("left_straight", "right_roundhouse_kick"), "直拳牵制 → 回旋踢"),
]

DEFENSE_LABELS = {
    "open": "未设防",
    "middle": "中位护架",
    "high": "高位护头",
    "cross": "交叉格挡",
    "single": "单臂护架",
    "parry": "侧向拨挡",
    "low": "下段防守（候选）",
}


class ActionRecognizer:
    def __init__(self, rest):
        self.rest = np.asarray(rest)
        self.arm_scale = {
            side: (
                np.linalg.norm(self.rest[b] - self.rest[a])
                + np.linalg.norm(self.rest[c] - self.rest[b])
            )
            / 0.56
            for side, a, b, c in (("left", 5, 6, 7), ("right", 8, 9, 10))
        }
        self.leg_scale = {
            side: (
                np.linalg.norm(self.rest[b] - self.rest[a])
                + np.linalg.norm(self.rest[c] - self.rest[b])
            )
            / (2 * np.hypot(0.43, 0.015))
            for side, a, b, c in (("left", 11, 12, 13), ("right", 15, 16, 17))
        }
        self.body_scale = max(np.linalg.norm(self.rest[4] - self.rest[0]) / 0.7, 0.1)
        self.previous = None
        self.previous_time = None
        self.last_events = {
            name: -10.0 for name in ("left_arm", "right_arm", "left_leg", "right_leg", "body")
        }
        self.armed = dict.fromkeys(self.last_events, True)
        self.event_counter = 0
        self.previous_yaw = None
        self.yaw_rate = 0.0
        self.spin_turn = 0.0
        self.spin_used = False
        self.spin_quiet = 0.0
        self.parry_until = -1.0
        self.parry_side = None
        self.parry_id = 0
        self.parry_last = -1.0
        self.attack_history = []
        self.knee_candidate_since = {"left": None, "right": None}

    def defense_state(self, local, velocity, valid, time_s):
        sides = []
        heights = []
        low_sides = []
        for side, shoulder, elbow, wrist in (("left", 5, 6, 7), ("right", 8, 9, 10)):
            relative = (local[wrist] - local[shoulder]) / max(self.arm_scale[side], 0.1)
            reliable = np.all(valid[[0, 2, 5, 8, elbow, wrist]])
            low_guard = (
                reliable
                and 0.16 < relative[2] < 0.65
                and -0.7 < relative[1] <= -0.30
                and local[elbow, 1] > local[wrist, 1] + 0.08
            )
            if reliable and (
                (0.10 < relative[2] < 0.40 and -0.30 < relative[1] < 0.4) or low_guard
            ):
                sides.append(side)
                heights.append(relative[1])
                if low_guard:
                    low_sides.append(side)
                outward_speed = velocity[wrist, 0] * (1 if side == "left" else -1)
                if (
                    not low_guard
                    and outward_speed / self.arm_scale[side] > 0.65
                    and abs(relative[0]) < 0.33
                    and time_s - self.parry_last > 0.5
                ):
                    self.parry_side, self.parry_until = side, time_s + 0.22
                    self.parry_id += 1
                    self.parry_last = time_s
        mode = "open" if not sides else "single"
        if len(sides) == 2:
            mode = "high" if min(heights) > 0.13 else "middle"
            if local[7, 0] < local[10, 0] - 0.025:
                mode = "cross"
        if low_sides:
            mode = "low"
        if self.parry_side in sides and time_s <= self.parry_until:
            mode = "parry"
        return {
            "mode": mode,
            "label": DEFENSE_LABELS[mode],
            "guard_sides": sides,
            "parry_until": self.parry_until,
            "parry_side": self.parry_side,
            "parry_id": self.parry_id,
        }

    def process(self, points, valid, time_s):
        if self.previous_time is not None and time_s <= self.previous_time:
            raise ValueError("Recognizer timestamps must increase")
        basis = body_basis(points)
        local = (points - points[0]) @ basis
        dt = 0.033 if self.previous_time is None else time_s - self.previous_time
        velocity = (
            np.zeros_like(points)
            if self.previous is None or dt > 0.25
            else (local - self.previous) / dt
        )
        self.previous, self.previous_time = local, time_s
        trunk_valid = bool(np.all(valid[[0, 2, 5, 8]]))
        defense = self.defense_state(local, velocity, valid, time_s)
        yaw = float(np.arctan2(basis[0, 2], basis[2, 2]))
        delta_yaw = (
            0.0
            if self.previous_yaw is None
            else ((yaw - self.previous_yaw + np.pi) % (2 * np.pi) - np.pi)
        )
        self.previous_yaw = yaw
        if not trunk_valid or dt > 0.25 or abs(delta_yaw) > np.pi / 2:
            self.yaw_rate, self.spin_turn, self.spin_used = 0.0, 0.0, False
        else:
            self.yaw_rate += (1 - np.exp(-dt / 0.065)) * (delta_yaw / dt - self.yaw_rate)
            if abs(self.yaw_rate) > 1.0:
                if self.yaw_rate * self.spin_turn < 0:
                    self.spin_turn = 0.0
                self.spin_turn += delta_yaw
                self.spin_quiet = time_s
            elif time_s - self.spin_quiet > 0.24:
                self.spin_turn, self.spin_used = 0.0, False
        # A fast boxing twist is not a spin. Require a substantial, consistent
        # turn before suppressing ordinary punches; reset on direction reversal.
        rotating = abs(self.spin_turn) > 1.0
        leg_engaged = any(
            valid[ankle] and (points[ankle, 1] - self.rest[ankle, 1]) / self.leg_scale[side] > 0.25
            for side, ankle in (("left", 13), ("right", 17))
        )
        events = []
        state = "guard"
        phase = {
            "left_arm": "ready",
            "right_arm": "ready",
            "left_leg": "ready",
            "right_leg": "ready",
        }

        def emit(action, channel, confidence):
            self.event_counter += 1
            events.append(
                {
                    "id": f"event-{self.event_counter}",
                    "time_s": round(time_s, 4),
                    "action": action,
                    "label": LABELS[action],
                    "confidence": round(confidence, 3),
                }
            )
            self.last_events[channel] = time_s
            self.armed[channel] = False

        if rotating and abs(self.spin_turn) > 2.1 and not self.spin_used and trunk_valid:
            spin_action = None
            for side, hip, knee, ankle in (("left", 11, 12, 13), ("right", 15, 16, 17)):
                if (
                    np.all(valid[[hip, knee, ankle]])
                    and (points[ankle, 1] - self.rest[ankle, 1]) / self.leg_scale[side] > 0.28
                    and np.linalg.norm(points[ankle] - points[hip]) / self.leg_scale[side] > 0.62
                ):
                    spin_action = side + "_spin_kick"
            if spin_action is None:
                for side, shoulder, elbow, wrist in (("left", 5, 6, 7), ("right", 8, 9, 10)):
                    if (
                        np.all(valid[[shoulder, elbow, wrist]])
                        and np.linalg.norm(local[wrist] - local[shoulder]) / self.arm_scale[side]
                        > 0.40
                        and (local[wrist, 1] - local[shoulder, 1]) / self.arm_scale[side] > -0.18
                        and (
                            (local[wrist, 2] - local[shoulder, 2]) / self.arm_scale[side] > 0.24
                            or abs(local[wrist, 0] - local[shoulder, 0]) / self.arm_scale[side]
                            > 0.30
                        )
                    ):
                        spin_action = side + "_spin_backfist"
            if spin_action:
                channel = spin_action.split("_")[0] + (
                    "_leg" if spin_action.endswith("kick") else "_arm"
                )
                emit(spin_action, channel, 0.82)
                phase[channel] = "committed"
                self.spin_used = True
        for side, shoulder, elbow, wrist in (("left", 5, 6, 7), ("right", 8, 9, 10)):
            channel = side + "_arm"
            scale = max(self.arm_scale[side], 0.1)
            relative = (local[wrist] - local[shoulder]) / scale
            wrist_velocity = velocity[wrist] / scale
            forward, vertical, lateral = relative[2], relative[1], abs(relative[0])
            speed = np.linalg.norm(wrist_velocity)
            if not trunk_valid or not np.all(valid[[shoulder, elbow, wrist]]):
                phase[channel] = "unreliable"
                self.armed[channel] = False
                continue
            if rotating:
                continue
            # A lifted kicking leg often produces large balancing arm sweeps.
            # They are not independent punches. A future learned model can
            # support intentional simultaneous techniques; this rule abstains.
            if leg_engaged:
                phase[channel] = "supporting"
                continue
            if relative[1] < -0.30:
                phase[channel] = "defending" if side in defense["guard_sides"] else "ready"
                continue
            if defense["mode"] in ("high", "cross") or (
                defense["mode"] == "parry" and defense["parry_side"] == side
            ):
                phase[channel] = "defending"
                continue
            neutral = forward < 0.30 and vertical < 0.13 and lateral < 0.13
            if neutral and time_s - self.last_events[channel] > 0.22:
                self.armed[channel] = True
            if not self.armed[channel]:
                phase[channel] = "recovery"
                continue
            if speed > 0.35:
                phase[channel] = "preparation"
            action = None
            if vertical > 0.20 and wrist_velocity[1] > 0.28:
                action = side + "_uppercut"
            elif lateral > 0.24 and abs(wrist_velocity[0]) > 0.35:
                action = side + "_hook"
            elif forward > 0.43 and wrist_velocity[2] > 0.35 and vertical < 0.20 and lateral < 0.23:
                action = side + "_straight"
            if action and time_s - self.last_events[channel] > 0.4:
                emit(action, channel, min(0.97, 0.65 + speed * 0.12))
                phase[channel] = "committed"
        for side, hip, knee, ankle in (("left", 11, 12, 13), ("right", 15, 16, 17)):
            channel = side + "_leg"
            scale = max(self.leg_scale[side], 0.1)
            knee_lift = (points[knee, 1] - self.rest[knee, 1]) / scale
            foot_forward = ((points[ankle] - points[hip]) @ basis[:, 2]) / scale
            foot_height = (points[ankle, 1] - self.rest[ankle, 1]) / scale
            foot_lateral = ((points[ankle] - points[hip]) @ basis[:, 0]) / scale
            extension_speed = (
                float((velocity[ankle] - velocity[hip]) @ unit(local[ankle] - local[hip])) / scale
            )
            if not trunk_valid or not np.all(valid[[hip, knee, ankle]]):
                phase[channel] = "unreliable"
                self.armed[channel] = False
                self.knee_candidate_since[side] = None
                continue
            if self.spin_used or abs(self.spin_turn) > 1.75:
                continue
            if foot_height < 0.10 and knee_lift < 0.10 and time_s - self.last_events[channel] > 0.3:
                self.armed[channel] = True
            if not self.armed[channel]:
                phase[channel] = "recovery"
                continue
            angle = np.arccos(
                np.clip(
                    unit(points[hip] - points[knee]) @ unit(points[ankle] - points[knee]), -1, 1
                )
            )
            action = None
            if (
                (foot_forward > 0.50 or (abs(foot_lateral) > 0.40 and foot_forward > 0.20))
                and angle > np.deg2rad(125)
                and foot_height > 0.20
                and extension_speed > 0.25
            ):
                # A side thrust extends mainly across the body's lateral plane,
                # with the torso leaning away. A roundhouse continues forward
                # as it sweeps. This is a conservative geometric candidate, not
                # a trained martial-arts classifier or a replay-label lookup.
                side_thrust = (
                    abs(foot_lateral) > 0.45
                    and abs(foot_lateral) > 1.6 * max(foot_forward, 0)
                    and (local[ankle, 1] - local[hip, 1]) / scale < -0.10
                )
                action = side + (
                    "_side_kick"
                    if side_thrust
                    else "_roundhouse_kick"
                    if abs(foot_lateral) > 0.30
                    else "_kick"
                )
                self.knee_candidate_since[side] = None
            elif (
                not rotating
                and knee_lift > 0.32
                and foot_forward < 0.35
                and angle < np.deg2rad(110)
            ):
                # Do not commit a knee strike at the first chamber frame. A
                # front/roundhouse kick first lifts a bent knee, then extends.
                if self.knee_candidate_since[side] is None:
                    self.knee_candidate_since[side] = time_s
                if time_s - self.knee_candidate_since[side] >= 0.18:
                    action = side + "_knee"
                phase[channel] = "preparation"
            elif knee_lift > 0.12:
                self.knee_candidate_since[side] = None
                phase[channel] = "preparation"
            else:
                self.knee_candidate_since[side] = None
            if action and time_s - self.last_events[channel] > 0.5:
                emit(action, channel, 0.85)
                phase[channel] = "committed"
        crouch = (self.rest[0, 1] - points[0, 1]) / self.body_scale
        left_flat = unit([basis[0, 0], 0, basis[2, 0]], (1, 0, 0))
        lean = ((points[4] - points[0]) @ left_flat) / self.body_scale
        if crouch < 0.1 and abs(lean) < 0.12:
            self.armed["body"] = True
        if (
            trunk_valid
            and valid[4]
            and self.armed["body"]
            and not leg_engaged
            and time_s - self.last_events["body"] > 0.7
        ):
            if crouch > 0.18:
                emit("crouch", "body", 0.85)
            elif abs(lean) > 0.18:
                emit("dodge_left" if lean > 0 else "dodge_right", "body", 0.8)
        if not trunk_valid:
            state = "tracking_lost"
        elif events:
            state = events[-1]["action"]
        elif crouch > 0.15:
            state = "crouch"
        for event in events:
            if event["action"] in ("crouch", "dodge_left", "dodge_right"):
                continue
            self.attack_history.append((time_s, event["action"]))
            self.attack_history = self.attack_history[-3:]
            for sequence, label in COMBOS:
                recent = self.attack_history[-len(sequence) :]
                if tuple(action for _, action in recent) == sequence and all(
                    b[0] - a[0] <= 0.95 for a, b in zip(recent, recent[1:], strict=False)
                ):
                    event["combo"] = label
        return events, {
            "state": state,
            "phase": phase,
            "left_speed": round(float(np.linalg.norm(velocity[7])), 3),
            "right_speed": round(float(np.linalg.norm(velocity[10])), 3),
            "defense": defense,
            "heading_deg": round(float(np.rad2deg(yaw)), 1),
            "angular_speed_dps": round(float(np.rad2deg(self.yaw_rate)), 1),
        }
