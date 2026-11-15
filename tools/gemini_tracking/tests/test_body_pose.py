"""Tests for the MediaPipe -> Astra joint mapping and the body wire format."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sender  # noqa: E402
from body_pose import BodySolver, calibration_issue  # noqa: E402
from gemini_camera import Frame  # noqa: E402


class Landmark:
    def __init__(self, x: float, y: float, visibility: float = 1.0):
        self.x = x
        self.y = y
        self.visibility = visibility


def standing_pose() -> list[Landmark]:
    """A front-facing person, MediaPipe's landmark order, image y down.

    Their left shoulder (11) sits on the camera's right (x > 0.5) because they
    are facing the lens.
    """
    points = [Landmark(0.5, 0.5) for _ in range(33)]
    points[0] = Landmark(0.50, 0.18)  # nose
    points[7] = Landmark(0.46, 0.18)  # left ear
    points[8] = Landmark(0.54, 0.18)  # right ear
    points[11] = Landmark(0.60, 0.34)  # left shoulder (camera right)
    points[12] = Landmark(0.40, 0.34)  # right shoulder
    points[13] = Landmark(0.68, 0.48)  # left elbow
    points[14] = Landmark(0.32, 0.48)  # right elbow
    points[15] = Landmark(0.72, 0.60)  # left wrist
    points[16] = Landmark(0.28, 0.60)  # right wrist
    points[17] = Landmark(0.74, 0.64)  # left pinky
    points[18] = Landmark(0.26, 0.64)  # right pinky
    points[19] = Landmark(0.73, 0.65)  # left index
    points[20] = Landmark(0.27, 0.65)  # right index
    points[21] = Landmark(0.71, 0.62)  # left thumb
    points[22] = Landmark(0.29, 0.62)  # right thumb
    points[23] = Landmark(0.45, 0.60)  # left hip
    points[24] = Landmark(0.55, 0.60)  # right hip
    points[25] = Landmark(0.44, 0.78)  # left knee
    points[26] = Landmark(0.56, 0.78)  # right knee
    points[27] = Landmark(0.44, 0.93)  # left ankle
    points[28] = Landmark(0.56, 0.93)  # right ankle
    return points


def frame(depth_mm: np.ndarray | None = None) -> Frame:
    height, width = 720, 1280
    depth = np.full((height, width), 2000.0, dtype=np.float32)
    if depth_mm is not None:
        depth = depth_mm
    return Frame(
        bgr=np.zeros((height, width, 3), dtype=np.uint8),
        depth_mm=depth,
        fx=600.0,
        fy=600.0,
        cx=640.0,
        cy=360.0,
        timestamp_ms=0,
        sequence=1,
    )


class BodyMappingTests(unittest.TestCase):
    def test_nineteen_joints_in_astra_convention(self) -> None:
        body = BodySolver(smoothing=0.0).solve(standing_pose(), frame(), 1, 0.0)
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body.joints.shape, (19, 3))
        self.assertEqual(body.status.shape, (19,))
        # z is away from the camera and in millimetres.
        self.assertAlmostEqual(float(body.joints[9][2]), 2000.0, delta=1.0)
        # Astra x is the person's right, so their left shoulder is negative.
        self.assertLess(float(body.joints[2][0]), 0.0)
        self.assertGreater(float(body.joints[5][0]), 0.0)
        # and y is up.
        self.assertGreater(float(body.joints[0][1]), float(body.joints[9][1]))
        self.assertEqual(int(body.status[9]), 1)

    def test_missing_hand_depth_borrows_the_wrist(self) -> None:
        depth = np.full((720, 1280), 2000.0, dtype=np.float32)
        depth[440:480, 900:960] = 0.0  # a hole over the left hand
        depth[400:440, 880:940] = 0.0  # and over the left wrist
        body = BodySolver(smoothing=0.0).solve(standing_pose(), frame(depth), 1, 0.0)
        self.assertIsNotNone(body)
        assert body is not None
        self.assertGreater(float(body.joints[4][2]), 0.0)
        self.assertGreater(float(body.joints[16][2]), 0.0)
        # The borrowed depth has to agree with the body, not collapse to zero.
        self.assertAlmostEqual(float(body.joints[4][2]), 2000.0, delta=1.0)

    def test_no_depth_means_no_body(self) -> None:
        empty = np.zeros((720, 1280), dtype=np.float32)
        self.assertIsNone(BodySolver(smoothing=0.0).solve(standing_pose(), frame(empty), 1, 0.0))

    def test_low_visibility_joint_is_sent_untracked(self) -> None:
        pose = standing_pose()
        pose[15] = Landmark(0.72, 0.60, visibility=0.05)  # left wrist out of view
        body = BodySolver(smoothing=0.0).solve(pose, frame(), 1, 0.0)
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(int(body.status[16]), 0)

    def test_neck_sits_above_the_shoulders(self) -> None:
        # Averaging the shoulders for both joints collapses them onto one
        # point, and the game's calibration then rejects the whole body.
        body = BodySolver(smoothing=0.0).solve(standing_pose(), frame(), 1, 0.0)
        assert body is not None
        neck = body.joints[18]
        shoulder_spine = body.joints[1]
        distance = float(np.linalg.norm(neck - shoulder_spine))
        self.assertGreater(distance, 40.0)
        self.assertGreater(float(neck[1]), float(shoulder_spine[1]))
        # The neck stays on the torso, not somewhere near the head.
        self.assertLess(distance, 150.0)

    def test_spine_joints_are_ordered_hip_to_neck(self) -> None:
        body = BodySolver(smoothing=0.0).solve(standing_pose(), frame(), 1, 0.0)
        assert body is not None
        heights = [float(body.joints[joint][1]) for joint in (9, 8, 1, 18)]
        self.assertEqual(heights, sorted(heights))

    def test_body_passes_the_same_check_as_the_unity_panel(self) -> None:
        body = BodySolver(smoothing=0.0).solve(standing_pose(), frame(), 1, 0.0)
        assert body is not None
        self.assertIsNone(calibration_issue(body))

    def test_a_face_leaning_into_the_lens_is_not_a_body(self) -> None:
        # 0.6 m: the lens sees a head, MediaPipe extrapolates a torso, and the
        # angles are nonsense. Calibrating on that locks the avatar to garbage.
        close = np.full((720, 1280), 600.0, dtype=np.float32)
        self.assertIsNone(BodySolver(smoothing=0.0).solve(standing_pose(), frame(close), 1, 0.0))

    def test_a_collapsed_torso_is_rejected(self) -> None:
        pose = standing_pose()
        for index in (11, 12):  # shoulders down onto the hips
            pose[index] = Landmark(pose[index].x, 0.57)
        self.assertIsNone(BodySolver(smoothing=0.0).solve(pose, frame(), 1, 0.0))


class WireFormatTests(unittest.TestCase):
    def test_body_packet_matches_the_unity_schema(self) -> None:
        body = BodySolver(smoothing=0.0).solve(standing_pose(), frame(), 3, 0.0)
        assert body is not None
        raw = sender.body_packet([body], 7, 11, "session", 12345)
        packet = json.loads(raw)
        self.assertEqual(packet["version"], 1)
        self.assertEqual(packet["units"], "mm")
        self.assertFalse(packet["simulated"])
        self.assertEqual(packet["sequence"], 7)
        self.assertEqual(packet["sourceFrame"], 11)
        self.assertEqual(len(packet["bodies"]), 1)
        joints = packet["bodies"][0]["joints"]
        self.assertEqual(len(joints), 19)
        self.assertEqual([joint["type"] for joint in joints], list(range(19)))
        for joint in joints:
            self.assertEqual(len(joint["orientation"]), 9)
            # Astra: 2 means tracked. Sending 1 makes every joint "low
            # confidence" in the panel and the avatar is never driven.
            self.assertIn(joint["status"], (0, 2))
            for axis in ("x", "y", "z"):
                self.assertIsInstance(joint["position"][axis], float)

    def test_ids_stay_with_the_same_person_when_players_cross(self) -> None:
        left = BodySolver(smoothing=0.0).solve(standing_pose(), frame(), 1, 0.0)
        assert left is not None
        right = BodySolver(smoothing=0.0).solve(standing_pose(), frame(), 2, 0.0)
        assert right is not None
        right.joints[9][0] += 400.0
        previous = {1: left.joints[9].copy(), 2: right.joints[9].copy()}
        # The two bodies swap sides on screen; ids must not swap with them.
        left.joints[9][0], right.joints[9][0] = right.joints[9][0], left.joints[9][0]
        ordered = sender.sort_bodies([right, left], previous)
        self.assertEqual([body.body_id for body in ordered], [1, 2])


if __name__ == "__main__":
    unittest.main()
