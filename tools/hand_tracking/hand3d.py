"""Rebuilds a 3D hand from MediaPipe's 2D landmarks.

MediaPipe's *world* landmarks turned out to be unusable for retargeting.
Measured on a real recording of this project they collapse as soon as the palm
turns away from the camera: the palm length drops from 100 mm to 36 mm and the
palm width from 65 mm to 7 mm, while the 2D landmarks stay pixel accurate.

Everything built on the world landmarks inherits that collapse:

* the palm frame's x axis is the part of ``pinky - index`` perpendicular to
  ``wrist -> middle``, so once the palm is edge-on it is pure noise; the frame
  spun up to 126 degrees between two consecutive frames, which is the
  "skeleton garbles when I turn my palm" symptom;
* the out-of-plane component of a finger disappears, so a fist only moves the
  fingertips inside the palm plane: "the gaps between the fingers close, but it
  never makes a fist".

This module ignores the world landmarks and rebuilds the hand from the 2D
landmarks plus two anatomical facts:

* the palm is flat and rigid, so its two in-image axes and the hand's
  width/length ratio fix its plane, up to the usual two-fold reflection which is
  resolved by continuity;
* a finger is a one degree of freedom chain. Every phalanx has a fixed length
  and hinges about an axis parallel to the knuckles, so the whole finger is
  described by *one* number - how far it has curled - and the flexion profile of
  a real hand says how that number is spread over the three joints.

The second point is what makes a fist possible. Measuring each phalanx
separately and pushing each joint out of the plane by whatever depth restores its
length looks reasonable but is wrong: the errors of the three segments add up
instead of cancelling, and a closed hand comes out as a claw pointing at the
camera. Fitting one curl value and expanding it through a real flexion profile
keeps the chain a chain, so the fingertips arc back into the palm.

The output is expressed in the hand's own frame - ``x = index knuckle ->
little knuckle``, ``y = wrist -> middle knuckle``, ``z = x cross y`` - which is
the same frame ``skeleton.hand_basis`` builds from the landmarks and the same
construction ``HumanoidReplay`` uses on the avatar, so the receiver rebuilds the
points without any extra convention.
"""

from __future__ import annotations

import math

import numpy as np

LANDMARK_COUNT = 21
WRIST = 0
THUMB_CMC = 1
INDEX_MCP = 5
MIDDLE_MCP = 9
RING_MCP = 13
PINKY_MCP = 17

# A palm can only ever look narrower than it is, so the running maximum of the
# observed width and length converges on the hand's true proportions. It decays
# slowly so a hand held differently can re-calibrate instead of pinning them.
DECAY = 0.9993

# How much of the image the palm's two axes have to span before their 2x2
# matrix can be inverted. This is the determinant of the projected axes - the
# palm's footprint - and it is what replaces the old "normal points at the
# camera" test: past this the palm is edge-on and the depth of every landmark
# is unknowable, so the frame is refused instead of invented.
MIN_PALM_FOOTPRINT = 0.18

# Finger chains: base joint followed by the three phalanx lengths, as a
# fraction of the palm length (wrist -> middle knuckle). Anthropometric means.
FINGERS = {
    "Thumb": ((THUMB_CMC, 2, 3, 4), (0.30, 0.26, 0.22)),
    "Index": ((INDEX_MCP, 6, 7, 8), (0.42, 0.26, 0.20)),
    "Middle": ((MIDDLE_MCP, 10, 11, 12), (0.46, 0.28, 0.21)),
    "Ring": ((RING_MCP, 14, 15, 16), (0.43, 0.27, 0.20)),
    "Little": ((PINKY_MCP, 18, 19, 20), (0.34, 0.21, 0.18)),
}

# Cumulative flexion of each phalanx out of the palm plane at a fully closed
# fist, in radians. Metacarpophalangeal joints close to ~90 degrees, proximal
# interphalangeal to ~190 and distal to ~255, which is what wraps the fingertip
# back onto the palm instead of leaving it sticking out into the air.
FLEXION = {
    "Thumb": (0.85, 2.00, 2.85),
    "Index": (1.45, 3.30, 4.45),
    "Middle": (1.45, 3.30, 4.45),
    "Ring": (1.45, 3.30, 4.45),
    "Little": (1.45, 3.30, 4.45),
}

