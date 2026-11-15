"""Quick probe: does pyorbbecsdk see the Gemini 2 and can we align depth to colour?

Run with the hand-tracking virtual environment:

    tools\\hand_tracking\\.venv\\Scripts\\python.exe tools\\gemini_tracking\\probe.py
"""

from __future__ import annotations

import sys
import time

import cv2
import numpy as np


def color_to_bgr(frame) -> np.ndarray:
    from pyorbbecsdk import OBFormat

    width = frame.get_width()
    height = frame.get_height()
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    fmt = frame.get_format()
    if fmt == OBFormat.RGB:
        return cv2.cvtColor(data.reshape(height, width, 3), cv2.COLOR_RGB2BGR)
    if fmt == OBFormat.BGR:
        return data.reshape(height, width, 3).copy()
    if fmt == OBFormat.YUYV:
        return cv2.cvtColor(data.reshape(height, width, 2), cv2.COLOR_YUV2BGR_YUYV)
    if fmt == OBFormat.MJPG:
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("MJPG decode failed")
        return image
    raise RuntimeError(f"unsupported colour format {fmt}")


def main() -> int:
    try:
        from pyorbbecsdk import (
            AlignFilter,
            Config,
            Context,
            OBSensorType,
            OBStreamType,
            Pipeline,
        )
    except Exception as exc:  # pragma: no cover - probe only
        print(f"pyorbbecsdk import failed: {exc}")
        return 1

    context = Context()
    devices = context.query_devices()
    print(f"devices: {devices.get_count()}")
    if devices.get_count() == 0:
        print("no Orbbec device found")
        return 3
    device = devices.get_device_by_index(0)
    info = device.get_device_info()
    print(
        f"  name={info.get_name()} pid=0x{info.get_pid():04x} "
        f"sn={info.get_serial_number()} fw={info.get_firmware_version()}"
    )

    pipeline = Pipeline(device)
    config = Config()
    color_profiles = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
    depth_profiles = pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
    print("colour modes:")
    for i in range(color_profiles.get_count()):
        p = color_profiles.get_stream_profile_by_index(i).as_video_stream_profile()
        print(f"  {p.get_width()}x{p.get_height()}@{p.get_fps()} {p.get_format()}")
    print("depth modes:")
    for i in range(depth_profiles.get_count()):
        p = depth_profiles.get_stream_profile_by_index(i).as_video_stream_profile()
        print(f"  {p.get_width()}x{p.get_height()}@{p.get_fps()} {p.get_format()}")

    color_profile = color_profiles.get_default_video_stream_profile()
    depth_profile = depth_profiles.get_default_video_stream_profile()
    print(
        f"colour default: {color_profile.get_width()}x{color_profile.get_height()}"
        f"@{color_profile.get_fps()} {color_profile.get_format()}"
    )
    print(
        f"depth  default: {depth_profile.get_width()}x{depth_profile.get_height()}"
        f"@{depth_profile.get_fps()} {depth_profile.get_format()}"
    )

    config.enable_stream(color_profile)
    config.enable_stream(depth_profile)
    pipeline.start(config)

    align = AlignFilter(OBStreamType.COLOR_STREAM)
    frames = None
    started = time.perf_counter()
    got = 0
    for _ in range(90):
        frame_set = pipeline.wait_for_frames(1000)
        if frame_set is None:
            continue
        aligned = align.process(frame_set)
        if aligned is None:
            continue
        color = aligned.get_color_frame()
        depth = aligned.get_depth_frame()
        if color is None or depth is None:
            continue
        got += 1
        if frames is None:
            frames = (color, depth)
    elapsed = time.perf_counter() - started
    print(f"aligned frame sets: {got} in {elapsed:.2f}s ({got / elapsed:.1f} fps)")

    if frames is None:
        print("no aligned frames")
        pipeline.stop()
        return 2

    color, depth = frames
    bgr = color_to_bgr(color)
    depth_width = depth.get_width()
    depth_height = depth.get_height()
    depth_data = np.frombuffer(depth.get_data(), dtype=np.uint16).reshape(depth_height, depth_width)
    scale = depth.get_depth_scale()
    valid = depth_data[depth_data > 0]
    print(
        f"aligned colour {bgr.shape[1]}x{bgr.shape[0]}, depth {depth_width}x{depth_height}, "
        f"scale {scale:.4f} mm/unit"
    )
    if valid.size:
        print(
            f"depth range in view: {valid.min() * scale:.0f}..{valid.max() * scale:.0f} mm, "
            f"valid {valid.size / depth_data.size * 100:.1f}%"
        )

    intrinsic = color.get_stream_profile().get_intrinsic()
    distortion = color.get_stream_profile().get_distortion()
    print(
        f"colour intrinsics: fx={intrinsic.fx:.2f} fy={intrinsic.fy:.2f} "
        f"cx={intrinsic.cx:.2f} cy={intrinsic.cy:.2f} "
        f"{intrinsic.width}x{intrinsic.height}"
    )
    if distortion is not None:
        print(
            f"distortion: k1={distortion.k1:.4f} k2={distortion.k2:.4f} "
            f"k3={distortion.k3:.4f} p1={distortion.p1:.4f} p2={distortion.p2:.4f}"
        )

    cv2.imwrite("tmp/gemini_color.png", bgr)
    preview = np.clip(depth_data.astype(np.float32) * scale / 5000.0 * 255, 0, 255)
    cv2.imwrite("tmp/gemini_depth.png", preview.astype(np.uint8))
    print("wrote tmp/gemini_color.png and tmp/gemini_depth.png")

    pipeline.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
