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


def leg_ik_hint(hip, knee, ankle, target, forward):
    """Transport the current bend plane when editing a foot's destination.

    Reusing the old knee *position* as the pole can move it behind the new
    hip-to-foot axis and make a shortened stride bend the knee backwards.
    Near extension the joint positions do not observe that plane reliably;
    use the continuous thigh frame instead.
    """
    axis = unit(ankle - hip)
    pole = knee - hip - axis * ((knee - hip) @ axis)
    anterior = forward - axis * (forward @ axis)
    if np.linalg.norm(pole) < 0.025 or pole @ anterior < 0:
        # A negative hinge bend can arise from inertial overshoot. Do not
        # preserve that invalid solution when re-solving the same foot goal.
        pole = anterior
    pole = swing_rotation(axis, unit(target - hip)) @ unit(pole, forward)
    return hip + pole


def body_basis(points):
    up = unit(points[2] - points[0])
    left = points[5] - points[8]
    left = unit(left - up * (left @ up), (1, 0, 0))
    forward = unit(np.cross(left, up), (0, 0, 1))
    return np.column_stack((left, up, forward))


def segment_basis(left, up):
    """An anatomical frame; hip and shoulder planes are independent measurements."""
    up = unit(up)
    left = unit(left - up * (left @ up), (1, 0, 0))
    return np.column_stack((left, up, unit(np.cross(left, up), (0, 0, 1))))


def bend_rotation(
    rest_direction, direction, bend, fallback, previous=None, dt=1 / 30, rest_pole=(0.0, 0.0, 1.0)
):
    """Resolve segment roll from a measured bending plane or explicit pole prior.

    A straight limb has no observed bending plane. Transport the previous frame
    (initially its parent) while preserving aim. Forearm pronation is unobserved.
    """
    a, b = unit(rest_direction), unit(direction)
    pole = bend - b * (bend @ b)
    ref = np.array(rest_pole)
    ref = unit(ref - a * (ref @ a))
    transported = swing_rotation((previous if previous is not None else fallback) @ a, b) @ (
        previous if previous is not None else fallback
    )
    old_pole = transported @ ref
    if np.linalg.norm(pole) < 0.035:
        pole = old_pole
    else:
        pole = unit(pole)
        if previous is not None:
            # Keep the exactly observed aim. Only regularize inferred axial
            # twist: its plane becomes ill-conditioned near full extension.
            angle = np.arctan2(b @ np.cross(old_pole, pole), old_pole @ pole)
            angle = float(np.clip(angle, -10 * dt, 10 * dt))
            pole = old_pole * np.cos(angle) + np.cross(b, old_pole) * np.sin(angle)
    return (
        np.column_stack((b, pole, np.cross(b, pole)))
        @ np.column_stack((a, ref, np.cross(a, ref))).T
    )


