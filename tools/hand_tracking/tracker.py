"""MediaPipe 21-landmark hand detector.

Returns the raw metric landmarks; callers turn them into a hand skeleton
(``skeleton.py``) and, as a fallback, finger curls (``curls.py``).

Uses the MediaPipe Tasks ``HandLandmarker`` (the legacy ``mp.solutions`` package
was removed in 0.10.31). The model file is not stored in Git; fetch it once with
``fetch_model.cmd``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

try:  # keep the geometry module importable on machines without MediaPipe
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision
except ImportError:  # pragma: no cover
    mp = None
    mp_tasks = None
    mp_vision = None

DEFAULT_MODEL = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"


def image_frame(points: np.ndarray, screen) -> np.ndarray:
    """Express MediaPipe's world landmarks in the image's own axes.

    x right, y **down**, z into the scene: the frame ``hand3d`` rebuilds hands
    in and the avatar's hands are driven from. The Tasks API has shipped world
    landmarks in both Y conventions, so the screen landmarks - which always grow
    downward - decide which way round this build is. Flipping Y and Z together
    is a rotation, not a reflection, so the frame stays right-handed and
    ``cross(x, y)`` keeps pointing at the palm rather than at the back of it.

    Y-up output would have been the natural choice for display, but every
    consumer here already speaks the image frame, and a hand frame rotated 180
    degrees about x puts the avatar's wrist exactly backwards.
    """
    if screen is None or len(screen) != len(points) or len(points) < 3:
        return points
    vertical = points[:, 1] - float(np.mean(points[:, 1]))
    downward = screen[:, 1] - float(np.mean(screen[:, 1]))
    if float(np.dot(vertical, downward)) < 0.0:
        return points * np.array([1.0, -1.0, -1.0])
    return points


class HandTracker:
    def __init__(self, model_path: Path | None = None, max_hands: int = 2, detection: float = 0.5,
                 tracking: float = 0.5, mirror_sides: bool = False):
        if mp is None:
            raise RuntimeError("MediaPipe 未安装，请先运行 tools/hand_tracking/install.cmd")
        model = Path(model_path) if model_path else DEFAULT_MODEL
        if not model.exists():
            raise RuntimeError(f"找不到手部模型 {model}，请先运行 fetch_model.cmd")
        self.mirror_sides = mirror_sides
        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=max(1, min(2, max_hands)),
            min_hand_detection_confidence=float(detection),
            min_hand_presence_confidence=float(tracking),
            min_tracking_confidence=float(tracking),
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self._last_timestamp = -1

    def process(self, rgb: np.ndarray, timestamp_ms: int):
        """Return ``[{"side", "score", "points", "screen"}]`` for every hand."""
        if rgb.dtype != np.uint8:
            rgb = rgb.astype(np.uint8)
        # Tasks API demands strictly increasing timestamps.
        stamp = max(int(timestamp_ms), self._last_timestamp + 1)
        self._last_timestamp = stamp
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect_for_video(image, stamp)
        hands = []
        worlds = result.hand_world_landmarks or []
        screens = result.hand_landmarks or []
        handedness = result.handedness or []
        for position, world in enumerate(worlds):
            if position >= len(handedness) or not handedness[position]:
                continue
            category = handedness[position][0]
            side = category.category_name
            if self.mirror_sides:
                side = "Right" if side == "Left" else "Left"
            points = np.array([[p.x, p.y, p.z] for p in world], dtype=np.float64)
            screen = None
            if position < len(screens):
                screen = np.array([[p.x, p.y] for p in screens[position]], dtype=np.float64)
            points = image_frame(points, screen)
            hands.append({
                "side": side,
                "score": float(category.score),
                "points": points,
                "screen": screen,
            })
        return hands

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> HandTracker:
        return self

    def __exit__(self, *_) -> None:
        self.close()
