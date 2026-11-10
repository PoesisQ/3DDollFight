"""Turns 21 MediaPipe landmarks into a hand skeleton rooted at the wrist.

The body skeleton already supplies the wrist pose, so only the hand *inside*
its own frame is needed. That avoids camera-to-depth extrinsics entirely: the
same local points are rebuilt on the avatar's hand bone, which is exactly the
end of the tracked arm.

Frame definition, identical for both hands and both the real hand and the rig:

    origin = wrist landmark 0
    x      = index MCP -> pinky MCP   (across the palm, toward the little finger)
    y      = wrist -> middle MCP      (along the palm, toward the fingers)
    z      = x cross y

Every point is then expressed as ``(dot(d, x), dot(d, y), dot(d, z)) / |y|``,
so coordinates are unitless and one palm length long. Because x and y are taken
from the same anatomical landmarks on both sides, the left hand's mirrored
geometry stays mirrored in the same way the avatar's left hand is mirrored, and
finger curl directions come out correct without a per-side sign fudge.
"""

from __future__ import annotations

import numpy as np

LANDMARK_COUNT = 21
WRIST = 0
INDEX_MCP = 5
MIDDLE_MCP = 9
PINKY_MCP = 17

# MediaPipe landmark chain per finger: wrist anchor, MCP, PIP, DIP, TIP.
CHAINS = {
    "Thumb": (0, 1, 2, 3, 4),
    "Index": (0, 5, 6, 7, 8),
    "Middle": (0, 9, 10, 11, 12),
    "Ring": (0, 13, 14, 15, 16),
    "Little": (0, 17, 18, 19, 20),
}

# The middle fingertip sits about two palm lengths from the wrist, so the cap
# has to clear that; anything past it is estimation noise or a degenerate fit,
# and letting it through would flip fingers.
LOCAL_LIMIT = 2.2


def _unit(vector: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(vector))
    if not np.isfinite(length) or length < 1e-9:
        return None
    return vector / length


def hand_basis(points) -> tuple[np.ndarray, np.ndarray, np.ndarray, float] | None:
    """Return ``(x, y, z, palm_length)`` or ``None`` for a degenerate hand."""
    hand = np.asarray(points, dtype=np.float64)
    if hand.shape != (LANDMARK_COUNT, 3) or not np.all(np.isfinite(hand)):
        return None
    forward = hand[MIDDLE_MCP] - hand[WRIST]
    palm_length = float(np.linalg.norm(forward))
    y = _unit(forward)
    if y is None:
        return None
    across = hand[PINKY_MCP] - hand[INDEX_MCP]
    across = across - y * float(np.dot(across, y))
    x = _unit(across)
    if x is None:
        return None
    z = np.cross(x, y)
    return x, y, z, palm_length


def solve(points) -> tuple[np.ndarray, float, tuple[np.ndarray, np.ndarray, np.ndarray]] | None:
    """Local points, palm length and the hand's own axes, in one pass.

    The axes are the same frame the local points are expressed in, but kept in
    the caller's (camera) coordinates. The receiver needs them to work out how
    far the palm is rolled around the wrist, which landmark offsets alone
    cannot say.
    """
    hand = np.asarray(points, dtype=np.float64)
    basis = hand_basis(hand)
    if basis is None:
        return None
    x, y, z, palm_length = basis
    offsets = hand - hand[WRIST]
    local = np.stack(
        (offsets @ x, offsets @ y, offsets @ z),
        axis=1,
    ) / palm_length
    return np.clip(local, -LOCAL_LIMIT, LOCAL_LIMIT), palm_length, (x, y, z)


def local_points(points) -> tuple[np.ndarray, float] | None:
    """Express 21 landmarks in the hand frame, normalised by palm length."""
    solved = solve(points)
    return None if solved is None else (solved[0], solved[1])


def to_astra_axes(axes) -> list[float]:
    """Hand axes converted from MediaPipe's frame to Astra's.

    MediaPipe's world landmarks follow the *image* frame: X right, Y **down**,
    Z into the scene. Astra is X right, Y up, Z into the scene. The map
    ``(x, -y, -z)`` is a proper rotation (determinant +1), so the frame stays
    right-handed and ``cross(x, y) == z`` keeps holding after the conversion.

    Flipping Z but not Y - the earlier version - is a reflection: the axes stop
    being right-handed, so the reconstructed palm normal lands on the back of
    the hand instead of the palm, and the avatar's wrist ends up turned half a
    turn around the forearm. It reads as "cannot tell palm up from palm down".

    Lives here rather than in ``run.py`` so the conversion can be asserted
    without MediaPipe, a camera or the bridge.
    """
    values: list[float] = []
    for axis in axes:
        values += [float(axis[0]), -float(axis[1]), -float(axis[2])]
    return values


def is_plausible(local, palm_length_mm: float) -> bool:
    """Reject frames whose scale or spread cannot belong to a real hand.

    The palm length only has to rule out degenerate input: it comes from the
    world landmarks, which shrink to a third of their true value once the palm
    turns away from the camera, and the joints themselves are rebuilt from the
    2D landmarks these days.
    """
    points = np.asarray(local, dtype=np.float64)
    if points.shape != (LANDMARK_COUNT, 3) or not np.all(np.isfinite(points)):
        return False
    if not 12.0 <= float(palm_length_mm) <= 250.0:
        return False
    if float(np.max(np.abs(points))) > LOCAL_LIMIT + 1e-6:
        return False
    # Wrist is the origin by construction and the middle MCP sits at y == 1.
    return float(np.linalg.norm(points[WRIST])) < 1e-6 and 0.5 < float(points[MIDDLE_MCP][1]) < 1.5
