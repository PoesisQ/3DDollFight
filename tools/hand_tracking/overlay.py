"""Draws the Astra body skeleton onto the colour preview.

The joints arrive with two coordinates: a world position in millimetres and the
pixel position the sensor itself projected them to. Only the pixel position is
used here. Re-deriving it from the world position would need the colour
intrinsics, which the SDK does not expose -- any such reconstruction is a guess,
and a guess is what put the skeleton on the wrong side of the person.

Nothing here feeds tracking, judgement or Unity: an error in this file can make
the preview look wrong and nothing else.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

# Same table as AstraSkeletonView.Bones in Unity, so the preview and the scene
# disagree only when the receiver does.
BONES = (
    (0, 18),
    (18, 1),
    (1, 8),
    (8, 9),
    (1, 2),
    (2, 3),
    (3, 16),
    (16, 4),
    (1, 5),
    (5, 6),
    (6, 17),
    (17, 7),
    (9, 10),
    (10, 11),
    (11, 12),
    (9, 13),
    (13, 14),
    (14, 15),
)

BONE_COLOUR = (0, 165, 255)
JOINT_COLOUR = (255, 255, 0)
# Held joints: still drawn so the arm does not blink, but in a colour that says
# the sensor has lost them. The picture is the diagnostic, so it has to admit
# which parts of it are old.
BONE_HELD_COLOUR = (120, 110, 95)
JOINT_HELD_COLOUR = (170, 165, 150)


class JointTrack:
    """Keeps the last position the sensor was sure of, for a moment.

    An arm resting against the torso is one place the depth image cannot
    separate two surfaces. The tracker then marks the elbow and wrist
    LOW_CONFIDENCE and fills them in from its own model, which lands the arm
    out to the side rather than along the body -- in a T-pose it tracked
    perfectly, which is why the skeleton looked right at first and wrong once
    the person put their arms down.

    Drawing those frames makes the arm flap; dropping them makes it blink.
    Holding the last confident position does neither, as long as the picture
    shows it is being held: those joints are dimmed, and after ``seconds``
    without a confident update they go away entirely.
    """

    def __init__(self, seconds: float = 0.5):
        self.seconds = float(seconds)
        self._points: dict[int, tuple[float, float]] = {}
        self._stamps: dict[int, float] = {}
        self.stale: frozenset[int] = frozenset()

    def update(self, points: Mapping[int, tuple[float, float]], now: float | None = None):
        """Fold in this frame's confident pixels and return what to draw."""
        now = time.perf_counter() if now is None else float(now)
        for kind, point in points.items():
            self._points[kind] = (float(point[0]), float(point[1]))
            self._stamps[kind] = now
        for kind, stamp in list(self._stamps.items()):
            if now - stamp > self.seconds:
                del self._stamps[kind]
                self._points.pop(kind, None)
        self.stale = frozenset(kind for kind in self._points if kind not in points)
        return dict(self._points)

    def reset(self) -> None:
        self._points.clear()
        self._stamps.clear()
        self.stale = frozenset()


def visible(
    screens: Mapping[int, tuple[float, float]], width: int, height: int
) -> dict[int, tuple[float, float]]:
    """Drop joints that fall outside the frame or carry a non-finite pixel."""
    if width <= 0 or height <= 0:
        return {}
    inside: dict[int, tuple[float, float]] = {}
    for kind, point in screens.items():
        try:
            u, v = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        if u != u or v != v:  # NaN: the sensor had no projection for this joint.
            continue
        if 0.0 <= u < width and 0.0 <= v < height:
            inside[kind] = (u, v)
    return inside


def _pixel(point: tuple[float, float]) -> tuple[int, int]:
    return int(round(point[0])), int(round(point[1]))


def draw(
    cv2, frame, screens: Mapping[int, tuple[float, float]], stale: frozenset[int] = frozenset()
) -> int:
    """Draw the skeleton on a BGR frame in place; returns joints that landed.

    ``stale`` names the joints whose pixel is the last confident one rather
    than this frame's: they are drawn dimmer so a held arm is never mistaken
    for a tracked one.
    """
    height, width = frame.shape[:2]
    points = visible(screens, width, height)
    for first, second in BONES:
        if first in points and second in points:
            held = first in stale or second in stale
            cv2.line(
                frame,
                _pixel(points[first]),
                _pixel(points[second]),
                BONE_HELD_COLOUR if held else BONE_COLOUR,
                2,
                cv2.LINE_AA,
            )
    for kind, point in points.items():
        held = kind in stale
        cv2.circle(
            frame,
            _pixel(point),
            2 if held else 3,
            JOINT_HELD_COLOUR if held else JOINT_COLOUR,
            -1,
            cv2.LINE_AA,
        )
    return len(points)
