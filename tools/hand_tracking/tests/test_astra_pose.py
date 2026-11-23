import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import astra_pose


class PoseAdapterTests(unittest.TestCase):
    def test_extra_landmarks_only_include_visible_in_frame_points_with_depth(self):
        class Point:
            def __init__(self, x, y, visibility):
                self.x, self.y, self.visibility = x, y, visibility

        class Frame:
            width, height = 100, 100
            fx, fy, cx, cy = 100, 100, 50, 50

            def depth_at(self, x, y):
                return 0 if x > 70 else 1000

        points = [
            Point(0.5, 0.5, 0.9),
            Point(0.8, 0.5, 0.9),
            Point(0.5, 0.5, 0.1),
            Point(1.2, 0.5, 0.9),
        ]
        result = astra_pose.additional_pose_points(points, Frame())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], 0)
        self.assertEqual(result[0]["status"], 2)
        self.assertEqual(result[0]["position"]["z"], 1000)

    def test_missing_or_out_of_frame_leg_depth_is_not_reported_tracked(self):
        class Point:
            x, y = 0.5, 0.5

        class Frame:
            width, height = 100, 100

            def depth_at(self, x, y):
                return 0 if x > 70 else 1200

        points = [Point() for _ in range(33)]
        points[26] = Point()
        points[26].x = 1.1
        points[27] = Point()
        points[27].x = 0.8
        body = type("Body", (), {"status": np.ones(19, dtype=int)})()
        astra_pose.require_leg_depth(body, points, Frame())
        self.assertEqual(body.status[11], 1)
        self.assertEqual(body.status[14], 0)
        self.assertEqual(body.status[12], 0)
        self.assertEqual(body.status[15], 1)

    def test_extra_points_preserve_original_body_packet(self):
        class Point:
            x, y, visibility = 0.5, 0.5, 0.9

        class Detector:
            def __init__(self, *args, **kwargs):
                pass

            def detect(self, rgb, stamp):
                return type("Result", (), {"pose_landmarks": [[Point() for _ in range(33)]]})()

            def close(self):
                pass

        class Solver:
            def __init__(self, *args, **kwargs):
                pass

            def solve(self, *args):
                return type(
                    "Body",
                    (),
                    {
                        "body_id": 1,
                        "status": np.ones(19, dtype=int),
                        "joints": np.tile([0.0, 0.0, 1000.0], (19, 1)),
                    },
                )()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(2)
        try:
            with (
                patch.object(astra_pose, "PoseDetector", Detector),
                patch.object(astra_pose, "BodySolver", Solver),
            ):
                tracker = astra_pose.AstraPoseTracker(
                    port=sock.getsockname()[1], model=Path(__file__)
                )
                try:
                    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
                    depth = np.full((8, 8), 1000, dtype=np.uint16)
                    tracker.process(rgb, depth, (8, 8, 4, 4), 1, 50)
                    body = json.loads(sock.recvfrom(65535)[0])["bodies"][0]
                    self.assertEqual(len(body["joints"]), 19)
                    self.assertEqual(len(body["poseLandmarks"]), 33)
                    self.assertTrue(all(p["status"] == 2 for p in body["poseLandmarks"]))
                finally:
                    tracker.close()
        finally:
            sock.close()

    def test_no_person_sends_empty_frame(self):
        class Detector:
            def __init__(self, *args, **kwargs):
                pass

            def detect(self, rgb, stamp):
                return type("Result", (), {"pose_landmarks": []})()

            def close(self):
                pass

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(2)
        try:
            with patch.object(astra_pose, "PoseDetector", Detector):
                tracker = astra_pose.AstraPoseTracker(
                    port=sock.getsockname()[1], model=Path(__file__)
                )
                try:
                    rgb = np.zeros((4, 4, 3), dtype=np.uint8)
                    depth = np.full((4, 4), 1000, dtype=np.int16)
                    self.assertEqual(tracker.process(rgb, depth, (4, 4, 2, 2), 42, 50), [])
                    data = json.loads(sock.recvfrom(65535)[0])
                    self.assertEqual(data["version"], 1)
                    self.assertEqual(data["sourceFrame"], 42)
                    self.assertEqual(data["bodies"], [])
                    with self.assertRaises(RuntimeError):
                        tracker.process(rgb, None, (4, 4, 2, 2), 43, 60)
                    with self.assertRaises(RuntimeError):
                        tracker.process(rgb, depth, (0, 4, 2, 2), 44, 70)
                finally:
                    tracker.close()
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
