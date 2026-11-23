"""Sample registered depth for hand landmarks; invalid measurements remain NaN.

This helper does not acquire or synchronize frames. Only pass a depth frame
registered to the same colour image used to compute the landmarks.
"""

import numpy as np

PALM = (0, 5, 9, 13, 17)


def sample_hand_depth(depth_mm, landmarks, radius=2, max_offset_mm=100):
    """Return 21 depths in mm, rejecting holes and background near the hand."""
    depth = np.asarray(depth_mm)
    points = np.asarray(landmarks, dtype=float)
    if depth.ndim != 2 or points.shape != (21, 2):
        raise ValueError("expected a 2D depth frame and 21 (x, y) landmarks")
    if radius < 0 or max_offset_mm <= 0:
        raise ValueError("invalid depth filter parameters")
    h, w = depth.shape
    result = np.full(21, np.nan, dtype=float)
    for i, (x, y) in enumerate(points):
        if not np.isfinite(x) or not np.isfinite(y) or not (0 <= x < 1 and 0 <= y < 1):
            continue
        px, py = int(x * w), int(y * h)
        patch = depth[
            max(0, py - radius) : min(h, py + radius + 1),
            max(0, px - radius) : min(w, px + radius + 1),
        ]
        valid = patch[np.isfinite(patch) & (patch > 0)]
        if valid.size >= max(1, patch.size // 4):
            result[i] = float(np.median(valid))
    palm = result[list(PALM)]
    if np.isfinite(palm).sum() < 3:
        return np.full(21, np.nan, dtype=float)
    anchor = np.nanmedian(palm)
    result[np.abs(result - anchor) > max_offset_mm] = np.nan
    return result


def depth_to_camera_points(landmarks, depths_mm, width, height, fx, fy, cx, cy):
    """Back-project registered pixels with validated colour-camera intrinsics.

    Returns millimetres, with x right, y down and z away from the camera.
    Missing/rejected depth remains NaN and must never be sent to Unity.
    """
    points = np.asarray(landmarks, dtype=float)
    depths = np.asarray(depths_mm, dtype=float)
    if points.shape != (21, 2) or depths.shape != (21,):
        raise ValueError("expected 21 image points and depths")
    if width <= 0 or height <= 0 or not np.isfinite([fx, fy, cx, cy]).all() or fx <= 0 or fy <= 0:
        raise ValueError("valid measured camera intrinsics are required")
    valid = (
        np.isfinite(points).all(axis=1)
        & np.isfinite(depths)
        & (depths > 0)
        & (points[:, 0] >= 0)
        & (points[:, 0] < 1)
        & (points[:, 1] >= 0)
        & (points[:, 1] < 1)
    )
    result = np.full((21, 3), np.nan, dtype=float)
    result[valid, 0] = (points[valid, 0] * width - cx) * depths[valid] / fx
    result[valid, 1] = (points[valid, 1] * height - cy) * depths[valid] / fy
    result[valid, 2] = depths[valid]
    return result


def depth_palm_basis(depth_mm, landmarks, intrinsics):
    """Return a metric palm frame only when depth samples are trustworthy."""
    depth = np.asarray(depth_mm)
    if depth.ndim != 2 or landmarks is None or intrinsics is None or len(intrinsics) != 4:
        return None
    samples = sample_hand_depth(depth, landmarks)
    if np.isfinite(samples).sum() < 14 or not np.isfinite(samples[[0, 5, 9, 17]]).all():
        return None
    h, w = depth.shape
    try:
        points = depth_to_camera_points(landmarks, samples, w, h, *intrinsics)
    except ValueError:
        return None
    across = points[17] - points[5]
    along = points[9] - points[0]
    length = float(np.linalg.norm(along))
    if not 25 <= length <= 180:
        return None
    y = along / length
    across -= y * float(across @ y)
    width = float(np.linalg.norm(across))
    if not 20 <= width <= 180:
        return None
    x = across / width
    z = np.cross(x, y)
    return x, y, z


def blend_palm_basis(colour_basis, depth_basis, weight=0.35):
    """Conservatively blend aligned frames; fall back on disagreement."""
    if colour_basis is None or depth_basis is None:
        return colour_basis
    cx, cy, cz = (np.asarray(v, dtype=float) for v in colour_basis)
    dx, dy, dz = (np.asarray(v, dtype=float) for v in depth_basis)
    if not all(np.isfinite(v).all() for v in (cx, cy, cz, dx, dy, dz)):
        return colour_basis
    if float(cx @ dx) < 0.7 or float(cy @ dy) < 0.7 or float(cz @ dz) < 0.7:
        return colour_basis
    y = (1 - weight) * cy + weight * dy
    y /= np.linalg.norm(y)
    x = (1 - weight) * cx + weight * dx
    x -= y * float(x @ y)
    if np.linalg.norm(x) < 1e-6:
        return colour_basis
    x /= np.linalg.norm(x)
    return x, y, np.cross(x, y)
