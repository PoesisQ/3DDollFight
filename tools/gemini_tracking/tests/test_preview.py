"""Tests for the preview overlay: what it draws, and how often.

The 2026-11-13 16:09 recording shows the skeleton blinking on and off at half
the camera rate. Nothing was wrong with the detector: the pose runs on one
frame in ``--pose-every``, and the frames in between were drawn with an empty
list, which is a blank overlay. ``held_for_preview`` is the fix, and it is
tested here because a camera is the one thing a test cannot have.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gemini_run  # noqa: E402
from body_pose import Body  # noqa: E402


def a_body(body_id: int = 1) -> Body:
    joints = np.zeros((19, 3), dtype=np.float64)
    joints[:, 2] = 2000.0
    status = np.ones(19, dtype=np.int32)
    screen = np.zeros((19, 2), dtype=np.float64)
    return Body(body_id=body_id, joints=joints, status=status, screen=screen)


def a_frame(width: int = 320, height: int = 240):
    return types.SimpleNamespace(bgr=np.zeros((height, width, 3), dtype=np.uint8))


class HeldForPreview(unittest.TestCase):
    def test_a_fresh_solve_is_drawn_and_kept(self):
        body = a_body()
        drawn, held, at = gemini_run.held_for_preview([body], [], 0.0, 10.0)
        self.assertEqual(drawn, [body])
        self.assertEqual(held, [body])
        self.assertEqual(at, 10.0)

    def test_a_frame_without_a_solve_reuses_the_last_one(self):
        case = self
        body = a_body()
        _, held, at = gemini_run.held_for_preview([body], [], 0.0, 10.0)
        # The next frame is the one the detector skipped: at 8 fps that is
        # 0.12 s later, well inside the hold.
        drawn, held, at = gemini_run.held_for_preview([], held, at, 10.12)
        case.assertEqual(drawn, [body])
        case.assertEqual(at, 10.0, "the held solve keeps its own timestamp")

    def test_the_hold_expires_when_nobody_is_found_any_more(self):
        body = a_body()
        _, held, at = gemini_run.held_for_preview([body], [], 0.0, 10.0)
        drawn, held, at = gemini_run.held_for_preview(
            [], held, at, 10.0 + gemini_run.PREVIEW_HOLD + 0.01
        )
        self.assertEqual(drawn, [])
        # Keeping it in `held` is harmless - the window is what decides - and
        # it means a detector that comes back does not have to re-prime.
        self.assertEqual(held, [body])

    def test_a_body_that_comes_back_is_drawn_again(self):
        body = a_body()
        _, held, at = gemini_run.held_for_preview([body], [], 0.0, 10.0)
        _, held, at = gemini_run.held_for_preview([], held, at, 12.0)
        fresh = a_body(2)
        drawn, held, at = gemini_run.held_for_preview([fresh], held, at, 12.1)
        self.assertEqual(drawn, [fresh])
        self.assertEqual(at, 12.1)

    def test_a_clock_that_goes_backwards_does_not_resurrect_a_stale_body(self):
        body = a_body()
        _, held, at = gemini_run.held_for_preview([body], [], 0.0, 10.0)
        drawn, _, _ = gemini_run.held_for_preview([], held, at, 9.0)
        self.assertEqual(drawn, [])


class Draw(unittest.TestCase):
    def test_the_skeleton_can_be_turned_off(self):
        body = a_body()
        # Spread the joints out, otherwise every bone is a zero-length line (or
        # is buried under the joint circles) and nothing is drawn either way.
        body.screen[:] = np.array([[40.0 + 12.0 * i, 100.0 + 24.0 * (i % 2)] for i in range(19)])

        painted = gemini_run.draw(a_frame(), [body], None, 8.0, 0.9, None)
        self.assertGreater(
            int(np.count_nonzero(np.all(painted == (0, 220, 0), axis=-1))),
            0,
            "the skeleton should paint bones when it is asked to",
        )

        plain = gemini_run.draw(a_frame(), [body], None, 8.0, 0.9, None, skeleton=False)
        self.assertEqual(
            int(np.count_nonzero(np.all(plain == (0, 220, 0), axis=-1))),
            0,
            "skeleton=False has to keep the picture clean",
        )


if __name__ == "__main__":
    unittest.main()
