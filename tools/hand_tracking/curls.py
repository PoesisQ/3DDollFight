"""Finger flexion from 21 MediaPipe hand landmarks.

Pure geometry on purpose: this module must stay importable without MediaPipe so
the maths can be unit tested on any machine.
"""

from __future__ import annotations

import math

import numpy as np

CURL_COUNT = 15
FINGER_NAMES = ("Thumb", "Index", "Middle", "Ring", "Little")
SEGMENT_NAMES = ("MCP", "PIP", "DIP")

# Chain of five landmarks per finger: wrist, base, middle, distal, tip.
# Index/Middle/Ring/Little share the wrist as the metacarpal anchor; the thumb
# uses its own CMC joint so the chain stays inside the hand.
CHAINS = {
    "Thumb": (0, 1, 2, 3, 4),
    "Index": (0, 5, 6, 7, 8),
    "Middle": (0, 9, 10, 11, 12),
    "Ring": (0, 13, 14, 15, 16),
    "Little": (0, 17, 18, 19, 20),
}

# Anatomical range of each joint, used to normalise degrees into [0, 1].
MAX_DEGREES = {
    "Thumb": (45.0, 60.0, 40.0),
    "Index": (90.0, 100.0, 70.0),
    "Middle": (90.0, 100.0, 70.0),
    "Ring": (90.0, 100.0, 70.0),
    "Little": (90.0, 100.0, 70.0),
}


def _flexion_degrees(chain: np.ndarray) -> np.ndarray:
    """Bend angle at the three inner joints, 0 meaning the chain is straight."""
    angles = np.zeros(3, dtype=np.float64)
    for i in range(1, 4):
        incoming = chain[i - 1] - chain[i]
        outgoing = chain[i + 1] - chain[i]
        norm = float(np.linalg.norm(incoming) * np.linalg.norm(outgoing))
        if norm < 1e-9:
            continue
        cosine = float(np.clip(np.dot(incoming, outgoing) / norm, -1.0, 1.0))
        angles[i - 1] = 180.0 - math.degrees(math.acos(cosine))
    return angles


def compute_curls(world_landmarks) -> np.ndarray:
    """Convert ``(21, 3)`` metric landmarks into 15 normalised curls.

    Order matches ``protocol.py``: Thumb/Index/Middle/Ring/Little, each with
    MCP/PIP/DIP. Values are clamped to ``[0, 1]``; a missing or degenerate
    chain yields zeros instead of NaN.
    """
    points = np.asarray(world_landmarks, dtype=np.float64)
    if points.shape != (21, 3) or not np.all(np.isfinite(points)):
        return np.zeros(CURL_COUNT, dtype=np.float32)
    curls = np.zeros(CURL_COUNT, dtype=np.float32)
    for finger_index, name in enumerate(FINGER_NAMES):
        chain = points[list(CHAINS[name])]
        degrees = _flexion_degrees(chain)
        limits = np.asarray(MAX_DEGREES[name], dtype=np.float64)
        curls[finger_index * 3:(finger_index + 1) * 3] = np.clip(degrees / limits, 0.0, 1.0)
    return curls


def classify(curls) -> str:
    """Coarse label for presentation only; never used for hit detection."""
    values = np.asarray(curls, dtype=np.float64)
    if values.shape != (CURL_COUNT,):
        return "unknown"
    mean = float(values.mean())
    index = float(values[3:6].mean())
    others = float(np.delete(values, [3, 4, 5]).mean())
    if mean < 0.25:
        return "open"
    if mean > 0.7:
        return "fist"
    if index < 0.2 and others > 0.55:
        return "point"
    return "unknown"


class CurlSmoother:
    """One Euro filter per curl channel, adapted for low-latency hand motion."""

    def __init__(self, minimum_cutoff: float = 1.2, beta: float = 0.08,
                 derivative_cutoff: float = 1.0):
        self.minimum_cutoff = float(minimum_cutoff)
        self.beta = float(beta)
        self.derivative_cutoff = float(derivative_cutoff)
        self.value = None
        self.derivative = np.zeros(CURL_COUNT, dtype=np.float64)

    @staticmethod
    def _alpha(cutoff: float, delta: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-3))
        return 1.0 / (1.0 + tau / max(delta, 1e-3))

    def reset(self) -> None:
        self.value = None
        self.derivative = np.zeros(CURL_COUNT, dtype=np.float64)

    def apply(self, curls, delta: float) -> np.ndarray:
        sample = np.asarray(curls, dtype=np.float64)
        if sample.shape != (CURL_COUNT,):
            return np.zeros(CURL_COUNT, dtype=np.float32)
        if self.value is None:
            self.value = sample.copy()
            return sample.astype(np.float32)
        raw_derivative = (sample - self.value) / max(delta, 1e-3)
        alpha_d = self._alpha(self.derivative_cutoff, delta)
        self.derivative += alpha_d * (raw_derivative - self.derivative)
        cutoff = self.minimum_cutoff + self.beta * np.abs(self.derivative)
        alpha = np.array([self._alpha(float(c), delta) for c in cutoff])
        self.value += alpha * (sample - self.value)
        return np.clip(self.value, 0.0, 1.0).astype(np.float32)
