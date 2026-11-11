"""Round-trip tests for the 2D hand reconstruction.

The hand is built in a *world* frame - X to the right, Y up, Z towards the
viewer - with its palm normal written down as a literal, then projected with
the same axes MediaPipe uses (x right, y down, z into the scene). Nothing in
this file reads ``hand3d.PALM_SIDE`` to decide which way a palm faces, so a sign
error in that constant cannot slip through by being baked into the fixture as
well. That is exactly how the previous version of these tests passed while every
finger on the avatar curled the wrong way.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hand3d  # noqa: E402
import skeleton  # noqa: E402

# World point -> image components: x stays, y is down, z goes into the scene.
TO_IMAGE = np.array([1.0, -1.0, -1.0])

# The hand is mirrored in depth between "world" here (Z towards the viewer) and
# the frame the landmarks arrive in. Only the 3D tests care: flipping z does not
# move a projection, so every 2D fixture is unaffected. The sign is not a guess -
# building the measured palm frame with TO_IMAGE instead puts the avatar's wrist
# 57 degrees out at a 30 degree turn, and with TO_FRAME it lands within a degree
# of the frame the avatar measures off its own bones.
TO_FRAME = np.array([1.0, -1.0, 1.0])

# Palm landmarks of a right hand, palm towards +Z, fingers up, thumb to the
# viewer's left. Units are palm lengths (wrist -> middle knuckle == 1).
PALM = {
    0: (0.00, 0.00, 0.00),  # wrist
    1: (-0.23, 0.12, 0.03),  # thumb CMC
    5: (-0.33, 0.98, 0.00),  # index MCP
    9: (0.00, 1.00, 0.00),  # middle MCP
    13: (0.20, 0.96, 0.00),  # ring MCP
    17: (0.36, 0.90, 0.00),  # little MCP
}
# The four fingers that lie in the palm plane; the thumb is excluded from the
# geometric assertions because its chord table treats it differently.
FINGERTIPS = (8, 12, 16, 20)
KNUCKLES = (5, 9, 13, 17)


def build_hand(curl: float = 0.0, palm_normal=(0.0, 0.0, 1.0)) -> np.ndarray:
    """A right hand in world coordinates; fingers bend towards ``palm_normal``."""
    points = np.zeros((hand3d.LANDMARK_COUNT, 3))
    for joint, position in PALM.items():
        points[joint] = position
    normal = np.asarray(palm_normal, dtype=float)
    for name, (chain, lengths) in hand3d.FINGERS.items():
        heading = points[chain[0]] - points[0]
        heading = heading / np.linalg.norm(heading)
        cursor = points[chain[0]].copy()
        for segment, length in enumerate(lengths):
            angle = hand3d.FLEXION[name][segment] * curl
            cursor = cursor + length * (math.cos(angle) * heading + math.sin(angle) * normal)
            points[chain[segment + 1]] = cursor
    return points


def rotate_y(points: np.ndarray, yaw: float) -> np.ndarray:
    ry = np.array(
        [[math.cos(yaw), 0.0, math.sin(yaw)], [0.0, 1.0, 0.0], [-math.sin(yaw), 0.0, math.cos(yaw)]]
    )
    return points @ ry.T


def rotate_x(points: np.ndarray, pitch: float) -> np.ndarray:
    rx = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(pitch), -math.sin(pitch)],
            [0.0, math.sin(pitch), math.cos(pitch)],
        ]
    )
    return points @ rx.T


def project_tilted(
    points: np.ndarray, yaw: float = 0.0, pitch: float = 0.0, scale: float = 0.25
) -> np.ndarray:
    """Projection of a hand that is turned and tipped, not just turned."""
    turned = rotate_x(rotate_y(points, yaw), pitch) * TO_IMAGE
    return turned[:, :2] * scale + np.array([0.5, 0.5])


def project(points: np.ndarray, yaw: float = 0.0, scale: float = 0.25) -> np.ndarray:
    """Orthographic projection to MediaPipe-style normalised landmarks."""
    turned = rotate_y(points, yaw) * TO_IMAGE
    return turned[:, :2] * scale + np.array([0.5, 0.5])


def truth_normal(yaw: float, palm_normal=(0.0, 0.0, 1.0)) -> np.ndarray:
    """The palm normal the camera would see, in image components."""
    turned = rotate_y(np.asarray(palm_normal, dtype=float)[None, :], yaw)[0]
    return turned * TO_IMAGE


def solve(points: np.ndarray, yaw: float = 0.0, lift=None, side: str = "Right"):
    lift = lift or hand3d.HandLift(aspect=1.0)
    solved = lift.solve(project(points, yaw=yaw), side)
    assert solved is not None
    return solved


def to_image(local: np.ndarray, axes) -> np.ndarray:
    """Undo the hand frame: local coordinates back to image components."""
    return local @ np.stack(axes)


def look_rotation(forward: np.ndarray, up: np.ndarray) -> np.ndarray:
    """Unity's ``Quaternion.LookRotation`` as a rotation matrix."""
    z = forward / np.linalg.norm(forward)
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    return np.stack((x, np.cross(z, x), z), axis=1)


