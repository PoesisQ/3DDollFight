"""Tests for the preview overlay that draws body joints the sensor projected."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import overlay  # noqa: E402


class FakeCv2:
    """Records draw calls so the overlay can be checked without a window."""

    LINE_AA = 16

    def __init__(self):
        self.lines = []
        self.circles = []
        self.line_colours = []
        self.dot_colours = []

    def line(self, frame, first, second, colour, thickness, style):
        self.lines.append((first, second))
        self.line_colours.append(colour)

    def circle(self, frame, centre, radius, colour, thickness, style):
        self.circles.append(centre)
        self.dot_colours.append(colour)


class FakeFrame:
    shape = (480, 640, 3)


class VisibleTests(unittest.TestCase):
    def test_a_point_inside_the_frame_is_kept_as_is(self):
        self.assertEqual(overlay.visible({0: (320.0, 240.0)}, 640, 480), {0: (320.0, 240.0)})

    def test_no_projection_is_invented(self):
        # The sensor's own pixels are the only input: a joint without one is
        # simply not drawn, rather than being projected from somewhere else.
        self.assertEqual(overlay.visible({}, 640, 480), {})

    def test_outside_the_frame_is_dropped(self):
        self.assertEqual(overlay.visible({0: (640.0, 240.0)}, 640, 480), {})
        self.assertEqual(overlay.visible({0: (320.0, 480.0)}, 640, 480), {})
        self.assertEqual(overlay.visible({0: (-1.0, 240.0)}, 640, 480), {})

    def test_edge_pixels_are_kept(self):
        self.assertEqual(overlay.visible({0: (0.0, 0.0)}, 640, 480), {0: (0.0, 0.0)})
        self.assertEqual(overlay.visible({0: (639.5, 479.5)}, 640, 480), {0: (639.5, 479.5)})

    def test_rejects_broken_pixels(self):
        points = overlay.visible({0: (float("nan"), 240.0), 1: ("x", 0.0), 2: (320.0,)}, 640, 480)
        self.assertEqual(points, {})

    def test_rejects_invalid_geometry(self):
        self.assertEqual(overlay.visible({0: (320.0, 240.0)}, 0, 480), {})
        self.assertEqual(overlay.visible({0: (320.0, 240.0)}, 640, 0), {})


class DrawTests(unittest.TestCase):
    def test_draws_one_line_per_visible_bone_and_one_dot_per_joint(self):
        cv2 = FakeCv2()
        screens = {0: (320.0, 60.0), 18: (320.0, 90.0), 1: (320.0, 120.0)}
        drawn = overlay.draw(cv2, FakeFrame(), screens)
        self.assertEqual(drawn, 3)
        self.assertEqual(len(cv2.circles), 3)
        self.assertEqual(len(cv2.lines), 2, "head-neck and neck-shoulderspine")

    def test_a_bone_needs_both_ends(self):
        cv2 = FakeCv2()
        self.assertEqual(overlay.draw(cv2, FakeFrame(), {0: (320.0, 60.0)}), 1)
        self.assertEqual(cv2.lines, [])

    def test_draws_nothing_without_joints(self):
        cv2 = FakeCv2()
        self.assertEqual(overlay.draw(cv2, FakeFrame(), {}), 0)
        self.assertEqual(cv2.lines, [])
        self.assertEqual(cv2.circles, [])

    def test_held_joints_are_drawn_in_another_colour(self):
        cv2 = FakeCv2()
        screens = {0: (320.0, 60.0), 18: (320.0, 90.0)}
        overlay.draw(cv2, FakeFrame(), screens, frozenset({18}))
        self.assertEqual(cv2.line_colours, [overlay.BONE_HELD_COLOUR])
        self.assertEqual(cv2.dot_colours, [overlay.JOINT_COLOUR, overlay.JOINT_HELD_COLOUR])
        self.assertEqual(len(cv2.lines), 1, "a held joint still closes its bone")


class JointTrackTests(unittest.TestCase):
    def test_a_joint_the_sensor_reports_is_live(self):
        track = overlay.JointTrack()
        self.assertEqual(track.update({0: (10.0, 20.0)}, now=1.0), {0: (10.0, 20.0)})
        self.assertEqual(track.stale, frozenset())

    def test_a_lost_joint_stays_where_it_was_last_seen(self):
        # An arm against the torso comes back from the tracker in a pose of its
        # own. Holding the last good pixel is what stops it flying out.
        track = overlay.JointTrack(seconds=0.5)
        track.update({3: (100.0, 200.0)}, now=1.0)
        self.assertEqual(track.update({}, now=1.2), {3: (100.0, 200.0)})
        self.assertEqual(track.stale, frozenset({3}))

    def test_the_hold_expires(self):
        track = overlay.JointTrack(seconds=0.5)
        track.update({3: (100.0, 200.0)}, now=1.0)
        self.assertEqual(track.update({}, now=1.6), {})
        self.assertEqual(track.stale, frozenset())

    def test_a_joint_coming_back_is_live_again(self):
        track = overlay.JointTrack(seconds=0.5)
        track.update({3: (100.0, 200.0)}, now=1.0)
        track.update({}, now=1.2)
        self.assertEqual(track.update({3: (140.0, 210.0)}, now=1.3), {3: (140.0, 210.0)})
        self.assertEqual(track.stale, frozenset())

    def test_only_the_lost_joints_are_marked(self):
        track = overlay.JointTrack(seconds=0.5)
        track.update({3: (100.0, 200.0), 4: (150.0, 260.0)}, now=1.0)
        points = track.update({3: (101.0, 201.0)}, now=1.1)
        self.assertEqual(points[3], (101.0, 201.0))
        self.assertEqual(points[4], (150.0, 260.0))
        self.assertEqual(track.stale, frozenset({4}))

    def test_reset_forgets_the_held_pose(self):
        track = overlay.JointTrack()
        track.update({3: (100.0, 200.0)}, now=1.0)
        track.reset()
        self.assertEqual(track.update({}, now=1.1), {})
        self.assertEqual(track.stale, frozenset())

    def test_the_dot_lands_on_the_pixel_the_sensor_reported(self):
        cv2 = FakeCv2()
        overlay.draw(cv2, FakeFrame(), {0: (123.4, 456.7)})
        self.assertEqual(cv2.circles, [(123, 457)])


if __name__ == "__main__":
    unittest.main()
