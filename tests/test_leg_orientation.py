"""Joint locations alone cannot detect an inside-out skinned thigh."""

import numpy as np
import pytest

from dollfight.kinematics import (
    PARENTS,
    Retargeter,
    leg_ik_hint,
    rest_pose,
    rotation_y,
    two_bone_ik,
)
from dollfight.transitions import fk, quaternion


def rx(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


@pytest.mark.parametrize("yaw", [0, 1.2, 2.8])
@pytest.mark.parametrize("flexion", [0.25, 0.8, 1.5])
def test_forward_knee_bend_preserves_thigh_surface_orientation(yaw, flexion):
    rest = rest_pose()
    local = np.tile([0.0, 0, 0, 1], (19, 1))
    local[0] = quaternion(rotation_y(yaw))
    for hip, knee in ((11, 12), (15, 16)):
        local[hip] = quaternion(rx(-flexion / 2))
        local[knee] = quaternion(rx(flexion))
    source, expected = fk(rest[0], local, rest)
    retarget = Retargeter(rest, foot_lock=False)
    points, _, _ = retarget.process(source, 1 / 30)
    np.testing.assert_allclose(points[11:], source[11:], atol=1e-7)
    for joint in (11, 12, 15, 16):
        # Both the aim and the cross-section axes must match. A 180-degree
        # axial twist passed the old bone-length / joint-origin checks.
        np.testing.assert_allclose(retarget.previous_rotations[joint], expected[joint], atol=1e-7)


def test_straight_bent_straight_cycle_does_not_invert_the_knee():
    rest = rest_pose()
    retarget = Retargeter(rest, foot_lock=False)
    for phase in np.linspace(0, 2 * np.pi, 121):
        bend = 0.5 * (1 - np.cos(phase))
        local = np.tile([0.0, 0, 0, 1], (len(PARENTS), 1))
        for hip, knee in ((11, 12), (15, 16)):
            local[hip] = quaternion(rx(-bend / 2))
            local[knee] = quaternion(rx(bend))
        source, _ = fk(rest[0], local, rest)
        retarget.process(source, 1 / 30)
        for hip in (11, 15):
            assert retarget.previous_rotations[hip][0, 0] > 0.999


def test_shortening_a_rear_step_does_not_reverse_knee_bending():
    hip = np.array([0.0, 0.95, 0])
    knee = np.array([0.0, 0.52, -0.09])
    ankle = np.array([0.0, 0.09, -0.20])
    target = np.array([0.0, 0.09, -0.05])
    hint = leg_ik_hint(hip, knee, ankle, target, np.array([0.0, 0, 1]))
    middle, end = two_bone_ik(
        hip, target, np.linalg.norm(knee - hip), np.linalg.norm(ankle - knee), hint
    )
    axis = end - hip
    radial = middle - hip - axis * ((middle - hip) @ axis) / (axis @ axis)
    assert radial[2] > 0.05


def test_inertial_hyperextension_is_repaired_without_moving_the_foot():
    hip = np.array([0.0, 0.95, 0])
    knee = np.array([0.0, 0.52, -0.10])
    ankle = np.array([0.0, 0.09, 0])
    hint = leg_ik_hint(hip, knee, ankle, ankle, np.array([0.0, 0, 1]))
    middle, end = two_bone_ik(
        hip, ankle, np.linalg.norm(knee - hip), np.linalg.norm(ankle - knee), hint
    )
    np.testing.assert_allclose(end, ankle, atol=1e-8)
    assert middle[2] == pytest.approx(0.10)
