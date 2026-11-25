"""Tests for the mirrored body feed used to pair hands with wrists."""

from __future__ import annotations

import json
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bodyfeed import BodyFeed  # noqa: E402


def one_body(body_id: int, wrist_x: float, status: int = 2) -> dict:
    """A body whose wrist sits at ``wrist_x``; used to tell bodies apart."""
    joints = []
    for joint_type in range(19):
        position = {"x": wrist_x if joint_type in (4, 7) else 0.0, "y": 500.0, "z": 2000.0}
        joints.append(
            {
                "type": joint_type,
                "status": 1,
                "position": position,
                "screen": {"ok": True, "x": 300.0 + joint_type, "y": 100.0 + joint_type},
                "orientation": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            }
        )
    return {"id": body_id, "status": status, "joints": joints}


def several_bodies(bodies: list[dict], session: str = "s") -> bytes:
    return json.dumps(
        {
            "version": 1,
            "session": session,
            "sequence": 1,
            "sourceFrame": 1,
            "timestampMs": 10,
            "simulated": False,
            "units": "mm",
            "screen": {"width": 640, "height": 480},
            "bodies": bodies,
        }
    ).encode()


def body_packet(
    left_x: float = -230.0,
    right_x: float = 230.0,
    status: int = 2,
    left_status: int = 1,
    right_status: int = 1,
    screen_ok: bool = True,
    screen_size: tuple[int, int] | None = (640, 480),
    screen_x: float = 300.0,
) -> bytes:
    joints = []
    for joint_type in range(19):
        position = {"x": 0.0, "y": 0.0, "z": 2000.0}
        # The extra wrist joints stay untracked so a test can tell the hand
        # joint apart from its fallback.
        joint_status = 0 if joint_type in (16, 17) else 1
        if joint_type == 4:
            position = {"x": left_x, "y": 500.0, "z": 2000.0}
            joint_status = left_status
        elif joint_type == 7:
            position = {"x": right_x, "y": 500.0, "z": 2000.0}
            joint_status = right_status
        joints.append(
            {
                "type": joint_type,
                "status": joint_status,
                "position": position,
                # Mirrors the bridge: the sensor's own projection, flagged so an
                # untracked joint cannot be mistaken for one sitting at (0, 0).
                "screen": {
                    "ok": bool(screen_ok and joint_status >= 1),
                    "x": screen_x + joint_type,
                    "y": 100.0 + joint_type,
                },
                "orientation": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            }
        )
    packet = {
        "version": 1,
        "session": "s",
        "sequence": 3,
        "sourceFrame": 3,
        "timestampMs": 10,
        "simulated": False,
        "units": "mm",
        "bodies": [{"id": 12, "status": status, "joints": joints}],
    }
    if screen_size is not None:
        packet["screen"] = {"width": screen_size[0], "height": screen_size[1]}
    return json.dumps(packet).encode()


