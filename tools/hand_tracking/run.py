"""Live hand tracking for DollFight.

Reads RGB frames from the Astra bridge's colour feed, turns each detected hand
into a 21-joint skeleton expressed in the wrist's own frame, and sends
``dollfight-hands-3`` datagrams to Unity. The body skeleton mirrored on the
second port tells us which wrist each hand belongs to, so left/right can never
be swapped by a mirrored image.

Typical use, after the bridge has been built:

    python run.py --start-bridge

Stop the sender inside the Unity panel first, because one process owns the Astra
camera at a time.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import curls as curl_module
import hand3d
import numpy as np
import protocol
import skeleton
from bodyfeed import BodyFeed
from feed import ColorFeed, ColorFeedError
from tracker import HandTracker

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = REPO_ROOT / "integrations" / "astra-unity-bridge" / "build/bin/Release"
DEFAULT_BRIDGE = BRIDGE_DIR / "AstraUnityBridge.exe"

# How long a hand has to stay lost before its state is thrown away. The palm's
# width, its tilt and its fingers all take seconds to re-learn, and dropping
# them on the first frame a fist hides behind the body makes the hand twitch
# open and re-lock on every occlusion.
HAND_GRACE = 1.0

# How long the last solved pose is re-sent when a frame cannot be solved. Short
# enough that a hand which really left the frame still goes away, long enough to
# cover the handful of frames a fist or an edge-on palm produces. Not re-sending
# anything is what makes the receiver ease the wrist to its bind pose and back.
#
# Measured on the 2026-11-11 crossed-arms recording: the detector loses *both*
# hands for up to 2.4 seconds while the palms overlap, so 0.4 s of cover ran out
# in the middle of the gesture and the receiver relaxed both hands to the bind
# pose before re-acquiring them - the "it glitches and does the opposite of my
# hand" report. 0.8 s covers the short gaps; the receiver also holds a hand it
# has seen within the last 0.5 s instead of relaxing it, so a longer gap freezes
# the pose that was last tracked rather than snapping it.
HAND_HOLD = 0.8

# Image components (x right, y down, z into the scene) to the receiver's axes
# (x right, y up, z into the scene). A 180 degree turn about x, so the three
# axes stay a right-handed set and ``z == x cross y`` still holds.
WIRE_TO_UNITY = np.array([1.0, -1.0, -1.0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Astra colour -> hand skeleton -> Unity UDP")
    parser.add_argument("--color-port", type=int, default=7005, help="bridge colour TCP port")
    parser.add_argument("--hand-port", type=int, default=7011, help="Unity hand UDP port")
    parser.add_argument(
        "--body-port",
        type=int,
        default=7012,
        help="mirrored body UDP port; 0 disables wrist pairing",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Unity address")
    parser.add_argument(
        "--start-bridge", action="store_true", help="launch AstraUnityBridge with --color-port"
    )
    parser.add_argument(
        "--bridge", type=Path, default=DEFAULT_BRIDGE, help="AstraUnityBridge.exe path"
    )
    parser.add_argument(
        "--license", type=Path, default=None, help="Orbbec body tracking license file"
    )
    parser.add_argument(
        "--mirror",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="swap MediaPipe handedness (Astra colour is not mirrored)",
    )
    parser.add_argument("--preview", action="store_true", help="show a local window with landmarks")
    parser.add_argument(
        "--min-confidence", type=float, default=0.5, help="drop hands below this score"
    )
    return parser.parse_args()


def resolve_license(explicit: Path | None) -> Path | None:
    """Find the body-tracking license the same way the Unity panel does.

    Order: --license, ASTRA_BODY_LICENSE, then $ASTRA_LAB_ENV/astra-body-license.txt.
    The bridge itself only understands --license, so the lookup has to happen here.
    """
    if explicit is not None:
        return explicit
    value = os.environ.get("ASTRA_BODY_LICENSE", "").strip()
    if value:
        candidate = Path(value)
        if candidate.is_file():
            return candidate
        print(f"ASTRA_BODY_LICENSE 指向的文件不存在：{value}")
    lab = os.environ.get("ASTRA_LAB_ENV", "").strip()
    if lab:
        candidate = Path(lab) / "astra-body-license.txt"
        if candidate.is_file():
            return candidate
    return None


def start_bridge(args: argparse.Namespace) -> subprocess.Popen:
    if not args.bridge.exists():
        raise SystemExit(f"找不到发送程序：{args.bridge}\n先运行 Build-Bridge.cmd")

    license_path = resolve_license(args.license)

    def launch(mirror: bool) -> subprocess.Popen:
        command = [str(args.bridge), "--color-port", str(args.color_port)]
        if mirror and args.body_port > 0:
            command += ["--mirror-port", str(args.body_port)]
        if license_path:
            command += ["--license", str(license_path)]
        return subprocess.Popen(command, cwd=str(args.bridge.parent))

    if license_path:
        print(f"使用身体跟踪授权：{license_path}")
    else:
        print("未找到授权文件，按 SDK 内置试用运行（与 Unity「启动摄像头」一致）。")

    process = launch(mirror=True)
    time.sleep(1.5)
    if process.poll() is not None and args.body_port > 0:
        # Older builds do not know --mirror-port. Keep running without wrist
        # pairing instead of failing the whole hand pipeline.
        print(
            "发送程序不支持 --mirror-port（可能是旧构建），本次不镜像身体报文；"
            "重新运行 Build-Bridge.cmd 后左右手配对才会生效。"
        )
        args.body_port = 0
        process = launch(mirror=False)
        time.sleep(1.5)
    if process.poll() is not None:
        raise SystemExit("发送程序启动失败，检查摄像头是否被其他程序占用。")
    return process


def connect_feed(port: int, attempts: int = 40) -> ColorFeed:
    feed = ColorFeed(port=port)
    for _ in range(attempts):
        try:
            feed.connect()
            return feed
        except OSError:
            time.sleep(0.25)
    raise SystemExit(f"连接不上彩色流 127.0.0.1:{port}，确认发送程序已用 --color-port 启动。")


def _screen_x(hand: dict) -> float:
    screen = hand.get("screen")
    if screen is None or len(screen) == 0:
        return 0.5
    return float(np.mean(screen[:, 0]))


def wire_axes(axes) -> list[float]:
    """Flatten the palm frame for the datagram, in the receiver's axes.

    ``hand3d`` builds the frame in image components: x right, y *down*, z into
    the scene. The receiver passes these numbers straight to
    ``Quaternion.LookRotation`` and compares them with a frame it measured on the
    avatar in Unity's world, which is y *up*, z into the scene. So y and z have
    to be flipped on the way out. Both ends were put in one model to settle it:
    leaving the frame unconverted puts the wrist 180 degrees out, which makes the
    avatar show the back of its hand whatever the real palm does, while this
    conversion brings the error to 0 for both hands.

    The 21 joints do not need touching. They live in the hand frame, and a local
    coordinate ``point . axis`` is unchanged when the point and the axis are
    rotated together, so flipping the axes here keeps them valid.
    """
    return [float(v) for axis in axes for v in (axis * WIRE_TO_UNITY)]


def palm_frame(hand: dict):
    """The palm's orientation, straight from MediaPipe's world landmarks.

    These are a learned 3D hand, not a projection of one, so they know how far
    the palm is tipped towards the camera - the one number a single view cannot
    recover from the 2D landmarks. ``hand3d`` used to infer it by comparing the
    palm's width against its length, which needs the hand to have been shown
    flat at least once and is 64 degrees out at the median on the recording
    here, 173 at worst.

    Returns ``None`` when the landmarks are degenerate, and the caller falls
    back to the inferred frame.
    """
    points = np.asarray(hand["points"], dtype=np.float64)
    if points.shape != (skeleton.LANDMARK_COUNT, 3):
        return None
    frame = skeleton.hand_basis(points)
    return None if frame is None else frame[:3]


def palm_millimetres(hand: dict) -> float:
    """Palm length from MediaPipe's world landmarks, for validation only.

    Only the scale is taken from here. The landmarks themselves are the source
    of the palm's orientation now, but their lengths collapse when the palm
    turns, so the number is used to reject frames that cannot be a real hand
    rather than to measure anything.
    """
    points = np.asarray(hand["points"], dtype=np.float64)
    return float(np.linalg.norm(points[skeleton.MIDDLE_MCP] - points[0])) * 1000.0


def palm_facing(hand: dict) -> str:
    """``palm`` / ``back`` / ``edge``, as the 2D landmarks see it.

    ``palm_depth_sign`` says which sign the palm frame's depth has to have; the
    palm normal is ``PALM_SIDE * z``, and a normal pointing along -z (out of the
    scene) is a palm facing the lens. So the product of the two being negative
    is "palm towards the camera", on both hands. Nothing here reads the world
    landmarks - this is the independent opinion the diagnosis needs.

    ASCII because OpenCV's Hershey fonts have no other glyphs.
    """
    screen = hand.get("screen")
    if screen is None:
        return "?"
    along = screen[skeleton.MIDDLE_MCP] - screen[skeleton.WRIST]
    across = screen[skeleton.PINKY_MCP] - screen[skeleton.INDEX_MCP]
    sign = hand3d.palm_depth_sign(across, along)
    if sign == 0.0:
        return "edge"
    return "palm" if sign * hand3d.PALM_SIDE[hand["side"]] < 0.0 else "back"


def split_shared_sides(detected: list[dict]) -> bool:
    """Give two hands different sides when MediaPipe called both the same one.

    One person has one left hand, but on the 2026-11-11 recording the model
    returns two right hands on 228 of 2123 frames - a tenth of them - and
    exactly around the poses this session was about. That frame then carries
    two entries for the right wrist and none for the left: the receiver drives
    the right hand twice and, finding no left hand at all, eases the left wrist
    to its bind pose. It reads as one hand flapping while the other hangs.

    ``assign_sides`` already corrects this from the body's wrists, but it needs
    both wrists to be tracked; when the hands are up in front of the chest that
    is exactly what the body pass tends to lose. This is the same rule it uses,
    from the picture alone: the camera faces the user, so their left hand is the
    one further right in the image.
    """
    if len(detected) != 2 or detected[0]["side"] != detected[1]["side"]:
        return False
    first, second = sorted(detected, key=_screen_x)
    first["side"], second["side"] = "Right", "Left"
    return True


def assign_sides(detected: list[dict], body: BodyFeed | None) -> bool:
    """Pair two detected hands with the body's two wrists, in place.

    Astra's +x is the camera's right and image x grows to the right, so the
    wrist with the larger x is the hand nearer the right edge. This overrides
    MediaPipe's handedness guess, which assumes a mirrored selfie image and is
    therefore systematically swapped for an unmirrored depth camera.
    """
    if len(detected) != 2 or body is None or not body.is_fresh():
        return False
    left, right = body.hand("Left"), body.hand("Right")
    if not left or not right or abs(left[0] - right[0]) < 40.0:
        return False
    ordered = sorted(detected, key=_screen_x)
    first, second = ("Right", "Left") if left[0] > right[0] else ("Left", "Right")
    ordered[0]["side"], ordered[1]["side"] = first, second
    return True


def main() -> int:
    args = parse_args()
    bridge = start_bridge(args) if args.start_bridge else None
    feed = None
    body = None
    tracker = None
    preview = None
    try:
        feed = connect_feed(args.color_port)
        tracker = HandTracker(mirror_sides=args.mirror)
        lift = hand3d.HandLift()
        if args.body_port > 0:
            try:
                body = BodyFeed(port=args.body_port)
            except OSError as error:
                print(
                    f"无法监听身体骨架 127.0.0.1:{args.body_port}（{error}），"
                    "左右手改用 MediaPipe 标签。"
                )

        sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        session = f"{Path(sys.executable).stat().st_size}-{int(time.time() * 1000)}"
        left_smoother = curl_module.CurlSmoother()
        right_smoother = curl_module.CurlSmoother()
        previous = time.perf_counter()
        sequence = 0
        counted = 0
        started = previous
        last_send = 0.0
        paired = False
        missing = {"Left": None, "Right": None}
        held: dict[str, tuple[dict, float]] = {}

        if args.preview:
            import cv2

            preview = cv2

        print(f"手部追踪已启动 -> {args.host}:{args.hand_port}，Ctrl+C 退出。")
        while True:
            _width, _height, _index, _stamp, image = feed.read()
            if _height:
                lift.aspect = float(_width) / float(_height)
            now = time.perf_counter()
            delta = max(1e-3, now - previous)
            previous = now

            if body is not None:
                body.poll()
            detected = tracker.process(image, int((now - started) * 1000))
            if assign_sides(detected, body) and not paired:
                paired = True
                print("左右手已按身体骨架的手腕位置配对，不再依赖 MediaPipe 标签。")
            # No-op whenever the line above gave the two hands different sides.
            split_shared_sides(detected)

            entries = []
            seen = set()
            for hand in detected:
                if hand["score"] < args.min_confidence:
                    continue
                side = hand["side"]
                solved = lift.solve(hand["screen"], side, basis=palm_frame(hand))
                if solved is None:
                    continue
                points, _palm_pixels, axes = solved
                palm_mm = palm_millimetres(hand)
                if not skeleton.is_plausible(points, palm_mm):
                    continue
                seen.add(side)
                smoother = left_smoother if side == "Left" else right_smoother
                curls = smoother.apply(curl_module.compute_curls(hand["points"]), delta)
                gesture = curl_module.classify(curls)
                entry = protocol.hand_entry(
                    side, hand["score"], points, palm_mm, curls, gesture, basis=wire_axes(axes)
                )
                entries.append(entry)
                held[side] = (entry, now)
            # A refused frame used to drop that hand out of the packet, and the
            # receiver answers a missing hand by easing it back towards its bind
            # pose. Curling four fingers into a thumbs-up is enough to produce
            # those frames - MediaPipe's landmarks fold through each other and
            # the palm measures wider than it is long - so at 24 fps the wrist
            # spent whole seconds flapping between the tracked pose and the bind
            # pose, which is the "arm will not stay under control" report.
            # Re-send the last pose that did solve instead: a hand that holds
            # still reads as a hand that is not moving, and half a second later
            # it is given up on anyway.
            for side, (entry, stamp) in held.items():
                if side not in seen and now - stamp <= HAND_HOLD:
                    entries.append(entry)
            for side in ("Left", "Right"):
                if side in seen:
                    missing[side] = None
                elif missing[side] is None:
                    missing[side] = now
                elif now - missing[side] > HAND_GRACE:
                    (left_smoother if side == "Left" else right_smoother).reset()
                    lift.reset(side)

            # Keep a steady heartbeat so Unity can fall back when hands leave the view.
            if entries or now - last_send > 0.2:
                sink.sendto(
                    protocol.encode(session, sequence, int(now * 1000), entries),
                    (args.host, args.hand_port),
                )
                last_send = now
            sequence += 1
            counted += 1

            if preview is not None:
                frame = image[:, :, ::-1].copy()
                for hand in detected:
                    if hand["screen"] is not None:
                        for x, y in hand["screen"]:
                            centre = (int(x * frame.shape[1]), int(y * frame.shape[0]))
                            preview.circle(frame, centre, 2, (0, 255, 0), -1)
                    if hand["screen"] is None:
                        continue
                    # Which side of the hand the picture is showing, decided by
                    # the same 2D landmarks that build the skeleton. Printed
                    # next to the hand so "the avatar shows the back of its hand
                    # while I am showing my palm" can be split into "the
                    # tracker lost the side" and "the avatar lost the side"
                    # without reading any numbers.
                    wrist = hand["screen"][skeleton.WRIST]
                    preview.putText(
                        frame,
                        f"{hand['side'][0]} {palm_facing(hand)}",
                        (int(wrist[0] * frame.shape[1]) - 20, int(wrist[1] * frame.shape[0]) + 18),
                        preview.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 255, 255),
                        2,
                    )
                rate = counted / max(1e-3, now - started)
                preview.putText(
                    frame,
                    f"{rate:.1f} fps  hands={len(entries)}",
                    (8, 24),
                    preview.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2,
                )
                preview.imshow("DollFight hand tracking", frame)
                if preview.waitKey(1) & 0xFF == 27:
                    break

            if counted % 60 == 0:
                rate = counted / max(1e-3, now - started)
                print(f"{counted} 帧  {rate:.1f} fps  手: {[e['side'] for e in entries]}")
    except KeyboardInterrupt:
        pass
    except ColorFeedError as error:
        print(f"彩色流中断：{error}")
    finally:
        if preview is not None:
            preview.destroyAllWindows()
        if tracker is not None:
            tracker.close()
        if body is not None:
            body.close()
        if feed is not None:
            feed.close()
        if bridge is not None:
            bridge.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