# ``z = x cross y`` with ``x`` towards the little finger and ``y`` towards the
# fingers is not the same anatomical direction on both hands. Worked out from a
# right hand held palm-to-camera with the fingers up - thumb to the viewer's
# left, so ``x = +X``, ``y = up`` - the cross product lands on ``+Z``, i.e. out
# of the palm. Mirror that hand to get a left one and the same construction lands
# on the back of the hand. Multiplying z by this constant gives the palm normal,
# the direction a closing finger bends towards, on both sides.
#
# Getting this sign wrong is silent: the hand still reconstructs, but every
# finger curls away from the palm and the first frame's plane branch is chosen
# mirrored, which locks the whole hand to the wrong side of its own palm.
PALM_SIDE = {"Right": 1.0, "Left": -1.0}

# How much of the previous frame's curl to keep. Enough to stop landmark noise
# twitching the fingers, short enough that a real fist still snaps shut.
CURL_SMOOTHING = 0.55

# The same idea for the 21 joints themselves, which is what actually drives the
# avatar. ``curl`` was already filtered but the joints were sent raw, so the fan
# of the fingers and the thumb's heading twitched at the landmark noise level
# even while the hand was held still - the fingers looked like they were
# crawling rather than flexing.
#
# The filter is one sided: it only engages while the hand is holding still.
# A joint that moves more than POINT_SNAP in one frame is real motion, and gets
# through untouched, so closing a fist costs no extra lag. Values are in palm
# lengths, where landmark noise sits around 0.02-0.05 and a closing finger moves
# 0.3 or more.
POINT_SMOOTHING = 0.65
POINT_SNAP = 0.20

# Bounds for the running calibration of the finger chords.
#
# The chord reading is only a fallback these days - the curl is fitted - but the
# reference still has to be kept in its box, because it is also what a finger
# falls back on when the fit has nothing to work with. It is tracked as a
# running maximum, which is right in principle and catastrophic in practice: one
# frame where the palm estimate collapsed to a few pixels divides by almost
# nothing, the maximum jumps by an order of magnitude, and because it only
# decays by 0.07 % per frame it stays wrong for the rest of the session. The hand
# then reads as a permanent fist - opening it changes nothing on screen.
#
# A chord can never exceed the phalanges it spans, so the reference is clamped
# near the anthropometric sum and can no longer absorb a bad frame.
CHORD_FLOOR = 0.80
CHORD_CEILING = 1.30

# A palm is longer than it is wide. Anything past this is a collapsed estimate,
# not a hand, and the frame is dropped instead of being fed to the calibration.
PALM_ASPECT_MAX = 1.35
# The same, relative to what this hand has already measured: a palm that shrinks
# to a fraction of its own recent size is a detection failure.
PALM_COLLAPSE = 0.30

# Which curl explains the three phalanges the camera saw.
#
# The old reading divided a finger's projected chord by a reference chord and
# called the ratio a curl. Measured on the recordings this project actually
# runs on, that ratio is not a shape at all: the reference is in palm lengths,
# and the palm's projected length is the least stable number in the image. Tilt
# the hand so the wrist-to-knuckle axis points at the camera and the palm
# collapses (60 px -> 23 px measured) while the fingers still project long, so
# every finger reads *longer than a straight finger can be*, the ratio
# saturates, and a fist comes out as an open hand. That is the "it cannot tell
# my fist from my open palm unless my palm is square to the camera" report, and
# it holds for any threshold chosen on that ratio.
#
# So the curl is fitted instead of measured: for each candidate the finger is
# rebuilt and projected, and the projected chain is compared with the observed
# one up to a single scale factor. The scale is free, which is exactly what
# removes the palm's foreshortening from the answer - a uniform shrink or
# stretch of the observed fingers cannot change which candidate fits best.
#
# The cost is the residual of that fit, normalised by the observed chain, so it
# is comparable across frames and finger sizes.
MIN_FIT_SPAN = 0.25  # palm lengths of phalanx that must be visible to fit
FIT_CONTINUITY = 0.12  # pull towards the previous frame, in residual units

# What the fitted curl has to be stretched by to mean "how closed is this hand".
#
# The fit asks which of the table's flexion profiles the picture agrees with,
# but MediaPipe puts its landmarks on the *surface* it can see rather than at the
# joint centres: a knuckle folds and the landmark stays out on the outside of the
# bend, so the chain it reports is always less folded than the hand is. Measured
# on this project's own recordings, a held fist fits 0.45-0.70 and an open hand
# 0.00-0.15, never the 1.00 the table says a fist is. Without the stretch the
# avatar curls its fingers halfway and the fist never closes, which is what "it
# cannot see my fist" looks like on screen even when the numbers are moving.
CURL_FLOOR = 0.25
CURL_CEILING = 0.65

