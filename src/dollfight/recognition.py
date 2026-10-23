"""Causal movement events with confidence gates, hysteresis and recovery.

No clip names, frame labels or expected action schedules enter this module.
"""

import numpy as np

from dollfight.kinematics import body_basis, unit

LABELS = {
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

        trunk_valid = bool(np.all(valid[[0, 2, 5, 8]]))
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
            if not trunk_valid or not np.all(valid[[hip, knee, ankle]]):
                phase[channel] = "unreliable"
                self.armed[channel] = False
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
                foot_forward > 0.56
                and angle > np.deg2rad(125)
                and velocity[ankle, 2] / scale > 0.25
            ):
                action = side + "_kick"
            elif (
                knee_lift > 0.32
                and foot_forward < 0.35
                and angle < np.deg2rad(110)
                and velocity[knee, 1] / scale > 0.2
            ):
                action = side + "_knee"
            elif knee_lift > 0.12:
                phase[channel] = "preparation"
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
        return events, {
            "state": state,
            "phase": phase,
            "left_speed": round(float(np.linalg.norm(velocity[7])), 3),
            "right_speed": round(float(np.linalg.norm(velocity[10])), 3),
        }
