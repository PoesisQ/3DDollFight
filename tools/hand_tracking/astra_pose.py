"""MediaPipe Pose Heavy on Astra's paired RGB/depth stream, sent as Astra joints."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

GEMINI_DIR = Path(__file__).resolve().parents[1] / "gemini_tracking"
if str(GEMINI_DIR) not in sys.path:
    sys.path.insert(0, str(GEMINI_DIR))

from body_pose import BodySolver, PoseDetector, calibration_issue  # noqa: E402
from gemini_camera import Frame  # noqa: E402
from sender import UdpSender, body_packet  # noqa: E402

MODEL = GEMINI_DIR / "models" / "pose_landmarker_heavy.task"


def require_leg_depth(body, landmarks, frame):
    """Do not report knee/foot depth borrowed from a different body part as tracked."""
    for joint, landmark in ((11, 25), (14, 26), (12, 27), (15, 28)):
        point = landmarks[landmark]
        x, y = float(point.x), float(point.y)
        if not (np.isfinite(x) and np.isfinite(y) and 0 <= x < 1 and 0 <= y < 1):
            body.status[joint] = 0
            continue
        measured = frame.depth_at(x * (frame.width - 1), y * (frame.height - 1))
        if not np.isfinite(measured) or not (120 <= measured <= 10000):
            body.status[joint] = 0

def additional_pose_points(landmarks, frame):
    """Independent Pose landmarks with their own measured depth, in Astra mm.

    No neighbour-depth fallback: an unreliable point is marked unavailable.
    These are supplemental observations, not extra humanoid bones.
    """
    output = []
    for index, point in enumerate(landmarks[:33]):
        x, y = float(point.x), float(point.y)
        visible = float(getattr(point, "visibility", 1.0))
        z = 0.0
        if np.isfinite([x, y, visible]).all() and visible >= 0.5 and 0 <= x < 1 and 0 <= y < 1:
            u, v = x * (frame.width - 1), y * (frame.height - 1)
            z = frame.depth_at(u, v)
        if np.isfinite(z) and 120 <= z <= 10000:
            position = {"x": round(-(u - frame.cx) * z / frame.fx, 2),
                        "y": round(-(v - frame.cy) * z / frame.fy, 2), "z": round(z, 2)}
            output.append({"type": index, "status": 2, "position": position})
    return output


class AstraPoseTracker:
    def __init__(self, host="127.0.0.1", port=7001, model=MODEL):
        model = Path(model)
        if not model.is_file():
            raise RuntimeError("缺少 Pose Heavy 模型，请先下载 pose_landmarker_heavy.task")
        self.detector = PoseDetector(model, max_poses=1, min_confidence=0.4)
        self.solver = BodySolver(smoothing=12.0)
        self.sender = UdpSender(host, port)
        self.session = "astra-pose-" + str(int(time.time() * 1000))
        self.sequence = 0
        self.last_issue = None
        self.last_issue_at = 0.0

    def process(self, rgb, depth, intrinsics, frame_index, stamp_ms):
        if depth is None or intrinsics is None or depth.shape != rgb.shape[:2]:
            raise RuntimeError("人体模型需要同步的 Astra 彩色和深度帧")
        fx, fy, cx, cy = intrinsics
        if not np.isfinite([fx, fy, cx, cy]).all() or fx <= 0 or fy <= 0:
            raise RuntimeError("相机参数无效，不能推算三维骨架")
        frame = Frame(bgr=rgb, depth_mm=depth, fx=fx, fy=fy, cx=cx, cy=cy,
                      timestamp_ms=int(stamp_ms), sequence=int(frame_index))
        result = self.detector.detect(rgb, int(stamp_ms))
        bodies = []
        extra_points = []
        for landmarks in result.pose_landmarks[:1]:
            body = self.solver.solve(landmarks, frame, 1, float(stamp_ms) / 1000.0)
            if body is not None:
                require_leg_depth(body, landmarks, frame)
                bodies.append(body)
                extra_points.append(additional_pose_points(landmarks, frame))
        payload = json.loads(body_packet(bodies, self.sequence, frame_index, self.session, stamp_ms))
        for packet_body, points in zip(payload["bodies"], extra_points):
            packet_body["poseLandmarks"] = points
        payload = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.sender.send(payload)
        self.sequence += 1
        now = time.monotonic()
        issue = calibration_issue(bodies[0]) if bodies else "未识别到人体"
        if bodies and issue is None:
            status = bodies[0].status
            missing = [name for index, name in ((11, "左膝"), (14, "右膝"),
                                                 (12, "左脚"), (15, "右脚")) if not status[index]]
            issue = "上身可校准，未识别：" + "、".join(missing) if missing else None
        if issue != self.last_issue and now - self.last_issue_at >= 1.5:
            print("人体模型：" + (issue or "关节点满足校准条件"), flush=True)
            self.last_issue, self.last_issue_at = issue, now
        return bodies

    def close(self):
        self.detector.close()
        self.sender.close()
