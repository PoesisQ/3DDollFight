"""Gemini 2 -> body + hand skeleton -> the same UDP ports Unity already reads.

    tools\\hand_tracking\\.venv\\Scripts\\python.exe tools\\gemini_tracking\\run.py --preview

Body goes to 7001 (and a copy to 7012 for the standalone hand tracker), hands
go to 7011.  Nothing in the Unity project needs to change; the receiver only
sees the Astra wire format it was written for.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import cv2
import hands
import numpy as np
import sender
from body_pose import BodySolver, PoseDetector, calibration_issue
from gemini_camera import GeminiCamera

MODELS = Path(__file__).resolve().parent / "models"
POSE_MODELS = {
    "full": MODELS / "pose_landmarker_full.task",
    "lite": MODELS / "pose_landmarker_lite.task",
}

# How long the preview keeps drawing the last solved body while the pose
# detector is between frames. Body detection runs every ``--pose-every``
# frames, so without this the overlay is only drawn on those frames and blinks
# at half the camera rate.
PREVIEW_HOLD = 0.5

# Astra's 19 joints, drawn the way the skeleton actually connects.
BONES = (
    (0, 18),
    (18, 1),
    (1, 2),
    (2, 3),
    (3, 16),
    (16, 4),
    (1, 5),
    (5, 6),
    (6, 17),
    (17, 7),
    (1, 8),
    (8, 9),
    (9, 10),
    (10, 11),
    (11, 12),
    (9, 13),
    (13, 14),
    (14, 15),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini 2 body + hand tracking for DollFight")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--body-port", type=int, default=7001)
    parser.add_argument("--mirror-port", type=int, default=7012)
    parser.add_argument("--hand-port", type=int, default=7011)
    parser.add_argument("--serial", default=None, help="pick a camera by serial number")
    parser.add_argument("--no-body", action="store_true")
    parser.add_argument("--no-hands", action="store_true")
    parser.add_argument(
        "--preview", action="store_true", default=True, help="显示摄像头画面（默认开启）"
    )
    parser.add_argument("--no-preview", action="store_true", help="不打开预览窗口")
    parser.add_argument(
        "--no-skeleton",
        action="store_true",
        help="预览只显示摄像头画面，不画骨架（窗口里按 s 也可以随时切换）",
    )
    parser.add_argument("--max-poses", type=int, default=1, help="1 = fastest; 2 for two players")
    parser.add_argument("--pose-model", choices=("full", "lite"), default="full")
    parser.add_argument("--pose-confidence", type=float, default=0.4)
    parser.add_argument("--hand-confidence", type=float, default=0.5)
    parser.add_argument("--smoothing", type=float, default=10.0, help="0 disables")
    parser.add_argument(
        "--pose-every", type=int, default=2, help="body every N frames; hands run on all"
    )
    parser.add_argument("--no-roi", action="store_true", help="track hands on the full frame")
    parser.add_argument("--color", default="1280x720")
    return parser.parse_args()


def held_for_preview(bodies, held, held_at: float, now: float, hold: float = PREVIEW_HOLD):
    """``(drawn, held, held_at)`` - what the preview overlay should draw.

    The body runs on one frame in ``--pose-every`` and the hands on all of
    them, so the frames in between have no solve at all.  Drawing those as "no
    skeleton" blinks the overlay at half the camera rate, which is what "the
    skeleton keeps flashing" was.  Hold the last good solve instead: while the
    person is there the skeleton stays on screen every frame, and it goes away
    once the solves stop agreeing that somebody is in front of the camera.
    """
    if bodies:
        return bodies, bodies, now
    if held and 0.0 <= now - held_at <= hold:
        return held, held, held_at
    return [], held, held_at


def draw(
    frame,
    bodies,
    hand_runner,
    fps: float,
    depth_ratio: float,
    note: str | None = None,
    skeleton: bool = True,
) -> np.ndarray:
    canvas = frame.bgr.copy()
    if skeleton:
        for body in bodies:
            for a, b in BONES:
                if body.status[a] and body.status[b]:
                    pa = tuple(np.round(body.screen[a]).astype(int))
                    pb = tuple(np.round(body.screen[b]).astype(int))
                    cv2.line(canvas, pa, pb, (0, 220, 0), 2)
            for index in range(19):
                if body.status[index]:
                    centre = tuple(np.round(body.screen[index]).astype(int))
                    colour = (0, 0, 255) if index in (4, 7) else (0, 255, 255)
                    cv2.circle(canvas, centre, 4, colour, -1)
            hip = body.screen[9]
            cv2.putText(
                canvas,
                f"id {body.body_id}  {body.joints[9][2] / 1000:.1f} m",
                (int(hip[0]) - 40, int(hip[1]) + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
            )
    hand_overlay = getattr(hand_runner, "last_detected", []) if (hand_runner and skeleton) else []
    for hand in hand_overlay:
        if hand.get("screen") is None:
            continue
        for x, y in hand["screen"]:
            point = (int(x * canvas.shape[1]), int(y * canvas.shape[0]))
            cv2.circle(canvas, point, 2, (255, 160, 0), -1)
        label = hands.palm_facing(hand)
        if label in ("palm", "back"):
            point = (
                int(np.mean(hand["screen"][:, 0]) * canvas.shape[1]),
                int(np.max(hand["screen"][:, 1]) * canvas.shape[0]) + 22,
            )
            side = "L" if hand.get("side") == "Left" else "R"
            cv2.putText(
                canvas,
                f"{side} {label}",
                point,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )
    facing = [
        ("L" if hand.get("side") == "Left" else "R") + ":" + hands.palm_facing(hand)
        for hand in getattr(hand_runner, "last_detected", [])
        if hand_runner
    ]
    cv2.putText(
        canvas,
        f"{fps:4.1f} fps   bodies={len(bodies)}   depth={depth_ratio * 100:.0f}%",
        (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )
    if note:
        colour = (0, 220, 0) if note.startswith("可校准") else (0, 0, 255)
        cv2.putText(
            canvas,
            note,
            (10, 58),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            colour,
            2,
        )
    if facing:
        cv2.putText(
            canvas,
            "hand facing: " + "  ".join(facing),
            (10, 86),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
        )
    return canvas


def main() -> int:
    args = parse_args()
    show_preview = args.preview and not args.no_preview
    width, height = (int(v) for v in args.color.lower().split("x"))

    camera = GeminiCamera(serial=args.serial, color_size=(width, height))
    camera.start()
    print(f"Gemini 已启动：彩色 {width}x{height}，深度对齐到彩色。")

    pose = None
    if not args.no_body:
        model = POSE_MODELS[args.pose_model]
        if not model.is_file():
            raise SystemExit(
                f"缺少姿态模型：{model}\n"
                "下载：https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
                f"pose_landmarker_{args.pose_model}/float16/1/pose_landmarker_{args.pose_model}.task"
            )
        pose = PoseDetector(model, max_poses=args.max_poses, min_confidence=args.pose_confidence)
    solver = BodySolver(smoothing=args.smoothing)

    hand_runner = None
    if not args.no_hands:
        hand_runner = hands.HandRunner(min_confidence=args.hand_confidence, use_roi=not args.no_roi)

    body_sender = sender.UdpSender(args.host, args.body_port) if not args.no_body else None
    mirror_sender = (
        sender.UdpSender(args.host, args.mirror_port)
        if body_sender is not None and args.mirror_port > 0
        else None
    )
    hand_sender = sender.UdpSender(args.host, args.hand_port) if hand_runner else None

    session = f"{os.getpid()}-{int(time.time() * 1000)}"
    sequence = 0
    frame_index = 0
    previous = time.perf_counter()
    fps = 0.0
    last_send = 0.0
    last_report = previous
    previous_hips: dict[int, np.ndarray] = {}
    p1_seen_printed = False
    last_issue: str | None = None
    last_issue_at = 0.0
    ms_read = ms_pose = ms_hands = 0.0
    preview_bodies: list = []
    preview_at = 0.0
    show_skeleton = not args.no_skeleton

    print(
        f"发送：身体 -> {args.host}:{args.body_port}"
        + (f"（镜像 {args.mirror_port}）" if mirror_sender else "")
        + (f"，手部 -> {args.host}:{args.hand_port}" if hand_sender else "")
        + "。Ctrl+C 退出。"
    )

    try:
        while True:
            started = time.perf_counter()
            frame = camera.read()
            if frame is None:
                continue
            ms_read = 0.85 * ms_read + 0.15 * (time.perf_counter() - started) * 1000.0
            now = time.perf_counter()
            delta = max(1e-3, now - previous)
            previous = now
            fps = fps * 0.9 + (1.0 / delta) * 0.1
            rgb = frame.bgr[:, :, ::-1]

            bodies = []
            if pose is not None and frame_index % max(1, args.pose_every) == 0:
                posed = time.perf_counter()
                result = pose.detect(rgb, int(now * 1000))
                ms_pose = 0.85 * ms_pose + 0.15 * (time.perf_counter() - posed) * 1000.0
                for index, landmarks in enumerate(result.pose_landmarks or []):
                    body = solver.solve(landmarks, frame, index + 1, now)
                    if body is not None:
                        bodies.append(body)
                bodies = sender.sort_bodies(bodies, previous_hips)
                previous_hips = {body.body_id: body.joints[9].copy() for body in bodies}
                if bodies:
                    preview_bodies, preview_at = bodies, now

            # The body runs on every other frame and the hands on all of them,
            # so half the frames have no solve at all. The preview keeps the
            # last one rather than going blank (see `held_for_preview`).
            shown, preview_bodies, preview_at = held_for_preview(
                bodies, preview_bodies, preview_at, now
            )

            entries = []
            if hand_runner is not None:
                primary = shown[0] if shown else None
                handed = time.perf_counter()
                entries = hand_runner.process(rgb, primary, now, delta)
                ms_hands = 0.85 * ms_hands + 0.15 * (time.perf_counter() - handed) * 1000.0

            # The same verdict the Unity panel will print.  A body can be
            # perfectly tracked here and still be refused there, and until now
            # that looked exactly like "the avatar does not move".
            issue = calibration_issue(bodies[0]) if bodies else None
            if bodies and issue != last_issue and now - last_issue_at > 1.5:
                last_issue = issue
                last_issue_at = now
                print("Unity 校准：" + (issue if issue else "通过"))

            if body_sender is not None and bodies:
                payload = sender.body_packet(
                    bodies, sequence, frame.sequence, session, int(now * 1000)
                )
                body_sender.send(payload)
                if mirror_sender is not None:
                    mirror_sender.send(payload)
                if not p1_seen_printed:
                    p1_seen_printed = True
                    print(
                        f"已识别到 {len(bodies)} 人；P1 髋部距离 "
                        f"{bodies[0].joints[9][2] / 1000:.2f} m。"
                    )
            if hand_sender is not None and (entries or now - last_send > 0.2):
                hand_sender.send(hands.protocol.encode(session, sequence, int(now * 1000), entries))
                last_send = now

            if show_preview:
                ratio = float(np.count_nonzero(frame.depth_mm)) / max(1, frame.depth_mm.size)
                note = None
                if shown:
                    distance = shown[0].joints[9][2] / 1000.0
                    held_issue = calibration_issue(shown[0])
                    if held_issue is not None:
                        note = f"Unity 会拒绝：{held_issue}"
                    elif distance < 1.6:
                        note = f"可校准  {distance:.2f} m  请退到 2.5 m 左右，否则 T 字手臂出画"
                    else:
                        note = f"可校准  {distance:.2f} m"
                canvas = draw(frame, shown, hand_runner, fps, ratio, note, skeleton=show_skeleton)
                # A 1280x720 imshow costs several milliseconds per frame and
                # blocks the loop; half size is plenty to see the skeleton.
                if canvas.shape[1] > 1100:
                    canvas = cv2.resize(
                        canvas,
                        (canvas.shape[1] // 2, canvas.shape[0] // 2),
                        interpolation=cv2.INTER_AREA,
                    )
                cv2.imshow("Gemini tracking", canvas)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                if key == ord("s"):
                    show_skeleton = not show_skeleton
                    print("骨架：" + ("显示" if show_skeleton else "已隐藏"))

            if now - last_report > 2.0:
                last_report = now
                ratio = float(np.count_nonzero(frame.depth_mm)) / max(1, frame.depth_mm.size)
                torso = shown[0].joints[9][2] / 1000.0 if shown else 0.0
                print(
                    f"{fps:4.1f} fps  bodies={len(shown)}  hands={len(entries)}  "
                    f"depth={ratio * 100:4.1f}%  torso={torso:4.2f} m"
                )
                print(
                    f"  耗时：采集 {ms_read:.0f} ms | 身体 {ms_pose:.0f} ms | "
                    f"手部 {ms_hands:.0f} ms"
                )
                if entries:
                    surfaces = "  ".join(
                        ("左" if hand.get("side") == "Left" else "右")
                        + "手="
                        + {"palm": "掌心", "back": "掌背", "edge": "侧对"}.get(
                            hands.palm_facing(hand), "未知"
                        )
                        for hand in hand_runner.last_detected
                    )
                    print(f"  画面所见掌面：{surfaces}（应与你自己的手一致）")
                if ratio < 0.01:
                    print(
                        "  深度几乎全为 0：相机可能正对 15cm 以内的物体/镜头被挡，"
                        "或场景太远超出有效范围。"
                    )
                if not shown:
                    print("  画面里没有完整人体：退到 2–2.5 m，让上半身完整入镜。")
                elif shown[0].joints[9][2] < 1600.0:
                    print("  距离太近：T 字手臂会出画，请退到 2–2.5 m。")

            frame_index += 1
            sequence += 1
    except KeyboardInterrupt:
        print("\n停止。")
    finally:
        camera.stop()
        if pose is not None:
            pose.close()
        if hand_runner is not None:
            hand_runner.close()
        for sock in (body_sender, mirror_sender, hand_sender):
            if sock is not None:
                sock.close()
        if show_preview:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
