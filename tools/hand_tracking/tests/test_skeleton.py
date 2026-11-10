"""Tests for the hand-local skeleton frame."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import skeleton  # noqa: E402


def straight_hand(scale: float = 1.0, mirrored: bool = False) -> np.ndarray:
    """Palm facing +z, fingers up +y, thumb toward +x (mirrored -> -x)."""
    hand = np.zeros((21, 3), dtype=np.float64)
    side = -1.0 if mirrored else 1.0
    hand[0] = (0.0, 0.0, 0.0)
    hand[1] = (side * 0.025, 0.02, 0.0)
    hand[2] = (side * 0.045, 0.05, 0.0)
    hand[3] = (side * 0.055, 0.075, 0.0)
    hand[4] = (side * 0.06, 0.09, 0.0)
    bases = {5: 0.03, 9: 0.0, 13: -0.02, 17: -0.035}
    for start, offset in bases.items():
        for joint in range(4):
            hand[start + joint] = (side * offset, 0.08 + joint * 0.025, 0.0)
    return hand * scale


class FrameTests(unittest.TestCase):
    def test_wrist_is_the_origin_and_middle_mcp_is_one_palm_up(self):
        points, palm = skeleton.local_points(straight_hand())
        self.assertAlmostEqual(palm, 0.08, places=6)
        self.assertLess(float(np.linalg.norm(points[0])), 1e-9)
        np.testing.assert_allclose(points[9], (0.0, 1.0, 0.0), atol=1e-6)

    def test_x_axis_points_at_the_little_finger(self):
        points, _ = skeleton.local_points(straight_hand())
        self.assertLess(float(points[5][0]), 0.0)
        self.assertGreater(float(points[17][0]), 0.0)

    def test_coordinates_are_scale_invariant(self):
        small, _ = skeleton.local_points(straight_hand(0.5))
        large, _ = skeleton.local_points(straight_hand(2.0))
        np.testing.assert_allclose(small, large, atol=1e-9)

    def test_basis_is_orthonormal_for_both_hands(self):
        for mirrored in (False, True):
            basis = skeleton.hand_basis(straight_hand(mirrored=mirrored))
            self.assertIsNotNone(basis)
            x, y, z, length = basis
            self.assertAlmostEqual(float(np.dot(x, y)), 0.0, places=9)
            self.assertAlmostEqual(float(np.linalg.norm(z)), 1.0, places=9)
            self.assertAlmostEqual(length, 0.08, places=6)

    def test_local_frame_is_invertible(self):
        hand = straight_hand()
        points, palm = skeleton.local_points(hand)
        basis = skeleton.hand_basis(hand)
        self.assertIsNotNone(basis)
        x, y, z, _ = basis
        rebuilt = hand[0] + (x * points[:, :1] + y * points[:, 1:2] + z * points[:, 2:3]) * palm
        np.testing.assert_allclose(rebuilt, hand, atol=1e-9)

    def test_local_coordinates_ignore_hand_orientation(self):
        hand = straight_hand()
        angle = np.deg2rad(37.0)
        rotation = np.array([
            [np.cos(angle), 0.0, np.sin(angle)],
            [0.0, 1.0, 0.0],
            [-np.sin(angle), 0.0, np.cos(angle)],
        ])
        turned = hand @ rotation.T
        original, _ = skeleton.local_points(hand)
        rotated, _ = skeleton.local_points(turned)
        np.testing.assert_allclose(original, rotated, atol=1e-9)

    def test_degenerate_hand_is_rejected(self):
        flat = np.zeros((21, 3), dtype=np.float64)
        self.assertIsNone(skeleton.local_points(flat))
        collapsed = np.tile(np.array([1.0, 2.0, 3.0]), (21, 1))
        self.assertIsNone(skeleton.local_points(collapsed))

    def test_plausibility_checks_scale_and_spread(self):
        points, palm = skeleton.local_points(straight_hand())
        self.assertTrue(skeleton.is_plausible(points, palm * 1000.0))
        self.assertFalse(skeleton.is_plausible(points, 5.0))
        self.assertFalse(skeleton.is_plausible(points, 400.0))
        broken = points.copy()
        broken[12, 1] = 9.0
        self.assertFalse(skeleton.is_plausible(broken, palm * 1000.0))

    def test_astra_axes_keep_the_frame_right_handed(self):
        # A right-handed MediaPipe basis, built from the documented frame:
        # x right, y down, z into the scene.
        x = np.array([1.0, 0.0, 0.0])
        y = np.array([0.0, 1.0, 0.0])
        z = np.cross(x, y)
        values = skeleton.to_astra_axes([x, y, z])
        ax, ay, az = (np.array(values[i * 3:i * 3 + 3]) for i in range(3))
        # Y is the only axis MediaPipe reports upside down.
        self.assertAlmostEqual(float(ay[1]), -1.0, places=6)
        # The conversion is a rotation, not a reflection: cross still matches,
        # so Unity's palm normal lands on the same side of the hand.
        np.testing.assert_allclose(np.cross(ax, ay), az, atol=1e-9)
        for axis in (ax, ay, az):
            self.assertAlmostEqual(float(np.linalg.norm(axis)), 1.0, places=6)

    def test_astra_axes_reject_the_old_reflection(self):
        # Flipping z but not y makes the frame left-handed. Assert the shape of
        # that mistake so a regression is caught by the cross product above.
        x = np.array([1.0, 0.0, 0.0])
        y = np.array([0.0, 1.0, 0.0])
        z = np.cross(x, y)
        reflected = [np.array([a[0], a[1], -a[2]]) for a in (x, y, z)]
        self.assertLess(float(np.dot(np.cross(reflected[0], reflected[1]), reflected[2])), 0.0)

    def test_astra_axes_keep_palm_down_palm_down(self):
        # End-to-end semantic check. Left hand reaching forward in Astra's
        # frame: fingers along +z, palm down, so the back of the hand is +y.
        x_astra = np.array([-1.0, 0.0, 0.0])   # index knuckle -> little knuckle
        y_astra = np.array([0.0, 0.0, 1.0])    # wrist -> middle knuckle
        z_astra = np.cross(x_astra, y_astra)   # back of the hand
        np.testing.assert_allclose(z_astra, [0.0, 1.0, 0.0], atol=1e-9)

        # How MediaPipe reports that same hand: x right, y down, z forward.
        mediapipe = [np.array([a[0], -a[1], -a[2]]) for a in (x_astra, y_astra, z_astra)]
        values = skeleton.to_astra_axes(mediapipe)
        ax, ay, az = (np.array(values[i * 3:i * 3 + 3]) for i in range(3))
        np.testing.assert_allclose(ax, x_astra, atol=1e-9)
        np.testing.assert_allclose(ay, y_astra, atol=1e-9)
        np.testing.assert_allclose(az, z_astra, atol=1e-9)
        # The avatar rebuilds its palm from az; if that came back as -y the
        # wrist would sit half a turn out and the palm would read upside down.
        self.assertGreater(float(az[1]), 0.5)


if __name__ == "__main__":
    unittest.main()