class Retargeter:
    """Fixed target lengths; FK swing mapping followed by optional planted-foot IK.

    Only joint positions are observed, so axial wrist/forearm twist is not
    measured. Bend-plane and continuity priors resolve the remaining axial DOF.
    """

    def __init__(self, source_rest, profile="standard", foot_lock=True, target_rest=None):
        self.source_rest = np.asarray(source_rest)
        self.rest = (
            rest_pose(profile) if target_rest is None else np.asarray(target_rest, dtype=float)
        )
        if self.rest.shape != (19, 3) or not np.isfinite(self.rest).all():
            raise ValueError("目标骨架必须是 19 × 3 个有限的米制坐标")
        if np.any(bone_lengths(self.rest) < 0.005) or not 0.2 < self.rest[0, 1] < 2.5:
            raise ValueError("目标骨架的骨长或骨盆高度不合理")
        self.foot_lock = foot_lock
        self.previous_feet = None
        self.anchors = {}
        self.contact_state = [False, False]
        self.anchor_weights = [0.0, 0.0]
        self.previous_quaternions = None
        self.previous_rotations = None
        self.ground_correction = None
        self.limb_rest_poles = {}
        for start in (5, 8, 11, 15):
            upper = unit(self.rest[start + 1] - self.rest[start])
            lower = self.rest[start + 2] - self.rest[start + 1]
            pole = lower - upper * (lower @ upper)
            # The observed pole is the LOWER segment projected off the upper
            # segment, not the direction in which the knee points. A forward
            # knee therefore has a backward pole. Using +Z for both elbows
            # and knees turns a bent thigh inside out even when FK is exact.
            self.limb_rest_poles[start] = unit(pole, (0, 0, -1) if start in (11, 15) else (0, 0, 1))

    def process(self, source, dt):
        offsets = self.rest.copy()
        for parent, child in EDGES:
            offsets[child] -= self.rest[parent]
        hip_left = source[11] - source[15]
        shoulder_left = source[5] - source[8]
        rotations = np.repeat(np.eye(3)[None], len(JOINTS), axis=0)
        rotations[0] = segment_basis(hip_left, source[1] - source[0])
        rotations[1] = segment_basis(unit(hip_left) + unit(shoulder_left), source[2] - source[1])
        rotations[2] = segment_basis(shoulder_left, source[3] - source[2])
        rotations[3] = segment_basis(shoulder_left, source[4] - source[3])
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
            if start in (5, 8, 11, 15):
                rotations[start] = bend_rotation(
                    offsets[end],
                    source[end] - source[start],
                    source[end + 1] - source[end],
                    parent_rotation,
                    None if self.previous_rotations is None else self.previous_rotations[start],
                    dt,
                    rest_pole=self.limb_rest_poles[start],
                )
            elif start in (13, 17):
                # Toe direction observes pitch/yaw; foot roll is ambiguous.
                # Use continuous floor-up roll, never a swinging knee's axis.
                rotations[start] = bend_rotation(
                    offsets[end],
                    source[end] - source[start],
                    np.array([0.0, 1.0, 0.0]),
                    parent_rotation,
                    None if self.previous_rotations is None else self.previous_rotations[start],
                    dt,
                    rest_pole=(0.0, 1.0, 0.0),
                )
            else:
                rotations[start] = (
                    swing_rotation(rest_direction, source[end] - source[start]) @ parent_rotation
                )
        for terminal in (4, 7, 10, 14, 18):
            rotations[terminal] = rotations[PARENTS[terminal]]
        points = np.zeros_like(source)
        source_legs = np.mean(
            [
                np.linalg.norm(self.source_rest[k] - self.source_rest[h])
                + np.linalg.norm(self.source_rest[a] - self.source_rest[k])
                for h, k, a in ((11, 12, 13), (15, 16, 17))
            ]
        )
        target_legs = np.mean(
            [
                np.linalg.norm(offsets[k]) + np.linalg.norm(offsets[a])
                for k, a in ((12, 13), (16, 17))
            ]
        )
        ratio = target_legs / source_legs
        points[0] = self.rest[0] + (source[0] - self.source_rest[0]) * ratio
        for parent, child in EDGES:
            points[child] = points[parent] + rotations[parent] @ offsets[child]
        # Preserve floor contact for different proportions even during a pivot:
        # vertical grounding is distinct from locking a stationary foot in XZ.
        if self.foot_lock:
            altitude = source[[13, 17], 1] - self.source_rest[[13, 17], 1]
            fade = np.clip((altitude - 0.025) / 0.12, 0, 1)
            weight = 1 - fade * fade * (3 - 2 * fade)
            errors = self.rest[[13, 17], 1] + altitude * ratio - points[[13, 17], 1]
            correction = float(weight @ errors / max(weight.sum(), 1e-9))
            correction = float(np.clip(correction, -0.35, 0.35))
            if self.ground_correction is None:
                self.ground_correction = correction
            else:
                change = (correction - self.ground_correction) * (1 - np.exp(-dt / 0.10))
                self.ground_correction += float(np.clip(change, -0.6 * dt, 0.6 * dt))
            points[:, 1] += self.ground_correction
        contacts = [False, False]
        feet = source[[13, 17]].copy()
        if self.foot_lock and self.previous_feet is not None:
            for side, (hip, knee, ankle, toe) in enumerate(((11, 12, 13, 14), (15, 16, 17, 18))):
                speed = np.linalg.norm(feet[side] - self.previous_feet[side]) / max(dt, 1e-3)
                near_ground = source[ankle, 1] < self.source_rest[ankle, 1] + 0.07
                if self.contact_state[side]:
                    self.contact_state[side] = (
                        source[ankle, 1] < self.source_rest[ankle, 1] + 0.095 and speed < 0.4
                    )
                else:
                    self.contact_state[side] = near_ground and speed < 0.22
                active = self.contact_state[side]
                # Hysteresis plus a short weight ramp avoids snapping at every
                # noisy velocity threshold crossing; a lifted/pivoting foot releases.
                self.anchor_weights[side] = float(
                    np.clip(self.anchor_weights[side] + dt / (0.08 if active else -0.12), 0, 1)
                )
                if active:
                    self.anchors.setdefault(side, points[ankle].copy())
                if side in self.anchors and self.anchor_weights[side] > 0:
                    anchor = self.anchors[side]
                    anchor[1] = self.rest[ankle, 1]
                    weight = self.anchor_weights[side]
                    weight = weight * weight * (3 - 2 * weight)
                    target = points[ankle] * (1 - weight) + anchor * weight
                    k, a = two_bone_ik(
                        points[hip],
                        target,
                        np.linalg.norm(offsets[knee]),
                        np.linalg.norm(offsets[ankle]),
                        leg_ik_hint(
                            points[hip],
                            points[knee],
                            points[ankle],
                            target,
                            -rotations[hip] @ self.limb_rest_poles[hip],
                        ),
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
                    contacts[side] = bool(active and weight > 0.5)
                else:
                    self.anchors.pop(side, None)
        if self.foot_lock:
            # A fast swing can be too fast for a planted-foot lock but must not
            # tunnel through the floor. Correct that leg with fixed-length IK,
            # rather than abruptly lifting the pelvis and the other leg.
            for hip, knee, ankle, toe in ((11, 12, 13, 14), (15, 16, 17, 18)):
                floor = max(0.025, self.rest[ankle, 1] - 0.015)
                if points[ankle, 1] < floor:
                    target = points[ankle].copy()
                    target[1] = floor
                    k, a = two_bone_ik(
                        points[hip],
                        target,
                        np.linalg.norm(offsets[knee]),
                        np.linalg.norm(offsets[ankle]),
                        leg_ik_hint(
                            points[hip],
                            points[knee],
                            points[ankle],
                            target,
                            -rotations[hip] @ self.limb_rest_poles[hip],
                        ),
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
        self.previous_feet = feet
        quaternions = []
        for i, parent in enumerate(PARENTS):
            local = rotations[i] if parent < 0 else rotations[parent].T @ rotations[i]
            q = quaternion(local)
            if self.previous_quaternions is not None and q @ self.previous_quaternions[i] < 0:
                q = -q
            quaternions.append(q)
        self.previous_quaternions = np.array(quaternions)
        self.previous_rotations = rotations.copy()
        return points, self.previous_quaternions, contacts
