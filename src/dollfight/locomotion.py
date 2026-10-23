"""Calibrated station displacement -> bounded arena displacement (metres)."""

import numpy as np


class MovementMapper:
    def __init__(self, origin, *, side, gain=1.5, initial_gap=2.2, enabled=True, mode="station"):
        self.origin = np.asarray(origin, dtype=float)
        self.side = side
        self.gain = float(np.clip(gain, 0.5, 2.5))
        self.initial_gap = float(np.clip(initial_gap, 1.2, 3.5))
        self.enabled = enabled
        if mode not in ("station", "mocap"):
            raise ValueError("Unknown movement mode")
        self.mode = mode
        self.offset = np.zeros(2)
        self.previous_time = None

    def process(self, points, valid, time_s):
        dt = 1 / 30 if self.previous_time is None else time_s - self.previous_time
        if dt <= 0:
            raise ValueError("Movement timestamps must increase")
        self.previous_time = time_s
        reliable = bool(valid[0] and np.isfinite(points[0]).all())
        measured = (points[0] - self.origin)[[2, 0]]  # station forward / left, never body yaw
        old = self.offset.copy()
        clamped = False
        if reliable and self.enabled:
            if self.mode == "mocap":
                # Already retargeted, filtered root: preserve its scale/timing so
                # planted feet do not slide. Camera station bounds do not apply.
                self.offset = measured.copy()
            else:
                bounded = np.clip(measured, [-0.65, -0.45], [0.65, 0.45])
                clamped = bool(np.any(abs(bounded - measured) > 1e-6))
                desired = np.sign(bounded) * np.maximum(abs(bounded) - 0.025, 0) * self.gain
                delta = (desired - self.offset) * (1 - np.exp(-dt / 0.065))
                length = np.linalg.norm(delta)
                self.offset += delta * min(1, 1.8 * min(dt, 0.1) / max(length, 1e-9))
        speed = (self.offset - old) / dt
        position = np.array(
            [
                -self.side * self.initial_gap / 2 + self.side * self.offset[0],
                0,
                -self.side * self.offset[1],
            ]
        )
        return position, {
            "source_forward_m": round(float(measured[0]), 3) if reliable else None,
            "mapped_forward_m": round(float(self.offset[0]), 3),
            "forward_speed_mps": round(float(speed[0]), 3),
            "lateral_speed_mps": round(float(speed[1]), 3),
            "state": "失跟踪·保持站位"
            if not reliable
            else (
                "前进"
                if speed[0] > 0.08
                else "后退"
                if speed[0] < -0.08
                else "侧移"
                if abs(speed[1]) > 0.08
                else "站稳"
            ),
            "clamped": clamped,
            "mode": self.mode,
        }


def separate_players(positions, minimum=0.55):
    """A 2.5D lane keeps players ordered and prevents walking through each other."""
    result = np.asarray(positions, dtype=float).copy()
    blocked = result[1, 0] - result[0, 0] < minimum
    if blocked:
        center = (result[0, 0] + result[1, 0]) / 2
        result[:, 0] = [center - minimum / 2, center + minimum / 2]
    return result, bool(blocked)
