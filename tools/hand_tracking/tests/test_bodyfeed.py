"""Tests for the mirrored body feed used to pair hands with wrists."""

from __future__ import annotations

import json
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bodyfeed import BodyFeed  # noqa: E402


def body_packet(
    left_x: float = -230.0,
    right_x: float = 230.0,
    status: int = 2,
    left_status: int = 1,
    right_status: int = 1,
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
                "orientation": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            }
        )
    return json.dumps(
        {
            "version": 1,
            "session": "s",
            "sequence": 3,
            "sourceFrame": 3,
            "timestampMs": 10,
            "simulated": False,
            "units": "mm",
            "bodies": [{"id": 12, "status": status, "joints": joints}],
        }
    ).encode()


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


if __name__ == "__main__":
    unittest.main()