# A thumbs-up is the thumb moving *out of* the palm, not the thumb curling, and
# the direction it takes is measured from the landmarks instead of assumed.
MIN_THUMB_REACH = 0.45

# The thumb does not fold the way the other four do.
#
# The four fingers hinge about the knuckles, so they leave the palm plane: their
# bend direction is the palm normal, and that is what the reconstruction uses.
# The thumb folds *across the palm* instead - watch a fist and the thumb lies
# along the index and middle fingers, inside the palm's own plane - so bending
# it along the palm normal sends it out of the hand and no amount of curl can
# match the picture. The fit then reads "straight" no matter what the hand does:
# on this project's recordings the thumb sat at 0.00 for whole sessions,
# including frames where it is visibly tucked under the fingers.
#
# So the thumb bends along the palm's far side instead, lifted slightly off the
# surface so it passes over the folded fingers rather than through them.
THUMB_LIFT = 0.35

# The thumb chain is short (0.78 palm lengths) and its landmarks are the least
# reliable of the five, so the residual landscape is flat and the continuity
# prior decides the answer whatever the picture says. Weight it far below the
# fingers, where the same prior is doing real work.
THUMB_CONTINUITY = 0.02

# How much of the palm has to survive into the picture before the picture is
# allowed to say which side of the hand faces the camera. This is the ratio the
# rest of the file already measures the palm by - its width against its length
# on screen - so a hand square to the lens is about 0.70 and a hand turned
# edge-on is 0. At 0.15 the palm is 12 degrees off being a line, which is the
# one pose where a palm and its mirror image are the same picture.
PALM_EDGE_ON = 0.15

# The palm frame that goes on the wire has to be a *continuous* function of
# time, because the receiver turns it straight into the avatar's wrist rotation.
#
# MediaPipe's world landmarks are the only direct measurement of how far the
# palm is tipped away from the lens, and they are not quiet: replayed over eight
# seconds of this project's own recording the frame moves 3.7 degrees per frame
# at the median and 9 at the ninetieth percentile. Unity turns the wrist towards
# that target every frame, so noise at that level is a hand that crawls.
#
# Below BASIS_SNAP the motion is the landmark noise floor rather than a wrist,
# and the frame is blended with the previous one. Above it the frame is taken as
# given, so a real turn costs no lag - the same one-sided filter
# ``POINT_SMOOTHING``/``POINT_SNAP`` uses on the joints.
#
# This used to *reject* any step past 35 degrees instead, on the theory that a
# wrist cannot turn that fast. The theory is true and the conclusion was still
# wrong: turning a palm over is a half turn, it is what the tracking exists to
# show, and it arrives in three or four frames. The rejected frame kept the
# previous axes - and because a rejected frame does not update them, every
# later frame was measured against the same stale reference and rejected too.
# One flip and that hand held its old palm orientation until it left the frame.
# Recorded: at 9.9 s of a 42 s clip its owner turned both palms over, both
# hands kept their old orientation for the remaining 32 s, and the pair of them
# read as "the palm faces the screen only while my palm does".
# ``palm_depth_sign`` is what makes rejection unnecessary.
BASIS_SNAP = 10.0
BASIS_SMOOTHING = 0.5

_TABLE_STEPS = 41


def _curl_table(name: str) -> tuple[np.ndarray, np.ndarray]:
    """Map ``curl`` to the chord the finger would project, as a ratio."""
    lengths = np.asarray(FINGERS[name][1], dtype=np.float64)
    angles = np.asarray(FLEXION[name], dtype=np.float64)
    straight = float(lengths.sum())
    rows = []
    for curl in np.linspace(0.0, 1.0, _TABLE_STEPS):
        theta = angles * curl
        columns = np.stack((np.cos(theta), np.sin(theta)), axis=1) * lengths[:, None]
        rows.append(float(np.linalg.norm(columns.sum(axis=0))) / straight)
    return np.linspace(0.0, 1.0, _TABLE_STEPS), np.asarray(rows)


_TABLES = {name: _curl_table(name) for name in FINGERS}


def _unit(vector: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(vector))
    if not np.isfinite(length) or length < 1e-9:
        return None
    return vector / length


def curl_from_ratio(name: str, ratio: float) -> float:
    """Invert the chord table: how curled is a finger whose chord is ``ratio``."""
    grid, chords = _TABLES[name]
    value = min(max(float(ratio), float(chords[-1])), 1.0)
    return float(np.interp(-value, -chords, grid))


