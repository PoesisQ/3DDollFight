"""Reads the body skeleton that the bridge mirrors to the hand tracker.

The bridge already publishes ``dollfight-body-1`` to Unity on port 7001. With
``--mirror-port`` it sends the same datagram here, which gives the hand tracker
the left/right wrist positions it needs to pair a detected hand with the arm it
actually belongs to. Without this, MediaPipe handedness alone decides left vs
right, and a mirrored image would silently drive the wrong hand.
"""

from __future__ import annotations

import json
import socket
import time

# Astra joint ids: 4 = left hand (wrist), 7 = right hand (wrist), 16/17 the
# extra wrist joints that sit just below them.
LEFT_HAND = 4
RIGHT_HAND = 7
LEFT_WRIST = 16
RIGHT_WRIST = 17


class BodyFeed:
    """Non-blocking reader for the mirrored body datagrams."""

    def __init__(self, port: int = 7012, timeout: float = 0.5):
        self.timeout = float(timeout)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", int(port)))
        self.socket.setblocking(False)
        self.port = self.socket.getsockname()[1]
        self.frame = None
        self.updated_at = 0.0
        self.received = 0

    def poll(self) -> bool:
        """Drain the socket; return True when a new body frame arrived."""
        got = False
        while True:
            try:
                datagram, _ = self.socket.recvfrom(65535)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            try:
                message = json.loads(datagram)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict) or message.get("version") != 1:
                continue
            if not isinstance(message.get("bodies"), list):
                continue
            self.frame = message
            self.updated_at = time.perf_counter()
            self.received += 1
            got = True
        return got

    def is_fresh(self) -> bool:
        return self.frame is not None and time.perf_counter() - self.updated_at <= self.timeout

    def _first_tracked_body(self):
        if not self.is_fresh():
            return None
        for body in self.frame["bodies"]:
            if not isinstance(body, dict):
                continue
            if body.get("status") in (2, 3):
                return body
        return None

    def joint(self, joint_type: int):
        """World position (mm) of a joint on the first tracked body, or None."""
        body = self._first_tracked_body()
        if body is None:
            return None
        for joint in body.get("joints") or []:
            if not isinstance(joint, dict) or joint.get("type") != joint_type:
                continue
            if int(joint.get("status") or 0) < 1:
                return None
            position = joint.get("position") or {}
            try:
                return (float(position["x"]), float(position["y"]), float(position["z"]))
            except (KeyError, TypeError, ValueError):
                return None
        return None

    def hand(self, side: str):
        """Wrist position for ``"Left"``/``"Right"``; falls back to the extra wrist joint."""
        if side == "Left":
            return self.joint(LEFT_HAND) or self.joint(LEFT_WRIST)
        if side == "Right":
            return self.joint(RIGHT_HAND) or self.joint(RIGHT_WRIST)
        raise ValueError(f"side must be Left or Right, got {side!r}")

    def close(self) -> None:
        try:
            self.socket.close()
        except OSError:
            pass

    def __enter__(self) -> BodyFeed:
        return self

    def __exit__(self, *_) -> None:
        self.close()
