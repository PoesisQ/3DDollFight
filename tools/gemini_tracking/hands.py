"""The existing MediaPipe hand pipeline, fed by Gemini's colour stream.

The heavy lifting (21 landmarks -> 21-joint hand skeleton in the wrist's own
frame, finger curls, palm basis) already exists in ``tools/hand_tracking``.
Rather than fork it, this module imports those files and re-creates the small
amount of per-frame logic in ``hand_tracking/run.py`` that ties them together:
side assignment from the body's wrists, the hold-last-good-pose window, and the
``dollfight-hands-3`` datagram.

If the hand pipeline changes, port the change here too; the shared parts
(``tracker``, ``hand3d``, ``skeleton``, ``curls``, ``protocol``) are imported,
only the loop is duplicated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HAND_DIR = Path(__file__).resolve().parents[1] / "hand_tracking"
if str(HAND_DIR) not in sys.path:
    sys.path.insert(0, str(HAND_DIR))

import curls as curl_module  # noqa: E402
import hand3d  # noqa: E402
import protocol  # noqa: E402
import skeleton  # noqa: E402
from tracker import HandTracker  # noqa: E402

WIRE_TO_UNITY = np.array([1.0, -1.0, -1.0])
HAND_HOLD = 1.5
HAND_GRACE = 1.0


def _screen_x(hand: dict) -> float:
    screen = hand.get("screen")
    if screen is None or len(screen) == 0:
        return 0.5
    return float(np.mean(screen[:, 0]))


def wire_axes(axes) -> list[float]:
    return [float(v) for axis in axes for v in (axis * WIRE_TO_UNITY)]


def palm_facing(hand: dict) -> str:
    """``palm`` / ``back`` / ``edge``: which side of the hand the picture shows.

    The same two-line reading ``hand_tracking/run.py`` prints, kept here so the
    preview can state it out loud. It is the only way to tell a sender that is
    wrong from a rig that is: if this says "back" while you are looking at the
    back of your hand, the sender is right and whatever looks flipped is
    downstream.
    """
    screen = hand.get("screen")
    if screen is None:
        return "?"
    along = screen[skeleton.MIDDLE_MCP] - screen[skeleton.WRIST]
    across = screen[skeleton.PINKY_MCP] - screen[skeleton.INDEX_MCP]
    sign = hand3d.palm_depth_sign(across, along)
    if sign == 0.0:
        return "edge"
    return "palm" if sign * hand3d.PALM_SIDE[hand["side"]] < 0.0 else "back"


def palm_frame(hand: dict):
    points = np.asarray(hand["points"], dtype=np.float64)
    if points.shape != (skeleton.LANDMARK_COUNT, 3):
        return None
    frame = skeleton.hand_basis(points)
    return None if frame is None else frame[:3]


def palm_millimetres(hand: dict) -> float:
    points = np.asarray(hand["points"], dtype=np.float64)
    return float(np.linalg.norm(points[skeleton.MIDDLE_MCP] - points[0])) * 1000.0


def split_shared_sides(detected: list[dict]) -> bool:
    if len(detected) != 2 or detected[0]["side"] != detected[1]["side"]:
        return False
    first, second = sorted(detected, key=_screen_x)
    first["side"], second["side"] = "Right", "Left"
    return True


def assign_sides(detected: list[dict], body) -> bool:
    """Use the body's two wrists to decide which hand is which.

    Astra's +x is the camera's right and image x grows to the right, so the
    wrist nearer the right edge belongs to the hand nearer the right edge.  The
    same rule works on Gemini because its colour image is not mirrored either.
    """
    if len(detected) != 2 or body is None:
        return False
    left = body.screen[16]
    right = body.screen[17]
    if abs(left[0] - right[0]) < 40.0:
        return False
    ordered = sorted(detected, key=_screen_x)
    first, second = ("Right", "Left") if left[0] > right[0] else ("Left", "Right")
    ordered[0]["side"], ordered[1]["side"] = first, second
    return True


class HandRunner:
    """Two hand-sized trackers instead of one full-frame one.

    The full-frame MediaPipe detector has to find a hand that is perhaps 120
    pixels wide inside a 1280x720 picture, and it loses that hand whenever the
    frame rate dips.  Cropping a box around each wrist makes the hand fill most
    of the model's input, so the landmarks are both more accurate and far more
    stable - and because each box belongs to a known side, the left/right label
    no longer depends on MediaPipe's handedness guess flipping between frames.
    """

    def __init__(
        self,
        min_confidence: float = 0.5,
        mirror_sides: bool = True,
        model: Path | None = None,
        use_roi: bool = True,
    ):
        self.min_confidence = min_confidence
        self.use_roi = use_roi
        self.full = HandTracker(model_path=model, mirror_sides=mirror_sides, max_hands=2)
        self.side_trackers = {
            side: HandTracker(model_path=model, mirror_sides=False, max_hands=1)
            for side in ("Left", "Right")
        }
        self.boxes: dict[str, tuple[float, float, float] | None] = {
            "Left": None,
            "Right": None,
        }
        self.misses = {"Left": 0, "Right": 0}
        # A side that keeps failing is simply not in the picture; do not spend
        # an inference on its empty box every frame.
        self.cooldown = {"Left": 0.0, "Right": 0.0}
        self.last_seed = -1.0
        self.lift = hand3d.HandLift()
        self.left_smoother = curl_module.CurlSmoother()
        self.right_smoother = curl_module.CurlSmoother()
        self.held: dict[str, tuple[dict, float]] = {}
        self.missing = {"Left": None, "Right": None}
        self.paired = False
        self.last_detected: list[dict] = []

    def _seed_boxes(self, rgb: np.ndarray, body, now: float) -> None:
        """Re-acquire hands that have no box yet, at most four times a second."""
        height, width = rgb.shape[:2]
        if body is not None:
            for side, joint in (("Left", 16), ("Right", 17)):
                if self.boxes[side] is not None or now < self.cooldown[side]:
                    continue
                u, v = body.screen[joint]
                if 0.0 <= u < width and 0.0 <= v < height:
                    self.boxes[side] = (float(u), float(v), 0.45 * height)
        if all(box is not None for box in self.boxes.values()):
            return
        if now - self.last_seed < 0.25:
            return
        self.last_seed = now
        found = self.full.process(rgb, int(now * 1000))
        if not found:
            return
        # Smallest wrist x is the person's right hand: the colour image is not
        # mirrored, so image left is the person's right.
        found.sort(key=_screen_x)
        sides = ["Right", "Left"] if len(found) == 2 else None
        if sides is None:
            sides = ["Left" if _screen_x(found[0]) > 0.5 else "Right"]
        for hand, side in zip(found, sides, strict=False):
            if self.boxes[side] is not None:
                continue
            screen = hand["screen"]
            if screen is None:
                continue
            centre = np.mean(screen, axis=0) * np.array([width, height])
            self.boxes[side] = (float(centre[0]), float(centre[1]), 0.45 * height)

    def _track_side(self, side: str, rgb: np.ndarray, now: float, anchor=None) -> dict | None:
        height, width = rgb.shape[:2]
        box = self.boxes[side]
        if box is None:
            return None
        cx, cy, size = box
        if anchor is not None:
            # Keep the crop on this side's wrist.  Without the pull, two hands
            # that come close can each drift onto the other and swap.
            ax, ay = anchor
            if 0.0 <= ax < width and 0.0 <= ay < height:
                cx = 0.7 * cx + 0.3 * float(ax)
                cy = 0.7 * cy + 0.3 * float(ay)
                self.boxes[side] = (cx, cy, size)
        size = max(96.0, min(size, 0.9 * min(width, height)))
        x0 = int(round(cx - size / 2))
        y0 = int(round(cy - size / 2))
        found = self.side_trackers[side].process(rgb, int(now * 1000), roi=(x0, y0, int(size)))
        if not found:
            self.misses[side] += 1
            if self.misses[side] >= 3:
                self.boxes[side] = None
                self.misses[side] = 0
                self.cooldown[side] = now + 0.5
            return None
        hand = found[0]
        screen = hand["screen"]
        if screen is None:
            return None
        pixels = screen * np.array([width, height])
        wrist = pixels[0]
        # The crop can only see part of a hand that ran out of it; a wrist far
        # from the box's centre means this is a different hand or a misfire.
        if float(np.linalg.norm(wrist - np.array([cx, cy]))) > size * 0.75:
            return None
        self.misses[side] = 0
        span = float(np.max(pixels.max(axis=0) - pixels.min(axis=0)))
        wanted = max(0.28 * height, min(1.6 * span, 0.75 * height))
        self.boxes[side] = (
            float(wrist[0]),
            float(wrist[1]),
            float(0.7 * size + 0.3 * wanted),
        )
        hand["side"] = side
        return hand

    def process(self, rgb: np.ndarray, body, now: float, delta: float = 1 / 30) -> list[dict]:
        # ``HandLift`` compares the palm's width against its length measured in
        # pixels, so it has to be told the image's aspect.  Its default is 4:3,
        # which was correct on Astra's 640x480 stream; Gemini is 1280x720 and
        # feeding 4:3 makes every palm look a quarter narrower than it is,
        # which is exactly the ratio that decides whether the palm's side is
        # readable at all.
        height, width = rgb.shape[:2]
        aspect = width / max(1, height)
        if abs(self.lift.aspect - aspect) > 1e-3:
            self.lift = hand3d.HandLift(aspect=aspect)
        if self.use_roi:
            self._seed_boxes(rgb, body, now)
            anchors = {}
            if body is not None:
                anchors = {"Left": body.screen[16], "Right": body.screen[17]}
            detected = [
                hand
                for side in ("Left", "Right")
                if (hand := self._track_side(side, rgb, now, anchors.get(side))) is not None
            ]
        else:
            detected = self.full.process(rgb, int(now * 1000))
            if assign_sides(detected, body):
                self.paired = True
            split_shared_sides(detected)
        self.last_detected = detected

        entries: list[dict] = []
        seen: set[str] = set()
        for hand in detected:
            if hand["score"] < self.min_confidence:
                continue
            side = hand["side"]
            solved = self.lift.solve(hand["screen"], side, basis=palm_frame(hand))
            if solved is None:
                continue
            points, _palm_pixels, axes = solved
            palm_mm = palm_millimetres(hand)
            if not skeleton.is_plausible(points, palm_mm):
                continue
            seen.add(side)
            smoother = self.left_smoother if side == "Left" else self.right_smoother
            curls = smoother.apply(curl_module.compute_curls(hand["points"]), max(1e-3, delta))
            gesture = curl_module.classify(curls)
            entry = protocol.hand_entry(
                side, hand["score"], points, palm_mm, curls, gesture, basis=wire_axes(axes)
            )
            entries.append(entry)
            self.held[side] = (entry, now)

        for side, (entry, stamp) in self.held.items():
            if side not in seen and now - stamp <= HAND_HOLD:
                entries.append(entry)
        for side in ("Left", "Right"):
            if side in seen:
                self.missing[side] = None
            elif self.missing[side] is None:
                self.missing[side] = now
            elif now - self.missing[side] > HAND_GRACE:
                (self.left_smoother if side == "Left" else self.right_smoother).reset()
                self.lift.reset(side)
        return entries

    def close(self) -> None:
        self.full.close()
        for tracker in self.side_trackers.values():
            tracker.close()
