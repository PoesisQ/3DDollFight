"""MediaPipe pose -> the 19 Astra joints the Unity receiver already understands.

The Astra SDK gave us joints for free; Gemini does not.  This module rebuilds
them from the colour image and the aligned depth map:

1. MediaPipe finds 33 body landmarks in the 1280x720 colour image.
2. Each landmark is turned into a metric point by sampling the aligned depth at
   its pixel and back-projecting with the colour intrinsics.
3. Those 33 points are folded into Astra's 19 joints, in Astra's own convention
   (x = the person's right, y = up, z = away from the camera, millimetres), so
   the Unity side needs no change at all.
4. Frames where a joint's own depth is missing borrow a neighbour's depth
   (a hand uses the wrist, a foot uses the knee), which is what keeps the
   skeleton from collapsing when a limb is occluded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

JOINT_COUNT = 19
HEAD = 0
SHOULDER_SPINE = 1
LEFT_SHOULDER = 2
LEFT_ELBOW = 3
LEFT_HAND = 4
RIGHT_SHOULDER = 5
RIGHT_ELBOW = 6
RIGHT_HAND = 7
MID_SPINE = 8
BASE_SPINE = 9
LEFT_HIP = 10
LEFT_KNEE = 11
LEFT_FOOT = 12
RIGHT_HIP = 13
RIGHT_KNEE = 14
RIGHT_FOOT = 15
LEFT_WRIST = 16
RIGHT_WRIST = 17
NECK = 18

# MediaPipe BlazePose landmark indices.
NOSE = 0
LEFT_EAR = 7
RIGHT_EAR = 8
L_SHOULDER = 11
R_SHOULDER = 12
L_ELBOW = 13
R_ELBOW = 14
L_WRIST = 15
R_WRIST = 16
L_PINKY = 17
R_PINKY = 18
L_INDEX = 19
R_INDEX = 20
L_THUMB = 21
R_THUMB = 22
L_HIP = 23
R_HIP = 24
L_KNEE = 25
R_KNEE = 26
L_ANKLE = 27
R_ANKLE = 28

# joint -> (landmark indices, weights).  Averaging before sampling depth keeps
# the sample on the body instead of on the edge pixel next to it.
SOURCES: dict[int, tuple[tuple[int, ...], tuple[float, ...]]] = {
    HEAD: ((NOSE, LEFT_EAR, RIGHT_EAR), (0.6, 0.2, 0.2)),
    NECK: ((L_SHOULDER, R_SHOULDER), (0.5, 0.5)),
    SHOULDER_SPINE: ((L_SHOULDER, R_SHOULDER), (0.5, 0.5)),
    LEFT_SHOULDER: ((L_SHOULDER,), (1.0,)),
    LEFT_ELBOW: ((L_ELBOW,), (1.0,)),
    LEFT_WRIST: ((L_WRIST,), (1.0,)),
    LEFT_HAND: ((L_PINKY, L_INDEX, L_THUMB), (1 / 3, 1 / 3, 1 / 3)),
    RIGHT_SHOULDER: ((R_SHOULDER,), (1.0,)),
    RIGHT_ELBOW: ((R_ELBOW,), (1.0,)),
    RIGHT_WRIST: ((R_WRIST,), (1.0,)),
    RIGHT_HAND: ((R_PINKY, R_INDEX, R_THUMB), (1 / 3, 1 / 3, 1 / 3)),
    MID_SPINE: ((L_SHOULDER, R_SHOULDER, L_HIP, R_HIP), (0.25,) * 4),
    BASE_SPINE: ((L_HIP, R_HIP), (0.5, 0.5)),
    LEFT_HIP: ((L_HIP,), (1.0,)),
    LEFT_KNEE: ((L_KNEE,), (1.0,)),
    LEFT_FOOT: ((L_ANKLE,), (1.0,)),
    RIGHT_HIP: ((R_HIP,), (1.0,)),
    RIGHT_KNEE: ((R_KNEE,), (1.0,)),
    RIGHT_FOOT: ((R_ANKLE,), (1.0,)),
}

# When a joint has no depth of its own, borrow from the closest joint that has.
DEPTH_FALLBACK: dict[int, tuple[int, ...]] = {
    HEAD: (NECK, SHOULDER_SPINE),
    NECK: (SHOULDER_SPINE, MID_SPINE),
    SHOULDER_SPINE: (MID_SPINE, NECK),
    MID_SPINE: (BASE_SPINE, SHOULDER_SPINE),
    BASE_SPINE: (MID_SPINE,),
    LEFT_SHOULDER: (SHOULDER_SPINE, LEFT_ELBOW),
    RIGHT_SHOULDER: (SHOULDER_SPINE, RIGHT_ELBOW),
    LEFT_ELBOW: (LEFT_SHOULDER, LEFT_WRIST),
    RIGHT_ELBOW: (RIGHT_SHOULDER, RIGHT_WRIST),
    LEFT_WRIST: (LEFT_ELBOW,),
    RIGHT_WRIST: (RIGHT_ELBOW,),
    LEFT_HAND: (LEFT_WRIST, LEFT_ELBOW),
    RIGHT_HAND: (RIGHT_WRIST, RIGHT_ELBOW),
    LEFT_HIP: (BASE_SPINE, LEFT_KNEE),
    RIGHT_HIP: (BASE_SPINE, RIGHT_KNEE),
    LEFT_KNEE: (LEFT_HIP, LEFT_FOOT),
    RIGHT_KNEE: (RIGHT_HIP, RIGHT_FOOT),
    LEFT_FOOT: (LEFT_KNEE,),
    RIGHT_FOOT: (RIGHT_KNEE,),
}

MIN_DEPTH_MM = 120.0
MAX_DEPTH_MM = 10_000.0
# A torso closer than this is someone leaning into the lens (or a face that
# MediaPipe extrapolated into a body), and its joint angles are meaningless.
MIN_HIP_DEPTH_MM = 800.0
# Hip-to-shoulder length of a real person, in millimetres.  Outside this range
# the "body" is a false positive from a poster, a chair, or a cropped frame.
MIN_TORSO_MM = 200.0
MAX_TORSO_MM = 800.0


@dataclass
class Body:
    body_id: int
    joints: np.ndarray  # (19, 3) mm in Astra convention
    status: np.ndarray  # (19,) 1 tracked / 0 untracked
    screen: np.ndarray  # (19, 2) colour pixels, for preview and wrist pairing


def _pixel(landmark, width: int, height: int) -> tuple[float, float]:
    x = min(max(float(landmark.x), 0.0), 1.0) * (width - 1)
    y = min(max(float(landmark.y), 0.0), 1.0) * (height - 1)
    return x, y


def _astra_xyz(camera_mm: np.ndarray) -> np.ndarray:
    """Camera frame (x right, y down, z forward) -> Astra (x person-right, y up)."""
    out = camera_mm.copy()
    out[..., 0] *= -1.0
    out[..., 1] *= -1.0
    return out


# The game refuses to calibrate unless these eight segments have real length.
# Mirrors AstraLivePlayer's segment table (required rows only); keeping a copy
# here lets the tracker say out loud why Unity rejected a frame, instead of
# looking alive while the avatar stands still.
REQUIRED_SEGMENTS = (
    (BASE_SPINE, MID_SPINE),
    (MID_SPINE, SHOULDER_SPINE),
    (SHOULDER_SPINE, NECK),
    (NECK, HEAD),
    (LEFT_SHOULDER, LEFT_ELBOW),
    (LEFT_ELBOW, LEFT_WRIST),
    (RIGHT_SHOULDER, RIGHT_ELBOW),
    (RIGHT_ELBOW, RIGHT_WRIST),
)
MIN_SEGMENT_MM = 10.0

JOINT_NAMES = {
    HEAD: "头",
    SHOULDER_SPINE: "肩部中点",
    LEFT_SHOULDER: "左肩",
    LEFT_ELBOW: "左肘",
    LEFT_HAND: "左手",
    RIGHT_SHOULDER: "右肩",
    RIGHT_ELBOW: "右肘",
    RIGHT_HAND: "右手",
    MID_SPINE: "脊柱中部",
    BASE_SPINE: "髋部中心",
    LEFT_HIP: "左髋",
    LEFT_KNEE: "左膝",
    LEFT_FOOT: "左脚",
    RIGHT_HIP: "右髋",
    RIGHT_KNEE: "右膝",
    RIGHT_FOOT: "右脚",
    LEFT_WRIST: "左腕",
    RIGHT_WRIST: "右腕",
    NECK: "颈",
}


def _rebuild_spine(joints: np.ndarray, screen: np.ndarray, status: np.ndarray) -> None:
    """Put mid-spine and neck on the hip->shoulder axis.

    Averaging the shoulders for both ``SHOULDER_SPINE`` and ``NECK`` would put
    them on the exact same point, and the game's calibration rejects a body
    whose neck and shoulder-spine coincide.  The neck therefore sits above the
    shoulder line, along the torso, and the mid spine halfway down.
    """
    if not (status[BASE_SPINE] and status[SHOULDER_SPINE]):
        return
    base = joints[BASE_SPINE]
    shoulder = joints[SHOULDER_SPINE]
    axis = shoulder - base
    length = float(np.linalg.norm(axis))
    if length < 80.0:
        return
    direction = axis / length
    joints[MID_SPINE] = base + axis * 0.45
    joints[NECK] = shoulder + direction * min(90.0, length * 0.22)
    status[MID_SPINE] = 1
    status[NECK] = 1

    base_screen = screen[BASE_SPINE]
    shoulder_screen = screen[SHOULDER_SPINE]
    screen[MID_SPINE] = base_screen + (shoulder_screen - base_screen) * 0.45
    screen[NECK] = shoulder_screen + (shoulder_screen - base_screen) * 0.22


def calibration_issue(body: Body) -> str | None:
    """Same verdict the Unity panel prints, so both sides agree on a frame."""
    missing = [
        JOINT_NAMES[a] for a, b in REQUIRED_SEGMENTS if not (body.status[a] and body.status[b])
    ]
    if missing:
        return "未追踪：" + "、".join(dict.fromkeys(missing))
    for a, b in REQUIRED_SEGMENTS:
        if float(np.linalg.norm(body.joints[a] - body.joints[b])) < MIN_SEGMENT_MM:
            return f"{JOINT_NAMES[a]}与{JOINT_NAMES[b]}位置过近"
    return None


class PoseDetector:
    def __init__(self, model: Path, max_poses: int = 2, min_confidence: float = 0.4):
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision as mp_vision

        options = mp_vision.PoseLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_poses=max_poses,
            min_pose_detection_confidence=min_confidence,
            min_pose_presence_confidence=min_confidence,
            min_tracking_confidence=min_confidence,
            output_segmentation_masks=False,
        )
        self._landmarker = mp_vision.PoseLandmarker.create_from_options(options)
        import mediapipe as mp

        self._mp = mp

    def detect(self, rgb: np.ndarray, timestamp_ms: int):
        image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb),
        )
        return self._landmarker.detect_for_video(image, timestamp_ms)

    def close(self) -> None:
        self._landmarker.close()


@dataclass
class _Smoother:
    """Per-body exponential smoothing, reset when the body jumps."""

    rate: float = 12.0
    joints: np.ndarray | None = field(default=None)
    last_stamp: float = 0.0

    def apply(self, joints: np.ndarray, stamp: float) -> np.ndarray:
        if self.joints is None or joints.shape != self.joints.shape:
            self.joints = joints.copy()
            self.last_stamp = stamp
            return joints
        dt = max(1e-3, stamp - self.last_stamp)
        alpha = 1.0 - math.exp(-self.rate * dt)
        if float(np.abs(joints - self.joints).max()) > 600.0:
            # A different person or a tracking re-acquire: do not drag the old
            # skeleton across the room.
            self.joints = joints.copy()
            self.last_stamp = stamp
            return joints
        self.joints = self.joints + alpha * (joints - self.joints)
        self.last_stamp = stamp
        return self.joints.copy()

    def reset(self) -> None:
        self.joints = None


class BodySolver:
    """Turns one MediaPipe pose into 19 Astra joints in millimetres."""

    def __init__(self, smoothing: float = 12.0, drop_visibility: float = 0.35):
        self.smoothing = smoothing
        self.drop_visibility = drop_visibility
        self._smoothers: dict[int, _Smoother] = {}

    def solve(self, pose, frame, body_id: int, stamp: float) -> Body | None:
        landmarks = pose
        height, width = frame.bgr.shape[:2]
        pixels = np.array([_pixel(lm, width, height) for lm in landmarks], dtype=np.float64)
        visibility = np.array([float(getattr(lm, "visibility", 1.0)) for lm in landmarks])

        # Raw metric position of every landmark that happens to have depth.
        z_all = np.zeros(len(landmarks), dtype=np.float64)
        for index in range(len(landmarks)):
            z_all[index] = frame.depth_at(pixels[index, 0], pixels[index, 1])
        valid = (z_all >= MIN_DEPTH_MM) & (z_all <= MAX_DEPTH_MM)

        joints = np.zeros((JOINT_COUNT, 3), dtype=np.float64)
        status = np.zeros(JOINT_COUNT, dtype=np.int32)
        screen = np.zeros((JOINT_COUNT, 2), dtype=np.float64)
        resolved_z = np.zeros(JOINT_COUNT, dtype=np.float64)

        for joint, (sources, weights) in SOURCES.items():
            u = float(np.dot(pixels[list(sources), 0], weights))
            v = float(np.dot(pixels[list(sources), 1], weights))
            screen[joint] = (u, v)
            z = frame.depth_at(u, v)
            if not (MIN_DEPTH_MM <= z <= MAX_DEPTH_MM):
                usable = [
                    z_all[i] for i, w in zip(sources, weights, strict=True) if valid[i] and w > 0
                ]
                z = float(np.median(usable)) if usable else 0.0
            resolved_z[joint] = z

        # Second pass: borrow a neighbour's depth where this joint still has none.
        for joint in range(JOINT_COUNT):
            if resolved_z[joint] > 0.0:
                continue
            for donor in DEPTH_FALLBACK.get(joint, ()):
                if resolved_z[donor] > 0.0:
                    resolved_z[joint] = resolved_z[donor]
                    break

        if not np.any(resolved_z > 0.0):
            return None

        median_z = float(np.median(resolved_z[resolved_z > 0.0]))
        for joint in range(JOINT_COUNT):
            sources, weights = SOURCES[joint]
            z = resolved_z[joint] if resolved_z[joint] > 0.0 else median_z
            u, v = screen[joint]
            x_mm = (u - frame.cx) * z / frame.fx
            y_mm = (v - frame.cy) * z / frame.fy
            joints[joint] = (x_mm, y_mm, z)
            tracked = (
                z > 0.0
                and float(np.average(visibility[list(sources)], weights=weights))
                >= self.drop_visibility
            )
            status[joint] = 1 if tracked else 0

        joints = _astra_xyz(joints)
        _rebuild_spine(joints, screen, status)
        # The torso has to be real for the skeleton to mean anything; if even
        # the hips have no depth, this frame is not worth sending.
        if status[[BASE_SPINE, MID_SPINE, NECK]].sum() < 2:
            return None
        if float(joints[BASE_SPINE][2]) < MIN_HIP_DEPTH_MM:
            return None
        torso = float(np.linalg.norm(joints[SHOULDER_SPINE] - joints[BASE_SPINE]))
        if not (MIN_TORSO_MM <= torso <= MAX_TORSO_MM):
            return None

        if self.smoothing > 0.0:
            smoother = self._smoothers.setdefault(body_id, _Smoother(self.smoothing))
            joints = smoother.apply(joints, stamp)
        return Body(body_id=body_id, joints=joints, status=status, screen=screen)

    def reset(self) -> None:
        self._smoothers.clear()
