"""Gemini 2 capture: colour + depth aligned to colour, in millimetres.

This is the piece the Astra bridge used to provide.  The rest of the tool only
sees :class:`Frame`, so the tracking code has no idea which camera it is on.

Alignment is done by the camera-side ``AlignFilter``: every depth pixel ends up
in the colour image's grid, which is what lets a MediaPipe landmark be turned
into a metric 3D point by reading one depth sample.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Frame:
    bgr: np.ndarray
    depth_mm: np.ndarray
    fx: float
    fy: float
    cx: float
    cy: float
    timestamp_ms: int
    sequence: int

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])

    def depth_at(self, u: float, v: float, window: int = 2) -> float:
        """Median depth in a small window, in mm; 0.0 when nothing is valid.

        A single pixel is too noisy on a 1280x800 stereo map, and the median
        survives the edge pixels around a limb that mix person and background.
        """
        height, width = self.depth_mm.shape
        x = int(round(u))
        y = int(round(v))
        if not (0 <= x < width and 0 <= y < height):
            return 0.0
        x0, x1 = max(0, x - window), min(width, x + window + 1)
        y0, y1 = max(0, y - window), min(height, y + window + 1)
        patch = self.depth_mm[y0:y1, x0:x1]
        valid = patch[patch > 0.0]
        if valid.size < 3:
            return 0.0
        return float(np.median(valid))

    def project(self, x_mm: float, y_mm: float, z_mm: float) -> tuple[float, float]:
        """Camera-frame millimetres to colour pixels."""
        if z_mm <= 0.0:
            return 0.0, 0.0
        return (
            self.fx * x_mm / z_mm + self.cx,
            self.fy * y_mm / z_mm + self.cy,
        )


def _decode_color(frame) -> np.ndarray:
    from pyorbbecsdk import OBFormat

    width = frame.get_width()
    height = frame.get_height()
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    fmt = frame.get_format()
    if fmt == OBFormat.MJPG:
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("Gemini colour frame failed to decode (MJPG)")
        return image
    if fmt == OBFormat.RGB:
        return cv2.cvtColor(data.reshape(height, width, 3), cv2.COLOR_RGB2BGR)
    if fmt == OBFormat.BGR:
        return data.reshape(height, width, 3).copy()
    if fmt == OBFormat.YUYV:
        return cv2.cvtColor(data.reshape(height, width, 2), cv2.COLOR_YUV2BGR_YUYV)
    raise RuntimeError(f"Unsupported Gemini colour format: {fmt}")


class GeminiCamera:
    """Owns the device.  One process at a time, same rule as the Astra SDK."""

    def __init__(self, serial: str | None = None, color_size: tuple[int, int] = (1280, 720)):
        self.serial = serial
        self.color_size = color_size
        self._pipeline = None
        self._align = None
        self._intrinsics = None

    def start(self) -> None:
        from pyorbbecsdk import (
            AlignFilter,
            Config,
            Context,
            OBSensorType,
            OBStreamType,
            Pipeline,
        )

        context = Context()
        devices = context.query_devices()
        if devices.get_count() == 0:
            raise RuntimeError(
                "没有找到 Orbbec 相机。确认 Gemini 2 插在 USB 3.0 口上，"
                "并且没有别的程序（Orbbec Viewer / Unity 面板）占用它。"
            )
        device = None
        for index in range(devices.get_count()):
            candidate = devices.get_device_by_index(index)
            if (
                self.serial is None
                or candidate.get_device_info().get_serial_number() == self.serial
            ):
                device = candidate
                break
        if device is None:
            raise RuntimeError(f"没有找到序列号 {self.serial} 的相机")

        self._pipeline = Pipeline(device)
        config = Config()
        color_profiles = self._pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
        color_profile = self._pick_color_profile(color_profiles)
        depth_profile = self._pipeline.get_stream_profile_list(
            OBSensorType.DEPTH_SENSOR
        ).get_default_video_stream_profile()
        config.enable_stream(color_profile)
        config.enable_stream(depth_profile)
        self._pipeline.start(config)
        self._align = AlignFilter(OBStreamType.COLOR_STREAM)

        intrinsic = color_profile.get_intrinsic()
        self._intrinsics = (intrinsic.fx, intrinsic.fy, intrinsic.cx, intrinsic.cy)
        self._sequence = 0

    def _pick_color_profile(self, profiles):
        """Prefer the requested size, else the default; MJPG keeps USB 3 happy."""
        target_w, target_h = self.color_size
        best = None
        for index in range(profiles.get_count()):
            profile = profiles.get_stream_profile_by_index(index).as_video_stream_profile()
            if (profile.get_width(), profile.get_height()) != (target_w, target_h):
                continue
            if profile.get_fps() != 30:
                continue
            if str(profile.get_format()).endswith("MJPG"):
                return profile
            best = best or profile
        if best is not None:
            return best
        return profiles.get_default_video_stream_profile()

    def read(self, timeout_ms: int = 1000) -> Frame | None:
        from pyorbbecsdk import OBFormat

        assert self._pipeline is not None, "call start() first"
        frame_set = self._pipeline.wait_for_frames(timeout_ms)
        if frame_set is None:
            return None
        aligned = self._align.process(frame_set) if self._align is not None else frame_set
        if aligned is None:
            return None
        color_frame = aligned.get_color_frame()
        depth_frame = aligned.get_depth_frame()
        if color_frame is None or depth_frame is None:
            return None

        bgr = _decode_color(color_frame)
        depth = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
        depth = depth.reshape(depth_frame.get_height(), depth_frame.get_width())
        scale = float(depth_frame.get_depth_scale())
        depth_mm = depth.astype(np.float32) * scale
        if depth_mm.shape != bgr.shape[:2]:
            depth_mm = cv2.resize(
                depth_mm, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST
            )
        if depth_frame.get_format() != OBFormat.Y16:
            # An unaligned RLE frame would decode here as garbage; the align
            # filter normally hands back Y16, so treat anything else as a
            # broken frame rather than feeding noise to the pose mapper.
            if float(depth_mm.max()) <= 0.0:
                return None

        fx, fy, cx, cy = self._intrinsics
        self._sequence += 1
        return Frame(
            bgr=bgr,
            depth_mm=depth_mm,
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            timestamp_ms=int(frame_set.get_timestamp_us() // 1000)
            if hasattr(frame_set, "get_timestamp_us")
            else 0,
            sequence=self._sequence,
        )

    def stop(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            finally:
                self._pipeline = None
                self._align = None
