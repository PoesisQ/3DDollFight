"""Builds ``dollfight-hands-3`` datagrams for the Unity receiver.

Version 3 adds the hand's own axes. The 21 joints are expressed *inside* the
hand frame, so they say where the fingers are but not how the palm is rolled
around the forearm; without that the avatar's wrist keeps whatever roll the
body tracker happened to leave it with, and a raised palm reads as edge-on.
Version 2 carried the skeleton only, version 1 only the 15 finger curls; the
receiver still accepts all three.

Kept separate from the tracker so the wire format can be asserted in tests
without MediaPipe or a camera.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping

import numpy as np
import skeleton

VERSION = 3
LEGACY_VERSIONS = (1, 2)
CURL_COUNT = 15
JOINT_COUNT = skeleton.LANDMARK_COUNT
COORD_COUNT = JOINT_COUNT * 3
AXIS_COUNT = 9
SIDES = ("Left", "Right")


def _clean_curls(values: Iterable[float]) -> list[float]:
    curls = list(values)
    if len(curls) != CURL_COUNT:
        raise ValueError(f"curls must have {CURL_COUNT} values, got {len(curls)}")
    cleaned = []
    for value in curls:
        number = float(value)
        if not math.isfinite(number):
            number = 0.0
        cleaned.append(round(min(1.0, max(0.0, number)), 4))
    return cleaned


def _clean_joints(local) -> list[float]:
    points = np.asarray(local, dtype=np.float64)
    if points.shape != (JOINT_COUNT, 3):
        raise ValueError(f"joints must be {(JOINT_COUNT, 3)}, got {points.shape}")
    if not np.all(np.isfinite(points)):
        raise ValueError("joints contain non-finite values")
    clipped = np.clip(points, -skeleton.LOCAL_LIMIT, skeleton.LOCAL_LIMIT)
    return [round(float(value), 4) for value in clipped.reshape(-1)]


def _clean_basis(axes) -> list[float]:
    """Nine numbers: the hand frame's x, y and z unit vectors."""
    values = np.asarray(axes, dtype=np.float64).reshape(-1)
    if values.size != AXIS_COUNT:
        raise ValueError(f"basis must have {AXIS_COUNT} values, got {values.size}")
    if not np.all(np.isfinite(values)):
        raise ValueError("basis contains non-finite values")
    normalised = values.reshape(3, 3)
    lengths = np.linalg.norm(normalised, axis=1)
    if np.any(lengths < 1e-6):
        raise ValueError("basis contains a zero axis")
    normalised = normalised / lengths[:, None]
    return [round(float(value), 4) for value in normalised.reshape(-1)]


def hand_entry(
    side: str,
    confidence: float,
    local,
    scale_mm: float,
    curls,
    gesture: str = "unknown",
    basis=None,
) -> dict:
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, got {side!r}")
    return {
        "side": side,
        "confidence": round(float(min(1.0, max(0.0, confidence))), 3),
        "gesture": gesture,
        "scaleMm": round(float(scale_mm), 2),
        "joints": _clean_joints(local),
        "curls": _clean_curls(curls),
        "basis": _clean_basis(basis),
    }


def encode(session: str, sequence: int, timestamp_ms: int, hands: Iterable[Mapping]) -> bytes:
    message = {
        "version": VERSION,
        "session": session,
        "sequence": int(sequence),
        "timestampMs": int(timestamp_ms),
        "hands": list(hands),
    }
    return json.dumps(message, separators=(",", ":")).encode("utf-8")
