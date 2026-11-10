"""Unit tests for finger flexion geometry.

Run with:  .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import curls as curl_module  # noqa: E402


def straight_hand() -> np.ndarray:
    """All five chains collinear with the wrist: every joint is extended."""
    points = np.zeros((21, 3), dtype=np.float64)
    for name in curl_module.FINGER_NAMES:
        chain = curl_module.CHAINS[name]
        for step, index in enumerate(chain):
            points[index] = (0.0, -0.01 * step, 0.0)
    return points


class FlexionTests(unittest.TestCase):
    def test_straight_hand_has_no_curl(self):
        result = curl_module.compute_curls(straight_hand())
        self.assertEqual(result.shape, (15,))
        self.assertLess(float(result.max()), 1e-3)

    def test_right_angle_is_half_scale_for_180_degree_limit(self):
        chain = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 1.0],
                          [0.0, 2.0, 1.0], [0.0, 3.0, 1.0]])
        degrees = curl_module._flexion_degrees(chain)
        self.assertAlmostEqual(degrees[0], 90.0, places=3)
        self.assertAlmostEqual(degrees[1], 0.0, places=3)

    def test_fully_curled_finger_saturates(self):
        points = straight_hand()
        # Fold the index chain through 90 degrees at MCP, PIP and DIP.
        points[5] = (0.0, -0.08, 0.0)
        points[6] = (0.0, -0.08, 0.03)
        points[7] = (0.0, -0.11, 0.03)
        points[8] = (0.0, -0.11, 0.0)
        result = curl_module.compute_curls(points)
        self.assertGreater(float(result[4]), 0.5)
        self.assertGreater(float(result[5]), 0.5)

    def test_invalid_input_returns_zeros(self):
        self.assertEqual(float(curl_module.compute_curls(np.zeros((3, 3))).max()), 0.0)
        broken = straight_hand()
        broken[0, 0] = math.nan
        self.assertEqual(float(curl_module.compute_curls(broken).max()), 0.0)

    def test_classify_covers_open_and_fist(self):
        self.assertEqual(curl_module.classify(np.zeros(15)), "open")
        self.assertEqual(curl_module.classify(np.ones(15)), "fist")

    def test_smoother_converges_without_overshoot(self):
        smoother = curl_module.CurlSmoother()
        target = np.ones(15, dtype=np.float64)
        value = smoother.apply(np.zeros(15), 1.0 / 30.0)
        for _ in range(200):
            value = smoother.apply(target, 1.0 / 30.0)
        self.assertGreater(float(value.mean()), 0.97)
        self.assertLessEqual(float(value.max()), 1.0)


if __name__ == "__main__":
    unittest.main()
