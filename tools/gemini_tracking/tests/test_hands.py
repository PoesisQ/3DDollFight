"""The palm reading the preview prints, pinned to the geometry it claims."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hand_tracking"))

import hands  # noqa: E402
import skeleton  # noqa: E402


def hand(side: str, pinky_right: bool) -> dict:
    """Fingers up, wrist at 0.6, knuckles at 0.4.

    ``pinky_right`` is where the little finger falls in the picture, which is
    the only thing the reading looks at: on a right hand shown palm-first it is
    on the viewer's right, and every other combination is some turn away from
    that.
    """
    screen = np.zeros((skeleton.LANDMARK_COUNT, 2))
    screen[skeleton.WRIST] = (0.50, 0.60)
    screen[skeleton.MIDDLE_MCP] = (0.50, 0.40)
    offset = 0.04 if pinky_right else -0.04
    screen[skeleton.INDEX_MCP] = (0.50 - offset, 0.40)
    screen[skeleton.PINKY_MCP] = (0.50 + offset, 0.40)
    return {"side": side, "screen": screen}


class PalmFacingTests(unittest.TestCase):
    def test_a_right_palm_shown_to_the_camera_reads_as_palm(self) -> None:
        # Right hand, palm to the lens, fingers up: the little finger is on the
        # viewer's right, which is what ``palm_depth_sign`` calls a palm.
        self.assertEqual(hands.palm_facing(hand("Right", True)), "palm")

    def test_the_same_hand_turned_over_reads_as_back(self) -> None:
        # Turning the hand over swaps which side of the wrist the little finger
        # falls on; nothing else about the pose changes.
        self.assertEqual(hands.palm_facing(hand("Right", False)), "back")

    def test_a_left_hand_reads_the_other_way_round(self) -> None:
        # ``PALM_SIDE`` is what makes one number enough for both hands.
        self.assertEqual(hands.palm_facing(hand("Left", False)), "palm")
        self.assertEqual(hands.palm_facing(hand("Left", True)), "back")

    def test_an_edge_on_palm_is_not_guessed(self) -> None:
        screen = np.zeros((skeleton.LANDMARK_COUNT, 2))
        screen[skeleton.WRIST] = (0.5, 0.60)
        screen[skeleton.MIDDLE_MCP] = (0.5, 0.40)
        screen[skeleton.INDEX_MCP] = (0.505, 0.40)
        screen[skeleton.PINKY_MCP] = (0.507, 0.40)
        self.assertEqual(hands.palm_facing({"side": "Right", "screen": screen}), "edge")


if __name__ == "__main__":
    unittest.main()