def palm_depth_sign(across: np.ndarray, along: np.ndarray) -> float:
    """Which way round the palm is, straight from the picture.

    The palm frame is ``x = pinky - index``, ``y = wrist -> middle``, so
    ``z = x cross y`` is not a matter of opinion: both of those vectors lie in
    the image plane, and the z component of their cross product is just their
    2D determinant. Two subtractions and a multiply, no state, no continuity -
    and it holds on every frame, including the frame a palm turns over on,
    which is the frame continuity cannot call.

    It is also the answer to "which side of the hand am I looking at", which is
    asked every time a palm is flipped towards the camera. ``x`` runs from the
    thumb's side towards the little finger; hold a right hand up, palm to the
    lens, fingers up, and the little finger is on the viewer's right, so the
    determinant comes out negative. Hold the same hand up with its back to the
    lens and the thumb changes sides and the determinant comes out positive. On
    a left hand both signs invert. That is exactly ``PALM_SIDE``, which is why
    ``PALM_SIDE * z`` is the palm normal on both hands, and why one number is
    enough to settle the half turn.

    Returns the sign ``z``'s depth component has to have. ``0.0`` means the
    palm is too close to edge-on for the picture to say - there the knuckle rows
    have merged into one line and the palm is its own mirror image, so a caller
    should keep what it had rather than invent a half turn.
    """
    a = np.asarray(across, dtype=np.float64)[:2]
    b = np.asarray(along, dtype=np.float64)[:2]
    length = float(np.linalg.norm(b))
    if length < 1e-9 or float(np.linalg.norm(a)) / length < PALM_EDGE_ON:
        # Width against length, so the answer does not depend on how big the hand
        # is on screen or on which units the caller measured it in.
        return 0.0
    return 1.0 if float(a[0] * b[1] - a[1] * b[0]) > 0.0 else -1.0