class PalmSideTests(unittest.TestCase):
    """The palm normal has to point where the physical palm points."""

    def test_right_palm_faces_the_camera(self):
        _, _, axes = solve(build_hand())
        normal = hand3d.PALM_SIDE["Right"] * np.asarray(axes[2])
        self.assertGreater(float(normal @ truth_normal(0.0)), 0.9)

    def test_right_palm_faces_away_after_a_half_turn(self):
        lift = hand3d.HandLift(aspect=1.0)
        for yaw in np.linspace(0.0, math.pi, 25):
            _, _, axes = solve(build_hand(), yaw=float(yaw), lift=lift)
        normal = hand3d.PALM_SIDE["Right"] * np.asarray(axes[2])
        # Palm turned away: the normal has to follow it, not stay on the camera.
        self.assertGreater(float(normal[2]), 0.0)
        self.assertGreater(float(normal @ truth_normal(math.pi)), 0.7)

    def test_each_side_keeps_the_same_anatomy(self):
        left = build_hand() * np.array([-1.0, 1.0, 1.0])
        _, _, axes = solve(left, side="Left")
        normal = hand3d.PALM_SIDE["Left"] * np.asarray(axes[2])
        self.assertGreater(float(normal @ truth_normal(0.0)), 0.9)

    def test_a_fist_does_not_get_to_say_which_side_is_showing(self):
        """The thumbs-up pose: four curled fingers fold the knuckle row.

        These are the numbers from 19.07 s of the 2026-11-11 thumbs-up
        recording, in palm lengths with the wrist at the origin: index knuckle
        at (+0.42, -1.43), pinky knuckle at (-0.06, -0.25), middle knuckle at
        (+0.35, -0.94). The row runs *along* the palm instead of across it and
        is 1.28 palm lengths long, which no rigid hand can do - the wrist is one
        end of the palm and the row is a chord across the other.

        Here the determinant is +0.04; three frames later the same stationary
        hand read -0.00 and then -0.55, and each sign change was a request to
        turn the wrist half a turn at 720 degrees a second. So the picture has
        to say nothing, and the caller has to hold what it had.
        """
        across = np.array([-0.474, 1.186])
        along = np.array([0.345, -0.939])
        self.assertEqual(0.0, hand3d.palm_depth_sign(across, along))
        # And the edge-on case still reads the same way it always did.
        self.assertEqual(0.0, hand3d.palm_depth_sign(np.array([0.05, 0.0]), np.array([0.0, 1.0])))
        # While a plain open palm still gets a sign.
        self.assertNotEqual(0.0, hand3d.palm_depth_sign(np.array([0.6, 0.0]), np.array([0.0, 1.0])))


class HandLiftTests(unittest.TestCase):
    def setUp(self):
        self.hand = build_hand()

    def test_open_hand_round_trips(self):
        local, _, axes = solve(self.hand)
        restored = to_image(local, axes)
        world = self.hand * TO_IMAGE
        # The palm is modelled as flat, so its in-image position has to come back
        # exactly while the few millimetres the real palm is thick do not.
        palm = list(PALM)
        np.testing.assert_allclose(restored[palm, :2], world[palm, :2], atol=1e-6)
        # Fingers come back to within a couple of percent: their rest direction
        # is forced into the palm plane, which the real knuckle offsets are not.
        np.testing.assert_allclose(restored[:, :2], world[:, :2], atol=0.03)
        # The thumb root sits a few millimetres off the palm plane and the
        # reconstruction flattens the palm there, so only the fingers that lie
        # in that plane have to keep their depth.
        fingers = list(range(5, 21))
        np.testing.assert_allclose(restored[fingers, 2], world[fingers, 2], atol=0.06)
        # An open hand is flat: the four fingers that lie in the palm plane must
        # not be lifted off it. The thumb is exempt - its chord is shorter than
        # the table's straight length, so it reads as slightly bent.
        self.assertLess(float(np.max(np.abs(local[list(range(5, 21)), 2]))), 0.02)
        self.assertGreater(float(local[list(FINGERTIPS), 1].mean()), 1.70)

    def test_fist_folds_towards_the_palm(self):
        fist = build_hand(curl=1.0)
        local, _, axes = solve(fist)
        points = to_image(local, axes)
        normal = truth_normal(0.0)
        knuckles = points[list(KNUCKLES)].mean(axis=0)
        tips = points[list(FINGERTIPS)]
        # Fingertips end up in front of the knuckles, on the palm side: that is
        # the whole difference between a fist and a splayed claw.
        offset = (tips - knuckles) @ normal
        self.assertGreater(float(offset.mean()), 0.15)
        self.assertLess(float(offset.mean()), 0.60)
        # And they come back towards the wrist instead of reaching past the
        # knuckles: image y grows downwards, so the tips must sit lower.
        self.assertGreater(float(tips[:, 1].mean()), float(points[list(KNUCKLES), 1].mean()) + 0.15)

    def test_curl_grows_monotonically(self):
        lift = hand3d.HandLift(aspect=1.0)
        heights = []
        for curl in np.linspace(0.0, 1.0, 9):
            local = solve(build_hand(curl=float(curl)), lift=lift)[0]
            heights.append(float(local[list(FINGERTIPS), 1].mean()))
        for before, after in zip(heights, heights[1:], strict=False):
            self.assertLess(after, before + 0.02)

    def test_curl_from_ratio_is_bounded(self):
        for name in hand3d.FINGERS:
            self.assertAlmostEqual(hand3d.curl_from_ratio(name, 1.0), 0.0, places=3)
            self.assertAlmostEqual(hand3d.curl_from_ratio(name, 5.0), 0.0, places=3)
            self.assertAlmostEqual(hand3d.curl_from_ratio(name, 0.0), 1.0, places=3)
            self.assertAlmostEqual(hand3d.curl_from_ratio(name, -1.0), 1.0, places=3)

    def test_palm_turn_does_not_spin_the_frame(self):
        lift = hand3d.HandLift(aspect=1.0)
        previous = None
        for yaw in np.linspace(0.0, 1.2, 12):
            normal = np.asarray(solve(self.hand, yaw=float(yaw), lift=lift)[2][2])
            if previous is not None:
                angle = math.degrees(math.acos(max(-1.0, min(1.0, float(normal @ previous)))))
                # The old world-landmark frame jumped up to 126 degrees here.
                self.assertLess(angle, 30.0)
            previous = normal

    def test_rejects_wrong_shape(self):
        lift = hand3d.HandLift(aspect=1.0)
        self.assertIsNone(lift.solve(np.zeros((3, 2)), "Right"))
        with self.assertRaises(ValueError):
            lift.solve(project(self.hand, 0.0), "Middle")


