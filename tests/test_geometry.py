import numpy as np
import pytest

from dollfight.geometry import Intrinsics, backproject, stage_rotation_to_unity, transform_points


def test_optical_axis_depth_and_image_axes():
    points = backproject([[320, 240], [420, 340]], [2, 2], Intrinsics(500, 500, 320, 240))
    np.testing.assert_allclose(points, [[0, 0, 2], [0.4, 0.4, 2]])


@pytest.mark.parametrize("depth", [0, -1, float("nan"), float("inf")])
def test_invalid_depth_cannot_create_a_joint(depth):
    with pytest.raises(ValueError):
        backproject([[320, 240]], [depth], Intrinsics(500, 500, 320, 240))


@pytest.mark.parametrize("fx", [0, -1, float("inf")])
def test_invalid_calibration_is_rejected(fx):
    with pytest.raises(ValueError):
        Intrinsics(fx, 500, 320, 240)


def test_camera_to_upright_stage_rotation_and_translation():
    transform = np.diag([1.0, -1.0, -1.0, 1.0])
    transform[:3, 3] = [0, 1.5, 3]
    np.testing.assert_allclose(transform_points([[0, 0.5, 2]], transform), [[0, 1, 1]])


def test_rigid_extrinsics_reject_silent_reflection():
    with pytest.raises(ValueError):
        transform_points([[0, 0, 2]], np.diag([1, 1, -1, 1]))


def test_unity_rotation_and_position_conversion_commute():
    rotation = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])
    point = np.array([1, 2, 3])
    basis = np.diag([1, 1, -1])
    converted = stage_rotation_to_unity(rotation)
    np.testing.assert_allclose(converted @ (basis @ point), basis @ (rotation @ point))
    np.testing.assert_allclose(np.linalg.det(converted), 1)
