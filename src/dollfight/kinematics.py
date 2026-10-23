"""Reference humanoid, analytic IK and engine-independent local bone rotations."""

import numpy as np

from dollfight.contracts import JOINTS

INDEX = {name: i for i, name in enumerate(JOINTS)}
PARENTS = np.array([-1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 13, 0, 15, 16, 17])
EDGES = [(int(parent), i) for i, parent in enumerate(PARENTS) if parent >= 0]
PROFILES = {
    "standard": {"label": "标准体型", "arms": 1.0, "legs": 1.0, "width": 1.0},
    "reach": {"label": "长臂轻量", "arms": 1.25, "legs": 1.08, "width": 0.88},
    "power": {"label": "宽肩重型", "arms": 1.08, "legs": 0.86, "width": 1.35},
}


def unit(vector, fallback=(0.0, 1.0, 0.0)):
    vector = np.asarray(vector, dtype=float)
    length = np.linalg.norm(vector)
    return vector / length if length > 1e-8 else np.asarray(fallback, dtype=float)


def rotation_y(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def swing_rotation(source, target):
    a, b = unit(source), unit(target)
    cross = np.cross(a, b)
    cosine = float(np.clip(a @ b, -1, 1))
    if cosine < -0.999999:
        axis = unit(np.cross(a, np.eye(3)[np.argmin(np.abs(a))]))
        return 2 * np.outer(axis, axis) - np.eye(3)
    skew = np.array([[0, -cross[2], cross[1]], [cross[2], 0, -cross[0]], [-cross[1], cross[0], 0]])
    return np.eye(3) + skew + skew @ skew / (1 + cosine)


def quaternion(matrix):
    """Rotation matrix to normalized xyzw; stable at 180 degrees."""
    m = np.asarray(matrix)
    trace = np.trace(m)
    if trace > 0:
        scale = np.sqrt(trace + 1) * 2
        q = np.array(
            [
                (m[2, 1] - m[1, 2]) / scale,
                (m[0, 2] - m[2, 0]) / scale,
                (m[1, 0] - m[0, 1]) / scale,
                scale / 4,
            ]
        )
    else:
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        scale = np.sqrt(max(1 + m[i, i] - m[j, j] - m[k, k], 1e-12)) * 2
        q = np.zeros(4)
        q[i], q[j], q[k] = scale / 4, (m[i, j] + m[j, i]) / scale, (m[i, k] + m[k, i]) / scale
        q[3] = (m[k, j] - m[j, k]) / scale
    q /= np.linalg.norm(q)
    return q if q[3] >= 0 else -q


def rest_pose(profile="standard"):
    p = np.array(
        [
            [0, 0.95, 0],
            [0, 1.12, 0],
            [0, 1.38, 0],
            [0, 1.51, 0],
            [0, 1.65, 0],
            [0.22, 1.38, 0],
            [0.51, 1.38, 0],
            [0.78, 1.38, 0],
            [-0.22, 1.38, 0],
            [-0.51, 1.38, 0],
            [-0.78, 1.38, 0],
            [0.105, 0.95, 0],
            [0.105, 0.52, 0.015],
            [0.105, 0.09, 0],
            [0.105, 0.04, 0.17],
            [-0.105, 0.95, 0],
            [-0.105, 0.52, 0.015],
            [-0.105, 0.09, 0],
            [-0.105, 0.04, 0.17],
        ]
    )
    settings = PROFILES[profile]
    result = p.copy()
    result[0, 1] = 0.09 + (0.95 - 0.09) * settings["legs"]
    for parent, child in EDGES:
        offset = p[child] - p[parent]
        if child in (6, 7, 9, 10):
            offset *= settings["arms"]
        if child in (12, 13, 16, 17):
            offset *= settings["legs"]
        if child in (5, 8, 11, 15):
            offset *= settings["width"]
        result[child] = result[parent] + offset
    return result


def bone_lengths(points):
    points = np.asarray(points, dtype=float)
    return np.array([np.linalg.norm(points[c] - points[p]) for p, c in EDGES])


def two_bone_ik(root, target, length_a, length_b, hint):
    root, target, hint = map(lambda x: np.asarray(x, dtype=float), (root, target, hint))
    direction = unit(target - root)
    distance = np.clip(
        np.linalg.norm(target - root), abs(length_a - length_b) + 1e-6, length_a + length_b - 1e-6
    )
    along = (length_a**2 + distance**2 - length_b**2) / (2 * distance)
    height = np.sqrt(max(length_a**2 - along**2, 0))
    orthogonal = hint - root - direction * ((hint - root) @ direction)
    if np.linalg.norm(orthogonal) < 1e-8:
        orthogonal = np.cross(direction, np.eye(3)[np.argmin(np.abs(direction))])
    middle = root + direction * along + unit(orthogonal) * height
    return middle, root + direction * distance


def body_basis(points):
    up = unit(points[2] - points[0])
    left = points[5] - points[8]
    left = unit(left - up * (left @ up), (1, 0, 0))
    forward = unit(np.cross(left, up), (0, 0, 1))
    return np.column_stack((left, up, forward))


class Retargeter:
    """Fixed target lengths; FK swing mapping followed by optional planted-foot IK.

    Only joint positions are observed, so axial wrist/forearm twist is not
    measured. We preserve the parent reference rather than inventing twist.
    """

    def __init__(self, source_rest, profile="standard", foot_lock=True):
        self.source_rest = np.asarray(source_rest)
        self.rest = rest_pose(profile)
        self.foot_lock = foot_lock
        self.previous_feet = None
        self.anchors = {}
        self.previous_quaternions = None

    def process(self, source, dt):
        offsets = self.rest.copy()
        for parent, child in EDGES:
            offsets[child] -= self.rest[parent]
        basis = body_basis(source)
        flat_forward = unit([basis[0, 2], 0, basis[2, 2]], (0, 0, 1))
        root_rotation = np.column_stack(
            (np.cross([0, 1, 0], flat_forward), [0, 1, 0], flat_forward)
        )
        rotations = np.repeat(np.eye(3)[None], len(JOINTS), axis=0)
        rotations[0] = root_rotation
        # Torso frame retains measured lean and shoulder orientation.
        for index in (1, 2, 3):
            rotations[index] = basis
        for start, end in (
            (5, 6),
            (6, 7),
            (8, 9),
            (9, 10),
            (11, 12),
            (12, 13),
            (13, 14),
            (15, 16),
            (16, 17),
            (17, 18),
        ):
            parent_rotation = rotations[PARENTS[start]]
            rest_direction = parent_rotation @ offsets[end]
            rotations[start] = (
                swing_rotation(rest_direction, source[end] - source[start]) @ parent_rotation
            )
        for terminal in (4, 7, 10, 14, 18):
            rotations[terminal] = rotations[PARENTS[terminal]]
        points = np.zeros_like(source)
        ratio = self.rest[0, 1] / self.source_rest[0, 1]
        points[0] = self.rest[0] + (source[0] - self.source_rest[0]) * ratio
        for parent, child in EDGES:
            points[child] = points[parent] + rotations[parent] @ offsets[child]
        contacts = [False, False]
        feet = source[[13, 17]].copy()
        if self.foot_lock and self.previous_feet is not None:
            for side, (hip, knee, ankle, toe) in enumerate(((11, 12, 13, 14), (15, 16, 17, 18))):
                speed = np.linalg.norm(feet[side] - self.previous_feet[side]) / max(dt, 1e-3)
                near_ground = source[ankle, 1] < self.source_rest[ankle, 1] + 0.07
                if near_ground and speed < 0.25:
                    anchor = self.anchors.setdefault(side, points[ankle].copy())
                    anchor[1] = self.rest[ankle, 1]
                    k, a = two_bone_ik(
                        points[hip],
                        anchor,
                        np.linalg.norm(offsets[knee]),
                        np.linalg.norm(offsets[ankle]),
                        points[knee],
                    )
                    rotations[hip] = (
                        swing_rotation(rotations[hip] @ offsets[knee], k - points[hip])
                        @ rotations[hip]
                    )
                    rotations[knee] = (
                        swing_rotation(rotations[knee] @ offsets[ankle], a - k) @ rotations[knee]
                    )
                    points[knee], points[ankle] = k, a
                    points[toe] = a + rotations[ankle] @ offsets[toe]
                    contacts[side] = True
                else:
                    self.anchors.pop(side, None)
        self.previous_feet = feet
        quaternions = []
        for i, parent in enumerate(PARENTS):
            local = rotations[i] if parent < 0 else rotations[parent].T @ rotations[i]
            q = quaternion(local)
            if self.previous_quaternions is not None and q @ self.previous_quaternions[i] < 0:
                q = -q
            quaternions.append(q)
        self.previous_quaternions = np.array(quaternions)
        return points, self.previous_quaternions, contacts