class CurlTests(unittest.TestCase):
    """How closed the hand is, which is the thing that has to be visible."""

    STRAIGHT = ("Index", "Middle", "Ring", "Little")

    def mean_curl(self, lift, side="Right"):
        curls = lift._curl.get(side, {})
        return float(np.mean([curls.get(name, 0.0) for name in self.STRAIGHT]))

    def test_open_and_fist_are_far_apart(self):
        lift = hand3d.HandLift(aspect=1.0)
        for _ in range(4):
            local, _, _ = solve(build_hand(), lift=lift)
        opened = self.mean_curl(lift)
        opened_height = float(local[list(FINGERTIPS), 1].mean())

        for _ in range(8):
            local, _, _ = solve(build_hand(curl=1.0), lift=lift)
        closed = self.mean_curl(lift)
        closed_height = float(local[list(FINGERTIPS), 1].mean())

        self.assertLess(opened, 0.20)
        self.assertGreater(closed, 0.80)
        # And the joints follow: a fist brings the fingertips back towards the
        # wrist instead of leaving them out where the open hand had them.
        self.assertGreater(opened_height - closed_height, 0.60)

    def test_a_collapsed_palm_does_not_poison_the_calibration(self):
        """The bug that made opening the hand change nothing on screen.

        The chord reference used to be a bare running maximum. One detection
        where the palm collapsed to a couple of pixels divided by almost
        nothing, multiplied the reference by about fifteen, and - because it
        decays by 0.07 % per frame - kept it wrong for the rest of the session.
        Every later frame then read as a closed fist. Measured on a real
        recording: 1.8 px, at frame 1233 of 1574.
        """
        lift = hand3d.HandLift(aspect=1.0)
        for _ in range(4):
            solve(build_hand(), lift=lift)
        reference = np.array(lift._pixels["Right"]["chord"], dtype=float)

        collapsed = project(build_hand())
        # The wrist lands almost on top of the middle knuckle while the fingers
        # stay where they are: the palm estimate collapses, the chords do not,
        # and their ratio explodes. Scaling the whole hand down would not do it,
        # because that leaves every ratio unchanged.
        collapsed[0] = collapsed[9] + np.array([0.0005, 0.0])
        lift.solve(collapsed, "Right")

        for _ in range(6):
            local, _, _ = solve(build_hand(), lift=lift)
        self.assertLessEqual(
            float(np.max(lift._pixels["Right"]["chord"] / reference)),
            1.05,
            "a collapsed frame must not raise the chord reference",
        )
        self.assertLess(self.mean_curl(lift), 0.20)
        self.assertLess(float(np.max(np.abs(local[list(FINGERTIPS), 2]))), 0.10)

    def test_thumb_direction_comes_from_the_landmarks(self):
        """A thumbs-up is the thumb leaving the palm, which no curl can encode.

        The thumb's chain used to start along ``wrist -> thumb base``, a fixed
        anatomical direction, so the reconstructed thumb could only ever point
        the way a relaxed hand points it. Now its direction is measured, and a
        thumb held straight up in the palm plane has to come back straight up.
        """
        hand = build_hand()
        base = hand[1].copy()
        heading = np.array([0.0, 1.0, 0.0])  # straight up the palm, not sideways
        cursor = base.copy()
        for segment, length in enumerate(hand3d.FINGERS["Thumb"][1]):
            cursor = cursor + heading * length
            hand[hand3d.FINGERS["Thumb"][0][segment + 1]] = cursor

        local, _, _ = solve(hand)
        thumb = local[4] - local[1]
        self.assertGreater(float(thumb[1]), 0.45)
        self.assertLess(abs(float(thumb[0])), 0.25)

    def test_a_closed_thumb_folds_across_the_palm(self):
        """A fist's thumb lies along the fingers, not out of the back of the hand.

        The reconstruction bent the thumb along the palm normal, the same
        direction the four fingers take. Those hinge about the knuckles and
        leave the palm; the thumb folds over the palm instead, and in a real
        fist it ends up lying along the index finger. Bending it along the
        normal sends the tip half a palm length out of the hand - and costs the
        fit the only cue it had, so the thumb read 0.00 for entire recordings,
        including frames where it is plainly tucked under the fingers.

        Measured here: the closed thumb has to travel across the palm and stay
        near its plane. Along the normal it moved 0.06 across and 0.53 out.
        """
        straight = np.array([-0.5, 0.85, 0.0])
        straight = straight / np.linalg.norm(straight)
        for palm_side in (1.0, -1.0):
            with self.subTest(palm_side=palm_side):
                bend = hand3d.HandLift._thumb_bend(straight, palm_side)
                self.assertIsNotNone(bend)
                cursor = np.zeros(3)
                for segment, length in enumerate(hand3d.FINGERS["Thumb"][1]):
                    angle = hand3d.FLEXION["Thumb"][segment]
                    cursor = cursor + length * (math.cos(angle) * straight + math.sin(angle) * bend)
                self.assertGreater(float(cursor[0]), 0.35, "the thumb has to cross the palm")
                self.assertLess(abs(float(cursor[2])), 0.25, "and stay near its plane")


