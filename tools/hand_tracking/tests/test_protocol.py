"""Tests for the dollfight-hands-3 wire format."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import protocol  # noqa: E402
import skeleton  # noqa: E402
from test_skeleton import straight_hand  # noqa: E402


def entry(side: str = "Left", curls=None):
    points, palm, axes = skeleton.solve(straight_hand())
    return protocol.hand_entry(side, 0.9, points, palm * 1000.0,
                               curls if curls is not None else [0.5] * 15, "open",
                               basis=[value for axis in axes for value in axis])


class ProtocolTests(unittest.TestCase):
    def test_entry_carries_63_joint_coordinates(self):
        hand = entry()
        self.assertEqual(len(hand["joints"]), protocol.COORD_COUNT)
        self.assertEqual(len(hand["curls"]), 15)
        self.assertEqual(len(hand["basis"]), protocol.AXIS_COUNT)
        self.assertAlmostEqual(hand["scaleMm"], 80.0, places=3)

    def test_basis_axes_are_unit_length(self):
        basis = entry()["basis"]
        for axis in range(3):
            length = sum(value * value for value in basis[axis * 3:axis * 3 + 3]) ** 0.5
            self.assertAlmostEqual(length, 1.0, places=3)

    def test_encode_marks_version_three(self):
        message = json.loads(protocol.encode("session", 7, 1234, [entry()]))
        self.assertEqual(message["version"], 3)
        self.assertEqual(message["sequence"], 7)
        self.assertEqual(len(message["hands"]), 1)
        self.assertEqual(len(message["hands"][0]["joints"]), 63)

    def test_coordinates_are_clipped_to_the_local_limit(self):
        points, palm, axes = skeleton.solve(straight_hand())
        points = points.copy()
        points[12] = (9.0, -9.0, 9.0)
        hand = protocol.hand_entry("Right", 0.5, points, palm * 1000.0, [0.0] * 15,
                                   basis=[value for axis in axes for value in axis])
        self.assertEqual(hand["joints"][36:39],
                         [skeleton.LOCAL_LIMIT, -skeleton.LOCAL_LIMIT, skeleton.LOCAL_LIMIT])

    def test_curls_are_clamped_and_finite(self):
        hand = entry("Right", [-1.0, 2.0, float("nan")] + [0.0] * 12)
        self.assertEqual(hand["confidence"], 0.9)
        self.assertEqual(hand["curls"][0], 0.0)
        self.assertEqual(hand["curls"][1], 1.0)
        self.assertEqual(hand["curls"][2], 0.0)

    def test_rejects_bad_side_and_shape(self):
        with self.assertRaises(ValueError):
            entry("Middle")
        points, palm, axes = skeleton.solve(straight_hand())
        basis = [value for axis in axes for value in axis]
        with self.assertRaises(ValueError):
            protocol.hand_entry("Left", 0.5, points[:20], palm * 1000.0, [0.0] * 15, basis=basis)
        with self.assertRaises(ValueError):
            protocol.hand_entry("Left", 0.5, points, palm * 1000.0, [0.0] * 14, basis=basis)
        with self.assertRaises(ValueError):
            protocol.hand_entry("Left", 0.5, points, palm * 1000.0, [0.0] * 15, basis=basis[:8])
        with self.assertRaises(ValueError):
            protocol.hand_entry("Left", 0.5, points, palm * 1000.0, [0.0] * 15,
                                basis=[0.0, 0.0, 0.0] + basis[3:])


if __name__ == "__main__":
    unittest.main()
