"""Causal planted-foot heading stabilization; never steer feet by root velocity.

An ankle position lock alone permits a grounded shoe to swivel. Conversely,
locking the rotation throughout a kick blocks the support-foot pivot. Use toe
height and angular velocity to distinguish a settled sole from heel strike,
toe-off and a pivot. The captured orientation remains authoritative in flight.
"""

import numpy as np

from dollfight.kinematics import rotation_y


def angle_delta(a, b):
    return (a - b + np.pi) % (2 * np.pi) - np.pi


class FootHeadingLock:
    def __init__(self):
        self.previous = None
        self.heading = None
        self.weight = 0.0

    def update(self, ankle, toe, rest_ankle, rest_toe, stationary, dt):
        direction = toe - ankle
        yaw = float(np.arctan2(direction[0], direction[2]))
        speed = np.inf if self.previous is None else abs(angle_delta(yaw, self.previous)) / dt
        self.previous = yaw
        flat = ankle[1] < rest_ankle[1] + 0.045 and toe[1] < rest_toe[1] + 0.035
        planted = stationary and flat and speed < np.deg2rad(50)
        if self.heading is not None and abs(angle_delta(yaw, self.heading)) > np.deg2rad(18):
            planted = False
        if planted and self.heading is None:
            self.heading = yaw
        # Fast pivot/takeoff releases on the current frame: a planted rotation
        # must not fight the recorded knee/hip turn for an extra smoothing window.
        if not flat or speed > np.deg2rad(90):
            self.weight = 0.0
        else:
            self.weight = float(np.clip(self.weight + dt / (0.10 if planted else -0.08), 0, 1))
        if self.weight == 0:
            self.heading = None
        correction = 0 if self.heading is None else angle_delta(self.heading, yaw)
        w = self.weight * self.weight * (3 - 2 * self.weight)
        return rotation_y(correction * w)