class CurlAcrossOrientations(unittest.TestCase):
    """A fist has to read as a fist whatever the palm is doing.

    The criterion used to be the finger's projected chord divided by the palm's.
    Both are image lengths, and the palm's is the one that disappears first when
    the hand turns: on the recordings this project runs on the ratio reaches 2.3
    for a held fist - longer than a straight finger can be - so the reading
    saturated at "open" and no threshold on it could have worked. The report was
    "unless my palm is square to the camera it cannot tell my fist from my open
    hand", and this is that case, rotated.
    """

    STRAIGHT = ("Index", "Middle", "Ring", "Little")

    # The motion a hand makes while somebody talks with their hands: turned a
    # little either way, tipped forward, and back. Never spun far enough to point
    # straight down the view axis, where one view carries no information at all.
    YAW = 1.0
    PITCH = 0.4

    def mean_curl(self, lift, side="Right"):
        curls = lift._curl.get(side, {})
        return float(np.mean([curls.get(name, 0.0) for name in self.STRAIGHT]))

    def orbit(self, curl, steps: int = 40):
        """Turn and tip a hand the way a person does, and report what was read.

        The orbit starts face-on because the palm's width has to be measured
        against something: the tilt is read as the palm being narrower than the
        calibration says it should be, and before the calibration has seen the
        palm at its widest there is nothing to compare with. A session starts
        the same way - the user faces the camera to be recognised.

        The steps are small for the same reason: the half turn that a palm can
        hide behind is resolved by continuity, so it can only be resolved while
        the hand is actually moving from frame to frame.
        """
        lift = hand3d.HandLift(aspect=1.0)
        for _ in range(6):
            lift.solve(project_tilted(build_hand(curl=curl)), "Right")
        readings = []
        for step in range(steps + 1):
            phase = 2.0 * math.pi * step / steps
            yaw = self.YAW * math.sin(phase)
            pitch = self.PITCH * (1.0 - math.cos(phase))
            image = project_tilted(build_hand(curl=curl), yaw=yaw, pitch=pitch)
            for _ in range(2):
                if lift.solve(image, "Right") is None:
                    break
            readings.append(
                (round(math.degrees(pitch)), round(math.degrees(yaw)), self.mean_curl(lift))
            )
        return readings

    def test_a_fist_stays_a_fist_when_the_hand_turns(self):
        for pitch, yaw, value in self.orbit(1.0):
            with self.subTest(pitch=pitch, yaw=yaw):
                self.assertGreater(value, 0.5, f"a fist read as open at pitch {pitch}, yaw {yaw}")

    def test_an_open_hand_stays_open_when_the_hand_turns(self):
        for pitch, yaw, value in self.orbit(0.0):
            with self.subTest(pitch=pitch, yaw=yaw):
                self.assertLess(
                    value, 0.25, f"an open hand read as a fist at pitch {pitch}, yaw {yaw}"
                )

    def test_a_foreshortened_palm_cannot_flip_the_verdict(self):
        """The measured failure, reproduced: the palm shrinks, the fingers do not.

        Tipping the hand so the wrist-to-knuckle axis points at the camera
        shrinks the palm's projected length and nothing else - a real recording
        of a held fist measured 22.7 px of palm against 60 px a moment earlier,
        which multiplied every chord by 2.6 and pinned the old reading at zero.
        """
        hand = build_hand(curl=1.0)
        along = hand[hand3d.MIDDLE_MCP] - hand[hand3d.WRIST]
        along = along / np.linalg.norm(along)
        collapsed = hand.copy()
        for joint in (1, 5, 9, 13, 17):
            offset = hand[joint] - hand[hand3d.WRIST]
            depth = float(offset @ along)
            collapsed[joint] = hand[hand3d.WRIST] + offset - 0.55 * depth * along

        lift = hand3d.HandLift(aspect=1.0)
        for _ in range(5):
            lift.solve(project(collapsed), "Right")
        self.assertGreater(
            self.mean_curl(lift), 0.5, "a collapsed palm made the fist read as an open hand"
        )