class HandLift:
    """Stateful 2D -> 3D hand reconstruction.

    One instance serves both hands; the per-side state (measured proportions,
    the palm normal and each finger's curl) is keyed by ``"Left"`` / ``"Right"``.
    """

    def __init__(self, aspect: float = 4.0 / 3.0):
        self.aspect = float(aspect) if aspect > 0 else 4.0 / 3.0
        self._pixels: dict[str, dict] = {}
        self._normal: dict[str, np.ndarray] = {}
        self._curl: dict[str, dict[str, float]] = {}
        self._points: dict[str, np.ndarray] = {}
        self._flat: dict[str, np.ndarray] = {}
        self._axes: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def reset(self, side: str | None = None) -> None:
        for name in [side] if side else list(self._normal):
            self._pixels.pop(name, None)
            self._normal.pop(name, None)
            self._curl.pop(name, None)
            self._points.pop(name, None)
            self._flat.pop(name, None)
            self._axes.pop(name, None)

    # ---------------------------------------------------------------- helpers

    def _settle(self, side: str, local: np.ndarray) -> np.ndarray:
        """Low-pass the joints, but only while the hand is holding still.

        The gate compares the largest coordinate change against
        ``POINT_SNAP``: anything above it is the hand moving, and is passed
        through so a fist still closes at full speed.
        """
        previous = self._points.get(side)
        if previous is not None and previous.shape == local.shape:
            step = float(np.max(np.abs(local - previous)))
            if step <= POINT_SNAP:
                local = POINT_SMOOTHING * previous + (1.0 - POINT_SMOOTHING) * local
        self._points[side] = local
        return local

    def _calibrate(
        self, side: str, palm_px: float, width_px: float, chords: np.ndarray, trusted: bool
    ):
        """Track this hand's proportions so the readings are self-referential.

        The palm and its width are tracked as running maxima because a rigid
        object can only ever project smaller than it is, and each axis is
        largest when it faces the camera square on.

        The finger chord reference is tracked the same way but clamped to a
        narrow band around the anthropometric sum. Without the clamp a single
        collapsed frame sets the reference an order of magnitude too high and
        every later frame reads as a closed fist; with it, the worst a bad frame
        can do is saturate this one frame's reading.

        ``trusted`` is false when the frame's proportions are not those of a
        hand. The frame is still reconstructed - the hand should not blink out
        just because it is pointing at the camera - but it does not get to
        rewrite the reference the rest of the session is measured against.
        """
        state = self._pixels.get(side)
        straight = np.array([sum(FINGERS[name][1]) for name in FINGERS])
        if state is None:
            state = {"palm": palm_px, "width": width_px, "chord": straight.copy()}
        if trusted:
            state["palm"] = max(state["palm"] * DECAY, palm_px)
            state["width"] = max(state["width"] * DECAY, width_px)
            state["chord"] = np.clip(
                np.maximum(state["chord"] * DECAY, chords),
                straight * CHORD_FLOOR,
                straight * CHORD_CEILING,
            )
        self._pixels[side] = state
        ratio = float(state["width"]) / max(float(state["palm"]), 1e-6)
        return min(max(ratio, 0.40), 0.90), np.asarray(state["chord"], dtype=np.float64)

    @staticmethod
    def _fit_curl(
        name: str,
        observed: np.ndarray,
        projected: np.ndarray,
        palm: np.ndarray,
        previous: float | None,
        continuity: float = FIT_CONTINUITY,
    ) -> float | None:
        """Which curl best reproduces the phalanges the camera saw.

        ``observed`` is the finger's three phalanx vectors as measured in the
        image, ``projected`` the image direction of a straight phalanx leaving
        the knuckle across the palm (``x`` in the hand frame), and ``palm`` the
        palm normal's image components - the direction a closing finger bends
        towards. For a candidate curl the finger is rebuilt and projected, and
        the two chains are compared after fitting one scale factor.

        That free scale is the whole point. The old criterion divided the
        finger's chord by the palm's projected length, and the palm is the part
        of the hand that disappears first when it tilts; the observed fingers
        then read longer than a straight finger can be, the ratio saturates and
        a fist is indistinguishable from an open hand. Fitting the shape instead
        of a ratio makes a uniform shrink or stretch of the observed fingers
        irrelevant, so the answer no longer depends on how squarely the palm
        faces the camera.

        Returns ``None`` when the finger projects too small to say anything -
        pointed at the camera it is a few pixels of noise, and the caller keeps
        its previous estimate rather than inventing one.
        """
        span = float(np.sum(np.linalg.norm(observed, axis=1)))
        if span < MIN_FIT_SPAN:
            return None
        grid = np.linspace(0.0, 1.0, _TABLE_STEPS)
        angles = np.asarray(FLEXION[name], dtype=np.float64)
        lengths = np.asarray(FINGERS[name][1], dtype=np.float64)[:, None]
        best_cost, best = None, 0.0
        for candidate in grid:
            theta = angles * candidate
            chain = lengths * (np.cos(theta)[:, None] * projected + np.sin(theta)[:, None] * palm)
            denom = float(np.sum(chain * chain))
            if denom < 1e-12:
                continue
            scale = float(np.sum(chain * observed)) / denom
            residual = float(np.sum((scale * chain - observed) ** 2)) / (span * span)
            if previous is not None:
                residual += continuity * (float(candidate) - previous) ** 2
            if best_cost is None or residual < best_cost:
                best_cost, best = residual, float(candidate)
        return best

    @staticmethod
    def _thumb_bend(straight: np.ndarray, palm_side: float) -> np.ndarray | None:
        """The direction a closing thumb travels, in palm coordinates.

        The four fingers hinge about the knuckles and leave the palm plane, so
        they bend along the palm normal. The thumb folds *across* the palm
        instead: in a fist it ends up lying along the index finger, inside the
        palm's own plane. Bending it along the normal - which is what this file
        did - sends it out of the hand, no candidate curl reproduces the folded
        chain the camera sees, and the fit answers "straight" every frame. On
        this project's recordings that pinned the thumb at 0.00 for whole
        sessions, including frames where it is plainly tucked under the fingers.

        So: perpendicular to the thumb's own metacarpal, pointing across the
        palm towards the fingertips' side, and lifted a little off the surface
        so the thumb passes over the folded fingers rather than through them.
        """
        up = np.array([0.0, 1.0, 0.0])  # wrist -> middle knuckle
        across = _unit(up - straight * float(up @ straight))
        if across is None:
            return None
        lifted = across + THUMB_LIFT * np.array([0.0, 0.0, palm_side])
        lifted = _unit(lifted)
        return lifted if lifted is not None else across

    def _settle_basis(self, side: str, basis, across=None, along=None):
        """Make the measured palm frame continuous, and rebuild it orthonormal.

        ``basis`` is MediaPipe's own estimate of the palm's orientation. It is
        the only signal that knows how far the palm is tipped towards the lens,
        and it is also the noisiest: on this project's recordings one frame in a
        hundred lands the palm normal on the far side of the hand, 167 degrees
        from where it was. The receiver maps this frame onto the avatar's wrist
        in world space, so a frame like that does not add noise, it turns the
        hand inside out - and the next frame turns it back, which is a twitch,
        not a gesture.

        The half turn is settled by the picture, not by time: ``palm_depth_sign``
        reads which side of the hand is on show off the 2D landmarks and the
        measured normal is flipped to agree with it. What is left over is the
        roll, which is small and is blended when it looks like noise. A genuine
        flip and a noise flip are no longer the same event, so nothing has to be
        rejected - and a filter that rejects is a filter that can latch, which
        is what held both hands of a real session 180 degrees out from the first
        time their owner turned them over.

        The ``y`` axis (wrist -> knuckles) is kept as measured because it *is*
        reliable - it comes from two well separated landmarks and it is what the
        joints are expressed against. The result is orthonormalised with
        ``x = y cross z``, so the triple stays right-handed and the receiver's
        ``LookRotation`` never sees a skewed frame.

        Returns the frame to use, or ``None`` when the input is degenerate.
        """
        y = _unit(np.asarray(basis[1], dtype=np.float64))
        z = _unit(np.asarray(basis[2], dtype=np.float64))
        if y is None or z is None:
            return None
        z = _unit(z - y * float(z @ y))
        if z is None:
            return None
        if across is not None and along is not None:
            want = palm_depth_sign(across, along)
            if want and float(z[2]) * want < 0.0:
                # Flipping z alone would mirror the hand; the orthonormalisation
                # below rebuilds x = y cross z, which flips x with it, so the
                # result is the half turn about y that the palm actually made.
                z = -z
        previous = self._axes.get(side)
        if previous is not None:
            step = math.degrees(math.acos(max(-1.0, min(1.0, float(z @ previous[2])))))
            if step <= BASIS_SNAP:
                blended = _unit(previous[2] * BASIS_SMOOTHING + z * (1.0 - BASIS_SMOOTHING))
                if blended is not None:
                    flattened = _unit(blended - y * float(blended @ y))
                    if flattened is not None:
                        z = flattened
        x = _unit(np.cross(y, z))
        if x is None:
            return None
        z = _unit(np.cross(x, y))
        if z is None:
            return None
        frame = (x, y, z)
        self._axes[side] = frame
        return frame

    def _frame(self, side: str, across: np.ndarray, along: np.ndarray, ratio: float):
        """Orthonormal palm axes, or ``None`` when the palm is degenerate.

        ``ratio`` is how wide this hand is compared with its own palm, measured
        when the palm was square to the camera. Both of the palm's observed
        axes are then compared with that: whatever the pair is *narrower* than
        it should be is foreshortening, and the only question is which axis it
        belongs to.

        The previous version answered that by fiat - the length axis was assumed
        to lie in the image plane - and the assumption is wrong for the one pose
        this project is actually used in: a hand held at chest height, tipped
        forward. Tipping shrinks the palm's length and nothing else, so the
        observed width/palm ratio climbs above the calibrated one, and that
        excess is the tilt. Splitting it off is what lets the flexion fit know
        that a closing finger is curling away from the camera rather than across
        the picture, which is the difference between "fist" and "no idea".
        """
        forward = _unit(np.array([along[0], along[1], 0.0]))
        if forward is None:
            return None
        width = float(np.linalg.norm(across))
        if width < 1e-6:
            return None
        # width/palm observed over width/palm calibrated. A pure roll makes it
        # smaller than one, a pure tilt makes it bigger than one; anything left
        # over after the tilt is the roll.
        shrink = width / max(ratio, 1e-6)
        along_seen = min(1.0, 1.0 / max(shrink, 1e-6))
        lean = math.sqrt(max(1.0 - along_seen * along_seen, 0.0))
        across_seen = min(shrink * along_seen, 1.0)
        rise = math.sqrt(max(1.0 - across_seen * across_seen, 0.0))
        direction = across / width
        candidates = []
        for tilt in (lean, -lean):
            y = _unit(np.array([forward[0] * along_seen, forward[1] * along_seen, tilt]))
            if y is None:
                continue
            for sign in (rise, -rise):
                x = np.array([across_seen * direction[0], across_seen * direction[1], sign])
                x = _unit(x - y * float(x @ y))
                if x is None:
                    continue
                z = _unit(np.cross(x, y))
                if z is None:
                    continue
                candidates.append((x, y, z))
        if not candidates:
            return None
        previous = self._normal.get(side)
        if previous is not None:
            return max(candidates, key=lambda c: float(c[2] @ previous))
        # First frame: one frame cannot say which side of the image plane the
        # palm leans towards - both candidates project identically - so take the
        # first and let continuity pin it. When the palm is face-on, which is how
        # a user stands when they start the tracker, the two coincide anyway.
        return candidates[0]

    # ------------------------------------------------------------------ solve

    def solve(self, screen, side: str, basis=None):
        """Return ``(local_points, palm_length_px, axes)`` or ``None``.

        ``screen`` is MediaPipe's normalised 2D landmarks and ``side`` decides
        which way the palm faces. ``local_points`` are 21 joints in the hand
        frame, normalised by the palm length; ``axes`` are that frame's three
        unit axes in the image frame (x right, y down, z into the scene).

        ``basis`` is the palm's orientation measured from MediaPipe's world
        landmarks, when the caller has it. The camera cannot see how far the
        palm is tipped towards or away from it - the same picture is produced by
        a short palm and by a long palm pointing at the lens - so ``_frame`` has
        to infer the tip from how much narrower the palm looks than it did when
        it was square to the camera. That inference is the weakest number in
        this file: it depends on the hand having been shown flat at least once,
        and it is 64 degrees out at the median on the recording available here,
        173 at worst (measured against the world landmarks, which see the tip
        directly). Everything
        downstream - where the knuckles sit in depth, which way in the picture a
        closing finger bends - is built on those axes, which is why a hand held
        at chest height used to come out as a tangle.
        """
        if side not in PALM_SIDE:
            raise ValueError(f"side must be 'Left' or 'Right', got {side!r}")
        q = np.asarray(screen, dtype=np.float64)[:, :2]
        if q.shape != (LANDMARK_COUNT, 2) or not np.all(np.isfinite(q)):
            return None
        # MediaPipe normalises x by the image width and y by its height.
        q = q * np.array([self.aspect, 1.0])
        q = q - q[WRIST]

        palm_pixels = float(np.linalg.norm(q[MIDDLE_MCP]))
        if palm_pixels < 1e-6:
            return None
        width_pixels = float(np.linalg.norm(q[PINKY_MCP] - q[INDEX_MCP]))
        # Two ways a detection goes wrong in a way that outlives the frame,
        # because the calibration is stateful: the palm shrinks to a fraction of
        # itself, or it comes back wider than it is long. The first is a lost
        # hand and there is nothing to reconstruct, so the frame goes. The
        # second is usually a genuine foreshortened palm pointing at the camera,
        # so the frame is kept but barred from rewriting the calibration.
        known = self._pixels.get(side)
        if known is not None and palm_pixels < known["palm"] * PALM_COLLAPSE:
            return None
        trusted = width_pixels <= palm_pixels * PALM_ASPECT_MAX
        names = list(FINGERS)
        chords = (
            np.array(
                [
                    float(np.linalg.norm(q[FINGERS[name][0][3]] - q[FINGERS[name][0][0]]))
                    for name in names
                ]
            )
            / palm_pixels
        )
        ratio, chord_ratios = self._calibrate(side, palm_pixels, width_pixels, chords, trusted)
        u = q / palm_pixels  # palm length == 1 from here on

        across = u[PINKY_MCP] - u[INDEX_MCP]
        along = u[MIDDLE_MCP] - u[WRIST]

        palm_side = PALM_SIDE[side]
        x = y = z = None
        if basis is not None:
            # Measured orientation wins over the inferred one. It is already in
            # the image frame (see ``tracker.image_frame``) and orthonormal, so
            # the projection below is a plain 2x2 map with no correction terms.
            # ``_settle_basis`` settles which of the two half turns it means and
            # then filters it: the joints are built in exactly the frame that
            # goes on the wire, so the receiver never has to relate two of them.
            axes = [np.asarray(axis, dtype=np.float64) for axis in basis]
            if len(axes) == 3 and all(np.all(np.isfinite(a)) for a in axes):
                settled = self._settle_basis(side, axes, across, along)
                if settled is not None:
                    x, y, z = settled
        if x is None:
            picked = self._frame(side, across, along, ratio)
            if picked is None:
                return None
            x, y, z = picked
            self._axes[side] = picked
        self._normal[side] = z

        # The palm's own projection, as a 2x2 map from palm coordinates to
        # image coordinates. Inverting it is how every landmark gets its place
        # on the palm: the old code divided by the normal's depth instead, which
        # multiplies the error by 1/n_z and explodes as the palm turns edge-on.
        # The determinant is the palm's footprint in the image - when it is too
        # small the knuckles' depth is simply not observable, so the frame is
        # refused rather than invented.
        #
        # The map then has to be scaled by how much of the palm's length made it
        # onto the picture, because ``u`` was divided by exactly that: ``u`` is
        # in projected palm lengths, not palm lengths. Without it every knuckle
        # lands 1/cos(tip) too far from the wrist - a hand tipped 60 degrees
        # comes out twice its size, with finger lengths that no longer belong to
        # it, which is what "a tangle in front of the chest" looked like.
        # How much of the palm's length made it onto the picture. One means the
        # palm lies in the image plane, zero means it points at the lens.
        seen = float(np.hypot(y[0], y[1]))
        projection = np.array([[x[0], y[0]], [x[1], y[1]]])
        footprint = float(projection[0, 0] * projection[1, 1] - projection[0, 1] * projection[1, 0])
        if np.isfinite(footprint) and abs(footprint) >= MIN_PALM_FOOTPRINT:
            flat = np.linalg.solve(projection / max(seen, 1e-9), u.T).T
            self._flat[side] = flat
        else:
            # The palm is edge-on and the knuckles' depth simply is not in the
            # picture. The palm is rigid, so the last frame that could be solved
            # still describes it - holding that beats dropping the hand for the
            # second it takes to turn over.
            flat = self._flat.get(side)
            if flat is None:
                return None

        # Fingers hinge towards the palm. In the hand frame that is +z times
        # this sign. The thumb is the exception and gets its own bend direction
        # from ``_thumb_bend``.
        palm_axis = np.array([0.0, 0.0, palm_side])

        points = np.zeros((LANDMARK_COUNT, 3))
        for joint in (WRIST, THUMB_CMC, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
            points[joint] = np.array([flat[joint][0], flat[joint][1], 0.0])

        curls = self._curl.setdefault(side, {})
        for index, name in enumerate(names):
            chain, lengths = FINGERS[name]

            # The direction the finger leaves the palm in, in palm coordinates.
            # For the four fingers that is the knuckle's offset from the wrist:
            # their metacarpals are rigid, so it gives the fan angle for free and
            # does not swing when the finger curls. A curled finger's first
            # phalanx points at the camera, so reading the fan angle off that
            # instead would swing the whole finger sideways as the hand closes.
            #
            # The thumb is the exception. Its metacarpal swings, and that swing
            # *is* the gesture - sticking a thumb up or out is the thumb moving
            # away from the palm, not curling. So its direction is measured from
            # the landmarks themselves, and the anatomical direction is only a
            # fallback for when the thumb is folded too tightly to have one.
            beyond = _unit(flat[chain[0]] - flat[WRIST])
            heading = beyond
            if name == "Thumb":
                reach = flat[4] - flat[1]
                if float(np.linalg.norm(reach)) > MIN_THUMB_REACH:
                    measured = _unit(reach)
                    if measured is not None:
                        heading = measured
            if heading is None:
                continue

            straight = np.array([heading[0], heading[1], 0.0])
            if name == "Thumb":
                bend = self._thumb_bend(straight, palm_side)
                if bend is None:
                    bend = palm_axis
                # The thumb's bend lives in the palm plane, so it goes through
                # the same 2x2 map as the finger directions.
                bend_image = projection @ bend[:2]
            else:
                bend = palm_axis
                # The palm normal is already a unit vector in the image frame;
                # its x and y are the direction a closing finger appears to
                # travel in the picture.
                bend_image = palm_side * np.array([z[0], z[1]])

            observed = np.array([u[chain[k + 1]] - u[chain[k]] for k in range(3)])
            fitted = self._fit_curl(
                name,
                observed,
                projection @ straight[:2],
                bend_image,
                curls.get(name),
                THUMB_CONTINUITY if name == "Thumb" else FIT_CONTINUITY,
            )
            if fitted is None:
                # Nothing but a smudge of pixels: keep what this finger was
                # doing instead of re-deciding from noise.
                wanted = curls.get(name)
            else:
                wanted = min(max((fitted - CURL_FLOOR) / (CURL_CEILING - CURL_FLOOR), 0.0), 1.0)
            if wanted is None:
                measured = float(np.linalg.norm(u[chain[3]] - u[chain[0]]))
                wanted = curl_from_ratio(name, measured / max(float(chord_ratios[index]), 1e-6))
            seen = curls.get(name)
            curl = (
                wanted
                if seen is None
                else ((1.0 - CURL_SMOOTHING) * wanted + CURL_SMOOTHING * seen)
            )
            curls[name] = curl

            cursor = points[chain[0]].copy()
            for segment in range(3):
                angle = FLEXION[name][segment] * curl
                direction = math.cos(angle) * straight + math.sin(angle) * bend
                cursor = cursor + direction * lengths[segment]
                points[chain[segment + 1]] = cursor

        local = points
        return self._settle(side, local), palm_pixels, (x, y, z)
