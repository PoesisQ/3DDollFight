"""Tests for the preview window that runs on its own thread."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preview import PreviewWindow  # noqa: E402


class FakeCv2:
    """Stands in for OpenCV: records calls and can block like a dragged window."""

    def __init__(self):
        self.shown = []
        self.keys = []
        self.destroyed = []
        self.draws = []
        self.first_shown = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.show_count = 0

    def imshow(self, name, frame):
        self.shown.append(frame)
        self.show_count += 1
        if self.show_count == 1:
            self.first_shown.set()
            self.release.wait(2)

    def waitKey(self, delay):
        return self.keys.pop(0) if self.keys else -1

    def destroyWindow(self, name):
        self.destroyed.append(name)

    def circle(self, frame, centre, radius, colour, thickness):
        self.draws.append(("circle", centre))


class PreviewWindowTests(unittest.TestCase):
    def make(self, **kwargs):
        cv2 = FakeCv2()
        window = PreviewWindow(cv2, idle=0.001, **kwargs)
        self.addCleanup(window.close)
        return cv2, window

    def test_shows_the_frame_it_is_given(self):
        cv2, window = self.make()
        window.show("frame")
        self.assertTrue(cv2.first_shown.wait(1.0))
        self.assertEqual(cv2.shown[0], "frame")

    def test_a_blocked_window_only_loses_frames_it_could_never_show(self):
        # The window is stuck in imshow, exactly like a window being dragged.
        cv2, window = self.make()
        cv2.release.clear()
        window.show("first")
        self.assertTrue(cv2.first_shown.wait(1.0))

        # The tracker keeps producing while the drag lasts. These must not
        # queue: the newest one replaces whatever waited before it.
        window.show("second")
        window.show("third")
        cv2.release.set()

        deadline = threading.Event()
        for _ in range(200):
            if len(cv2.shown) >= 2:
                break
            deadline.wait(0.01)
        self.assertEqual(cv2.shown[1], "third", "the frame in the middle was skipped")
        self.assertEqual(len(cv2.shown), 2)

    def test_escape_closes_the_window(self):
        cv2, window = self.make()
        cv2.keys.append(27)
        window.show("frame")
        for _ in range(200):
            if window.closed:
                break
            threading.Event().wait(0.01)
        self.assertTrue(window.closed)
        self.assertIn("DollFight camera + body skeleton", cv2.destroyed)

    def test_drawing_calls_go_straight_to_cv2(self):
        cv2, window = self.make()
        window.circle("frame", (1, 2), 3, (0, 255, 0), -1)
        self.assertEqual(cv2.draws, [("circle", (1, 2))])

    def test_close_stops_the_thread(self):
        _cv2, window = self.make()
        window.close()
        self.assertTrue(window.closed)
        self.assertFalse(window._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