class BodyFeedTests(unittest.TestCase):
    def setUp(self):
        self.feed = BodyFeed(port=0)
        self.sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def tearDown(self):
        self.sender.close()
        self.feed.close()

    def send(self, payload: bytes):
        self.sender.sendto(payload, ("127.0.0.1", self.feed.port))
        return self.feed.poll()

    def test_reads_wrist_positions(self):
        self.assertTrue(self.send(body_packet()))
        self.assertEqual(self.feed.hand("Left")[0], -230.0)
        self.assertEqual(self.feed.hand("Right")[0], 230.0)

    def test_ignores_untracked_bodies(self):
        self.assertTrue(self.send(body_packet(status=1)))
        self.assertIsNone(self.feed.hand("Left"))

    def test_missing_joint_falls_back_to_none(self):
        self.assertTrue(self.send(body_packet(left_status=0)))
        self.assertIsNone(self.feed.hand("Left"))
        self.assertIsNotNone(self.feed.hand("Right"))

    def test_rejects_foreign_datagrams(self):
        self.assertFalse(self.send(b'{"version":2,"bodies":[]}'))
        self.assertFalse(self.send(b"not json"))
        self.assertTrue(self.send(body_packet()))

    def test_joints_returns_only_tracked_ones(self):
        self.assertTrue(self.send(body_packet()))
        joints = self.feed.joints()
        self.assertIsInstance(joints, dict)
        self.assertNotIn(16, joints, "untracked wrists must not be given a position")
        self.assertIn(4, joints)
        self.assertEqual(joints[4][0], -230.0)
        self.assertEqual(len(joints), 17)

    def test_joints_is_empty_without_a_tracked_body(self):
        self.assertTrue(self.send(body_packet(status=1)))
        self.assertEqual(self.feed.joints(), {})

    def test_joints_is_empty_before_any_frame(self):
        self.assertEqual(self.feed.joints(), {})

    def test_screens_returns_the_sensor_projection(self):
        self.assertTrue(self.send(body_packet()))
        screens = self.feed.screens()
        self.assertEqual(screens[4], (304.0, 104.0))
        self.assertEqual(screens[7], (307.0, 107.0))

    def test_screens_skips_joints_the_sensor_did_not_project(self):
        self.assertTrue(self.send(body_packet()))
        self.assertNotIn(16, self.feed.screens(), "untracked wrists have no pixel")

    def test_screens_can_ask_for_the_confident_joints_only(self):
        message = json.loads(several_bodies([one_body(1, 0.0)]))
        joints = message["bodies"][0]["joints"]
        joints[4]["status"] = 2  # left hand: the sensor stands behind this one
        joints[7]["status"] = 1  # right hand: filled in from the model
        self.assertTrue(self.send(json.dumps(message).encode()))
        self.assertIn(4, self.feed.screens(min_status=2))
        self.assertNotIn(7, self.feed.screens(min_status=2))
        self.assertIn(7, self.feed.screens(), "the default keeps low confidence")

    def test_screens_skips_a_tracked_joint_flagged_as_unprojected(self):
        self.assertTrue(self.send(body_packet(screen_ok=False)))
        self.assertEqual(self.feed.screens(), {})

    def test_screens_drops_pixels_outside_the_reported_frame(self):
        self.assertTrue(self.send(body_packet(screen_x=700.0)))
        self.assertEqual(self.feed.screens(), {}, "all joints would land past 640 wide")

    def test_screens_is_empty_without_a_tracked_body(self):
        self.assertTrue(self.send(body_packet(status=1)))
        self.assertEqual(self.feed.screens(), {})

    def test_screen_size_comes_from_the_frame(self):
        self.assertTrue(self.send(body_packet(screen_size=(320, 240))))
        self.assertEqual(self.feed.screen_size(), (320, 240))

    def test_screen_size_falls_back_for_an_older_bridge(self):
        self.assertTrue(self.send(body_packet(screen_size=None)))
        self.assertEqual(self.feed.screen_size(), (640, 480))

    def test_follows_one_body_even_when_the_sdk_lists_another_first(self):
        # Two people in view. The first pick is the lowest id, not the first in
        # the list, so the choice does not depend on SDK ordering.
        self.assertTrue(self.send(several_bodies([one_body(7, -100.0), one_body(3, 400.0)])))
        self.assertEqual(self.feed.body_id, 3)
        self.assertEqual(self.feed.hand("Left")[0], 400.0)

        # Same two people, order swapped: the skeleton must stay on id 3.
        self.assertTrue(self.send(several_bodies([one_body(3, 400.0), one_body(7, -100.0)])))
        self.assertEqual(self.feed.body_id, 3)
        self.assertEqual(self.feed.hand("Left")[0], 400.0)

    def test_switches_only_when_the_followed_body_is_gone(self):
        self.assertTrue(self.send(several_bodies([one_body(3, 400.0)])))
        self.assertEqual(self.feed.body_id, 3)
        self.assertTrue(self.send(several_bodies([one_body(7, -100.0)])))
        self.assertEqual(self.feed.body_id, 7)
        self.assertEqual(self.feed.hand("Left")[0], -100.0)

    def test_a_restarted_bridge_clears_the_pinned_id(self):
        self.assertTrue(self.send(several_bodies([one_body(7, -100.0)], session="one")))
        self.assertEqual(self.feed.body_id, 7)
        # New session, and now a lower id is present: it must be re-picked
        # rather than the stale 7 being kept.
        self.assertTrue(
            self.send(several_bodies([one_body(7, -100.0), one_body(3, 400.0)], session="two"))
        )
        self.assertEqual(self.feed.body_id, 3)

    def test_an_untracked_body_is_never_followed(self):
        bodies = [one_body(2, 50.0, status=1), one_body(9, -80.0)]
        self.assertTrue(self.send(several_bodies(bodies)))
        self.assertEqual(self.feed.body_id, 9)
        self.assertEqual(self.feed.hand("Left")[0], -80.0)

    def test_reports_how_many_people_are_tracked(self):
        bodies = [one_body(3, 0.0), one_body(7, 10.0), one_body(9, 20.0, status=1)]
        self.assertTrue(self.send(several_bodies(bodies)))
        self.assertEqual(self.feed.tracked_count, 2, "status 1 is not a tracked body")


if __name__ == "__main__":
    unittest.main()
