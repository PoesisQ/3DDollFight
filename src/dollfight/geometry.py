"""Explicit coordinate conventions for RGB-D integration.

Camera: right-handed, +X image right, +Y image down, +Z optical forward.
Stage: right-handed, +Y up; placement relative to each camera comes from calibration.
Unity: convert the shared stage basis with H = diag(1, 1, -1).
All distances are meters; input pixels must already be undistorted.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float

    def __post_init__(self) -> None:
        if not np.isfinite([self.fx, self.fy, self.cx, self.cy]).all():
            raise ValueError("Intrinsics must be finite")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("Focal lengths must be positive")


def backproject(
    pixels: ArrayLike, depth_m: ArrayLike, intrinsics: Intrinsics
) -> NDArray[np.float64]:
    """Backproject optical-axis depth, NOT range along a normalized viewing ray.

    Pixels/depth must refer to the same aligned, undistorted image grid and
    matching intrinsics. Missing depth must be masked by the caller first.
    The output is a surface observation, not an anatomical joint center.
    """
    uv = np.asarray(pixels, dtype=float)
    z = np.asarray(depth_m, dtype=float)
    if uv.ndim != 2 or uv.shape[1] != 2 or z.shape != (len(uv),):
        raise ValueError("Expected pixels (N, 2) and depth_m (N,)")
    if not np.isfinite(uv).all() or not np.isfinite(z).all() or np.any(z <= 0):
        raise ValueError("Pixels must be finite and depth must be finite and positive")
    x = (uv[:, 0] - intrinsics.cx) * z / intrinsics.fx
    y = (uv[:, 1] - intrinsics.cy) * z / intrinsics.fy
    return np.column_stack((x, y, z))


def transform_points(points: ArrayLike, target_from_source: ArrayLike) -> NDArray[np.float64]:
    """Apply a rigid 4x4 column-vector transform; reflection and scale are rejected."""
    p = np.asarray(points, dtype=float)
    transform = np.asarray(target_from_source, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or not np.isfinite(p).all():
        raise ValueError("Expected finite points (N, 3)")
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("Expected a finite 4x4 transform")
    rotation = transform[:3, :3]
    if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-6, rtol=0):
        raise ValueError("Invalid homogeneous last row")
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0):
        raise ValueError("Rotation must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1, atol=1e-6, rtol=0):
        raise ValueError("Use an explicit basis conversion for handedness changes")
    return p @ rotation.T + transform[:3, 3]


def stage_rotation_to_unity(rotation: ArrayLike) -> NDArray[np.float64]:
    """Convert a rotation operator with H R H^-1, not a quaternion sign guess."""
    r = np.asarray(rotation, dtype=float)
    if r.shape != (3, 3) or not np.isfinite(r).all():
        raise ValueError("Expected a finite 3x3 rotation")
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-6, rtol=0):
        raise ValueError("Rotation must be orthonormal")
    if not np.isclose(np.linalg.det(r), 1, atol=1e-6, rtol=0):
        raise ValueError("Rotation must have determinant +1")
    basis = np.diag([1.0, 1.0, -1.0])
    return basis @ r @ basis