class MeasuredFrameTests(unittest.TestCase):
    """What it buys to be told the palm's orientation instead of guessing it.

    One view cannot separate "this palm is short" from "this palm is tipped
    towards me"; ``hand3d`` resolves it by comparing the palm's width with the
    width it had when it was last seen square to the camera. MediaPipe's world
    landmarks measure the tip directly, so when they are available they should
    be believed: the tests below hold the contract (the measured frame is used
    as given), the reason (the guess inverts after a tipped calibration), and
    the safety net (a broken frame falls back to the guess).
    """

    @staticmethod
    def pose(hand, pitch, yaw=0.0):
        """The hand as the camera sees it, in hand3d's frame."""
        return rotate_x(rotate_y(hand, yaw), pitch) * TO_FRAME

    def reference(self, hand, pitch, yaw=0.0):
        """The hand's true local points and axes, at that pose."""
        image = self.pose(hand, pitch, yaw)
        basis = skeleton.hand_basis(image)
        local = skeleton.solve(image)
        self.assertIsNotNone(basis)
        self.assertIsNotNone(local)
        return basis[:3], local[0]

    def error(self, screen, truth, basis=None):
        solved = hand3d.HandLift(aspect=1.0).solve(screen, "Right", basis=basis)
        self.assertIsNotNone(solved)
        return float(np.mean(np.linalg.norm(solved[0] - truth, axis=1)))

    def test_a_measured_frame_is_used_as_given(self):
        hand = build_hand()
        basis, _ = self.reference(hand, 0.9)
        _, _, axes = hand3d.HandLift(aspect=1.0).solve(
            project_tilted(hand, pitch=0.9), "Right", basis=basis
        )
        for given, got in zip(basis, axes, strict=True):
            np.testing.assert_allclose(got, given, atol=1e-9)

    def test_a_basis_that_contradicts_the_picture_is_corrected(self):
        """One bad basis frame must not turn the avatar's hand inside out.

        Replayed over eight seconds of this project's own recording, the palm
        frame MediaPipe reports moves 3.7 degrees per frame at the median and
        167 at worst - the normal landing on the far side of the hand. The
        receiver maps that frame straight onto the wrist's world rotation, so
        the hand snapped half a turn round and back on the next frame, which is
        the twitch that made the puppet unreadable while the skeleton preview,
        drawn from the joints, kept looking fine.

        The picture is not ambiguous about it: the same 2D landmarks that
        produced the joints decide which side of the palm is on show, so the
        frame is put back on the right side of the hand on the very frame it
        arrives, instead of being held and hoped over.
        """
        hand = build_hand()
        screen = project_tilted(hand, pitch=0.4)
        basis, truth = self.reference(hand, 0.4)
        lift = hand3d.HandLift(aspect=1.0)
        first = lift.solve(screen, "Right", basis=basis)
        self.assertIsNotNone(first)
        flipped = [basis[0], basis[1], -np.asarray(basis[2], dtype=float)]
        second = lift.solve(screen, "Right", basis=flipped)
        self.assertIsNotNone(second)
        step = float(np.degrees(np.arccos(np.clip(first[2][2] @ second[2][2], -1, 1))))
        self.assertLess(step, 0.5, "a basis that contradicts the picture still turned the hand")
        self.assertLess(float(np.mean(np.linalg.norm(second[0] - truth, axis=1))), 0.05)

    def test_a_fist_holds_the_side_it_was_last_sure_of(self):
        """The one place time gets a vote, and how narrowly it is bounded.

        At 19.07 s of the thumbs-up recording the measured normal flipped 180
        degrees between two frames of a hand that was not moving, while the 2D
        landmarks described a fist rather than a palm (see
        ``test_a_fist_does_not_get_to_say_which_side_is_showing``). Neither
        signal can settle the half turn, so the frame holds the side that was
        last readable.

        This drives ``_settle_basis`` directly because the inputs are the two
        measured vectors off that frame - a synthetic fist cannot produce them,
        since its knuckles stay where the anatomy puts them. The release is
        covered by ``test_a_real_turn_still_gets_through``, which requires the
        frame to be back on the measurement the moment the picture can read it.
        """
        hand = build_hand()
        basis, _ = self.reference(hand, 0.3)
        lift = hand3d.HandLift(aspect=1.0)
        first = lift.solve(project_tilted(hand, pitch=0.3), "Right", basis=basis)
        self.assertIsNotNone(first)
        settled = lift._settle_basis(
            "Right",
            (np.array([-1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, -1.0])),
            np.array([-0.474, 1.186]),
            np.array([0.345, -0.939]),
        )
        self.assertIsNotNone(settled)
        self.assertGreater(
            float(np.asarray(settled[2]) @ np.asarray(first[2][2])),
            0.9,
            "a fist turned the wrist over on the strength of a fold",
        )

    def test_a_palm_turned_over_stays_turned_over(self):
        """The half turn the filter used to swallow, and never gave back.

        Turning a palm over is a half turn: it is the gesture this tracking
        exists to show, and at the pace people do it it arrives in three or four
        frames. A rule that rejected any step over 35 degrees therefore rejected
        the flip - and, because a rejected frame does not update the reference,
        rejected every frame after it as well. Measured on the recording that
        prompted this: both hands latched 180 degrees out at 9.9 s of a 42 s
        clip and stayed there, which reads as "the palm faces the screen unless
        I turn it over".

        The picture says which side of the hand is showing, so the turn is not a
        guess and must not be filtered. It must also not be undone on the next
        frame, which is what "held" used to mean.
        """
        hand = build_hand()
        lift = hand3d.HandLift(aspect=1.0)
        for pitch in (0.3, 0.9):
            front_screen = project_tilted(hand, pitch=pitch)
            front_basis, _ = self.reference(hand, pitch)
            before = lift.solve(front_screen, "Right", basis=front_basis)
            self.assertIsNotNone(before)
            back_screen = project_tilted(hand, yaw=math.pi, pitch=pitch)
            back_basis, truth = self.reference(hand, pitch=pitch, yaw=math.pi)
            for frame in range(4):
                after = lift.solve(back_screen, "Right", basis=back_basis)
                self.assertIsNotNone(after)
                got = np.asarray(after[2][2], dtype=float)
                want = np.asarray(back_basis[2], dtype=float)
                self.assertGreater(
                    float(got @ want),
                    0.99,
                    f"pitch {pitch}, frame {frame}: the frame did not follow the palm over",
                )
                self.assertNotEqual(
                    np.sign(got[2]),
                    np.sign(before[2][2][2]),
                    f"pitch {pitch}, frame {frame}: still on the near side of the hand",
                )
                # The joints are expressed in that frame, so a frame that turned
                # over has to carry a hand that turned over with it - not a
                # mirrored one whose fingers close towards the back of the hand.
                self.assertLess(
                    float(np.mean(np.linalg.norm(after[0] - truth, axis=1))),
                    0.05,
                    f"pitch {pitch}, frame {frame}: the joints came out mirrored",
                )

    def test_the_picture_cannot_call_a_palm_that_is_edge_on(self):
        """Halfway through a flip the palm is a line, and a line has no side.

        ``palm_depth_sign`` returns zero there so the caller keeps the frame it had
        rather than inventing a half turn from a few pixels of width. Getting it
        wrong would be worse than useless: it would flip the hand at the exact
        moment nobody can tell, and flip it back again on the way out.
        """
        hand = build_hand()
        for yaw in (0.0, 0.4, 1.2):
            screen = project_tilted(hand, yaw=yaw)
            along = screen[hand3d.MIDDLE_MCP] - screen[hand3d.WRIST]
            across = screen[hand3d.PINKY_MCP] - screen[hand3d.INDEX_MCP]
            self.assertNotEqual(0.0, hand3d.palm_depth_sign(across, along), yaw)
        edge = project_tilted(hand, yaw=math.pi / 2)
        along = edge[hand3d.MIDDLE_MCP] - edge[hand3d.WRIST]
        across = edge[hand3d.PINKY_MCP] - edge[hand3d.INDEX_MCP]
        self.assertEqual(0.0, hand3d.palm_depth_sign(across, along))

    def test_a_real_turn_still_gets_through(self):
        """A rolling hand arrives, and never falls behind by more than a step.

        Turning the palm about the finger axis moves the frame further per
        frame than anything else a wrist does. At 25 degrees a frame - 750
        degrees a second at 30 fps, faster than a hand actually rolls - the
        frame has to arrive unfiltered wherever the picture can still read the
        palm, or the avatar's wrist would trail the real one by a visible
        margin.

        Around edge-on it cannot read it: at 86 degrees of yaw the knuckle row
        projects 0.14 palm lengths and the palm is its own mirror image, so the
        side that was last readable is held for that step instead of guessed.
        What must not happen is the error compounding - the old
        reject-past-35-degrees filter measured every frame against a reference
        it never updated, so once it fell behind it stayed behind. This is
        measured against the truth on every frame, so the hold has to stay one
        step.
        """
        hand = build_hand()
        lift = hand3d.HandLift(aspect=1.0)
        for step_index in range(1, 9):
            yaw = math.radians(25.0) * step_index
            basis, _ = self.reference(hand, 0.3, yaw)
            screen = project_tilted(hand, yaw=yaw, pitch=0.3)
            solved = lift.solve(screen, "Right", basis=basis)
            self.assertIsNotNone(solved)
            got = np.asarray(solved[2][2], dtype=float)
            want = np.asarray(basis[2], dtype=float)
            angle = float(np.degrees(np.arccos(np.clip(got @ want, -1, 1))))
            q = np.asarray(screen, dtype=float)
            q = q - q[0]
            u = q / float(np.linalg.norm(q[hand3d.MIDDLE_MCP]))
            readable = hand3d.palm_depth_sign(
                u[hand3d.PINKY_MCP] - u[hand3d.INDEX_MCP], u[hand3d.MIDDLE_MCP]
            )
            tolerance = 2.0 if readable else 27.0
            self.assertLess(
                angle,
                tolerance,
                f"z axis {angle:.1f} deg behind at yaw {yaw:.2f} (readable={bool(readable)})",
            )
        # Ending past 180 degrees, the palm has turned over and the picture can
        # read it again: the hold must have released, not become a lag.
        self.assertLess(angle, 2.0)

    def test_the_guess_can_be_a_hundred_degrees_out(self):
        """How far the inferred palm axis goes, and what fixes it.

        Sweeping a hand that starts square to the camera through the poses a
        person actually holds it in, the inferred long axis ends up 137 degrees
        from where the landmarks say it is - the worst case, at a palm tipped
        69 degrees and turned 23. That frame is not a rounding error, it is the
        hand pointing the other way, and it is what "the skeleton goes to pieces
        in front of my chest" was.

        The measured frame does not degrade anywhere in that sweep: it *is* the
        truth, so the reconstruction has nothing left to infer.
        """
        hand = build_hand(curl=0.5)
        lift = hand3d.HandLift(aspect=1.0)
        for _ in range(6):
            lift.solve(project_tilted(hand, pitch=0.0), "Right")
        worst, at = 0.0, None
        for pitch in np.linspace(-0.3, 1.2, 11):
            for yaw in np.linspace(-0.8, 0.8, 5):
                screen = project_tilted(hand, pitch=float(pitch), yaw=float(yaw))
                basis, _ = self.reference(hand, float(pitch), float(yaw))
                guessed = lift.solve(screen, "Right")
                self.assertIsNotNone(guessed)
                angle = math.degrees(math.acos(float(np.clip(guessed[2][1] @ basis[1], -1.0, 1.0))))
                if angle > worst:
                    worst, at = angle, (float(pitch), float(yaw))
        self.assertGreater(
            worst,
            60.0,
            f"the guess stayed within {worst:.0f} degrees; "
            "the fixture may no longer reach the poses this is about",
        )
        measured = hand3d.HandLift(aspect=1.0).solve(
            project_tilted(hand, pitch=at[0], yaw=at[1]),
            "Right",
            basis=self.reference(hand, at[0], at[1])[0],
        )
        np.testing.assert_allclose(
            measured[2][1], self.reference(hand, at[0], at[1])[0][1], atol=1e-9
        )

    def test_a_degenerate_frame_falls_back_to_the_guess(self):
        hand = build_hand()
        _, truth = self.reference(hand, 0.0)
        bad = np.array([[np.nan, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        screen = project_tilted(hand)
        self.assertAlmostEqual(self.error(screen, truth, bad), self.error(screen, truth), places=12)


class WireFrameTests(unittest.TestCase):
    """The sender and the receiver have to agree on which way the hand points.

    This is the contract that broke once already: the joints arrive in the right
    shape either way, so nothing looks obviously wrong in the stream, but a
    frame that is off by a half turn makes the avatar hold its hand back to
    front no matter what the real palm does.
    """

    M_IMAGE = np.array([1.0, -1.0, -1.0])  # y down, z into the scene
    M_UNITY = np.array([1.0, 1.0, -1.0])  # y up,   z into the scene

    def test_a_measured_frame_also_matches_the_avatar(self):
        """The world-landmark path lands on the same axes as the guess does.

        This is the check that a sign error cannot sneak past: the hand frame is
        orthonormal and plausible whichever way round it is built, so only a
        comparison against a physical hand tells them apart. A tipped, turned
        hand is used because that is where the two paths disagreed by up to 137
        degrees before the measured frame existed.
        """
        import run  # noqa: PLC0415 - the module pulls in the tracker stack

        for side in ("Right", "Left"):
            for pitch in (0.0, 0.7, 1.1):
                # Yaw 0.5 looks at the palm, yaw pi at the back of the same
                # hand: the half turn the avatar got wrong while every joint in
                # it stayed in the right place.
                for yaw in (0.5, math.pi):
                    physical = rotate_x(rotate_y(build_hand(curl=0.4), yaw), pitch)
                    if side == "Left":
                        physical = physical * np.array([-1.0, 1.0, 1.0])
                    image = physical * self.M_IMAGE
                    basis = skeleton.hand_basis(physical * TO_FRAME)
                    self.assertIsNotNone(basis)
                    solved = hand3d.HandLift(aspect=1.0).solve(image[:, :2], side, basis=basis[:3])
                    self.assertIsNotNone(solved)
                    flat = np.asarray(run.wire_axes(solved[2])).reshape(3, 3)
                    sent = look_rotation(flat[2], flat[1])
                    across = (physical[17] - physical[5]) * self.M_UNITY
                    along = (physical[9] - physical[0]) * self.M_UNITY
                    y = along / np.linalg.norm(along)
                    x = across - y * float(across @ y)
                    x /= np.linalg.norm(x)
                    avatar = look_rotation(np.cross(x, y), y)
                    error = np.degrees(
                        np.arccos(np.clip((np.trace(sent @ avatar.T) - 1.0) / 2.0, -1.0, 1.0))
                    )
                    self.assertLess(
                        float(error),
                        1.0,
                        f"{side} pitch {round(math.degrees(pitch))} yaw {round(math.degrees(yaw))}",
                    )

    def test_sender_frame_matches_the_avatar(self):
        import run  # noqa: PLC0415 - the module pulls in the tracker stack

        for side in ("Right", "Left"):
            for curl in (0.0, 0.6, 1.0):
                physical = build_hand(curl=curl)
                if side == "Left":
                    physical = physical * np.array([-1.0, 1.0, 1.0])
                lift = hand3d.HandLift(aspect=1.0)
                solved = lift.solve((physical * self.M_IMAGE)[:, :2], side)
                self.assertIsNotNone(solved)
                flat = np.asarray(run.wire_axes(solved[2])).reshape(3, 3)
                sent = look_rotation(flat[2], flat[1])
                # What BindHandSkeletons measures off the avatar's own bones.
                across = physical[17] - physical[5]
                along = physical[9] - physical[0]
                across, along = across * self.M_UNITY, along * self.M_UNITY
                y = along / np.linalg.norm(along)
                x = across - y * float(across @ y)
                x /= np.linalg.norm(x)
                avatar = look_rotation(np.cross(x, y), y)
                error = np.degrees(
                    np.arccos(np.clip((np.trace(sent @ avatar.T) - 1.0) / 2.0, -1.0, 1.0))
                )
                self.assertLess(float(error), 1.0, f"{side} curl {curl}")


class PointSmoothingTests(unittest.TestCase):
    """The joints themselves, not just the curl, have to stop trembling.

    ``curl`` has been filtered for a while, but the 21 joints that actually
    reach the avatar were rebuilt from the landmarks and sent raw on every
    frame. At the distances this project runs at - a hand is 60 to 90 pixels -
    that is enough noise to make the fingers crawl and the thumb wander while
    the hand is held still.
    """

    NOISE = 0.0025  # normalised image units, about 1.6 px on a 640 px frame

    @staticmethod
    def _sequence(frames, seed, smooth=True):
        rng = np.random.default_rng(seed)
        lift = hand3d.HandLift(aspect=1.0)
        saved = hand3d.POINT_SMOOTHING
        if not smooth:
            hand3d.POINT_SMOOTHING = 0.0
        try:
            steps = []
            previous = None
            for _ in range(frames):
                image = project(build_hand()) + rng.normal(0.0, PointSmoothingTests.NOISE, (21, 2))
                local = lift.solve(image, "Right")[0]
                if previous is not None:
                    steps.append(float(np.abs(local[list(FINGERTIPS)] - previous).mean()))
                previous = local[list(FINGERTIPS)]
            return float(np.mean(steps))
        finally:
            hand3d.POINT_SMOOTHING = saved

    def test_a_held_hand_stops_crawling(self):
        raw = self._sequence(14, seed=7, smooth=False)
        settled = self._sequence(14, seed=7, smooth=True)
        self.assertLess(
            settled, raw * 0.60, f"jitter only dropped from {raw:.4f} to {settled:.4f} palm lengths"
        )

    def test_a_closing_fist_is_not_slowed_down(self):
        # The filter is gated on motion: a hand that closes fast has to come
        # through untouched, otherwise the fix for jitter buys a laggy fist.
        lift = hand3d.HandLift(aspect=1.0)
        open_height = float(
            lift.solve(project(build_hand()), "Right")[0][list(FINGERTIPS), 1].mean()
        )
        heights = []
        for _ in range(4):
            heights.append(
                float(
                    lift.solve(project(build_hand(curl=1.0)), "Right")[0][
                        list(FINGERTIPS), 1
                    ].mean()
                )
            )
        self.assertLess(
            heights[1],
            open_height * 0.75,
            f"two frames after the fist started it was still at {heights[1]:.2f}",
        )


class SideAssignmentTests(unittest.TestCase):
    """Which physical hand a detection is, when MediaPipe gets it wrong.

    The hands are driven by bones named Left and Right, so a wrong label is not
    a cosmetic problem: the receiver writes one wrist twice and leaves the other
    one to fall back to its bind pose.
    """

    def test_two_hands_with_one_label_are_split_by_where_they_are(self):
        """Both hands labelled Right is a tenth of the thumbs-up recording.

        228 of 2123 frames, clustered around the hands-up poses this session
        was about, which is exactly when the body pass loses the wrists and
        ``assign_sides`` has nothing to check against. The camera faces the
        user, so their right hand is the one further left in the picture.
        """
        import run  # noqa: PLC0415 - the module pulls in the tracker stack

        hands = [
            {"side": "Right", "screen": np.tile([0.8, 0.5], (skeleton.LANDMARK_COUNT, 1))},
            {"side": "Right", "screen": np.tile([0.2, 0.5], (skeleton.LANDMARK_COUNT, 1))},
        ]
        self.assertTrue(run.split_shared_sides(hands))
        at_left = min(hands, key=lambda h: float(np.mean(h["screen"][:, 0])))
        at_right = max(hands, key=lambda h: float(np.mean(h["screen"][:, 0])))
        self.assertEqual("Right", at_left["side"])
        self.assertEqual("Left", at_right["side"])

    def test_two_different_labels_are_left_alone(self):
        import run  # noqa: PLC0415

        hands = [
            {"side": "Left", "screen": np.zeros((skeleton.LANDMARK_COUNT, 2))},
            {"side": "Right", "screen": np.ones((skeleton.LANDMARK_COUNT, 2))},
        ]
        self.assertFalse(run.split_shared_sides(hands))
        self.assertEqual(["Left", "Right"], [h["side"] for h in hands])

    def test_one_hand_keeps_its_label(self):
        import run  # noqa: PLC0415

        hands = [{"side": "Right", "screen": np.zeros((skeleton.LANDMARK_COUNT, 2))}]
        self.assertFalse(run.split_shared_sides(hands))
        self.assertEqual("Right", hands[0]["side"])


if __name__ == "__main__":
    unittest.main()
