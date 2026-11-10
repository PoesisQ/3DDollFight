"""World landmarks arrive in one of two Y conventions; this pins which one.

The Tasks API has shipped both. Getting it wrong is not a small error: the hand
frame turns 180 degrees about x, and the avatar's wrist ends up facing backwards
whatever the real palm does - the failure that ``skeleton.to_astra_axes`` was
written to undo once already.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker import image_frame  # noqa: E402

# Three landmarks, spread the way a hand's fingers are, in the two conventions.
Y_UP = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.3]])
SCREEN = np.array([[0.5, 0.5], [0.5, 0.4], [0.5, 0.3]])  # the picture grows down


def test_a_y_up_hand_is_turned_to_y_down():
    converted = image_frame(Y_UP.copy(), SCREEN)
    np.testing.assert_allclose(converted, Y_UP * np.array([1.0, -1.0, -1.0]))


def test_a_y_down_hand_is_left_alone():
    y_down = Y_UP * np.array([1.0, -1.0, -1.0])
    np.testing.assert_allclose(image_frame(y_down.copy(), SCREEN), y_down)


def test_the_flip_is_a_rotation_not_a_mirror():
    converted = image_frame(Y_UP.copy(), SCREEN)
    before = np.cross(Y_UP[1] - Y_UP[0], Y_UP[2] - Y_UP[0])
    after = np.cross(converted[1] - converted[0], converted[2] - converted[0])
    # A rotation moves the cross product with the points; a reflection would
    # turn it inside out, which is what puts the palm normal on the back of the
    # hand.
    np.testing.assert_allclose(after, before * np.array([1.0, -1.0, -1.0]))
    assert np.linalg.det(np.diag([1.0, -1.0, -1.0])) > 0.0


def test_without_a_picture_to_compare_against_nothing_is_touched():
    np.testing.assert_allclose(image_frame(Y_UP.copy(), None), Y_UP)
