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
        # Which body this feed is following. The SDK reports every person it can
        # see, and their order in ``bodies`` is not stable; picking the first one
        # every frame makes the skeleton jump to whoever happens to come first.
        # The Unity receiver pins an id for the same reason, so this does too.
        self.body_id = 0
        self.session = None
        self.body = None
        # How many people the SDK reported as tracked in the last frame. Shown
        # in the preview: with two people in shot, a skeleton that moves to the
        # other one is a selection problem, not a coordinate problem.
        self.tracked_count = 0

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
            # A new session means the bridge restarted, so any id pinned from the
            # previous one refers to nobody.
            if message.get("session") != self.session:
                self.session = message.get("session")
                self.body_id = 0
            self.frame = message
            self.body = self._select_body(message)
            self.updated_at = time.perf_counter()
            self.received += 1
            got = True
        return got

    def is_fresh(self) -> bool:
        return self.frame is not None and time.perf_counter() - self.updated_at <= self.timeout

    def _tracked_body(self):
        return self.body if self.is_fresh() else None

    def _select_body(self, message):
        """Pin one body for as long as it is tracked, the way Unity does.

        The previous id wins while that person is still there. Only when they
        are gone does another get chosen -- lowest id first, so the choice does
        not depend on the order the SDK happened to list them in.
        """
        bodies = message.get("bodies") or []
        tracked = [
            body for body in bodies if isinstance(body, dict) and body.get("status") in (2, 3)
        ]
        self.tracked_count = len(tracked)
        for body in tracked:
            if self.body_id and self._id_of(body) == self.body_id:
                return body
        if not tracked:
            self.body_id = 0
            return None
        chosen = min(tracked, key=self._id_of)
        self.body_id = self._id_of(chosen)
        return chosen

    @staticmethod
    def _id_of(body) -> int:
        try:
            return int(body.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    def screen_size(self) -> tuple[int, int]:
        """Pixel size of the image the joints were projected into.

        The bridge reports it per frame; 640x480 is the Astra depth grid the
        body tracker runs on, used only when an older bridge omits the field.
        """
        frame = self.frame if self.is_fresh() else {}
        screen = (frame or {}).get("screen") or {}
        try:
            width, height = int(screen.get("width", 0)), int(screen.get("height", 0))
        except (TypeError, ValueError):
            return (640, 480)
        return (width, height) if width > 0 and height > 0 else (640, 480)

    def screens(self, min_status: int = 1) -> dict[int, tuple[float, float]]:
        """Every tracked joint as ``{type: (u, v)}`` in image pixels.

        These come from the sensor's own projection of each joint, so they line
        up with the picture without any intrinsics or axis guessing on this
        side. Joints the SDK did not project are left out; so are joints sitting
        outside the image, because a dot on the border reads as a tracked joint
        that has gone somewhere it cannot be.

        ``min_status`` is the confidence a joint needs to count. The default
        keeps low-confidence joints, which is what the receiver in Unity uses.
        The preview asks for 2 instead: a joint the sensor is guessing at is
        drawn from its model rather than from the picture, and that is the arm
        that flies out to the side when a real arm rests against the body.
        """
        body = self._tracked_body()
        if body is None:
            return {}
        width, height = self.screen_size()
        found: dict[int, tuple[float, float]] = {}
        for joint in body.get("joints") or []:
            if not isinstance(joint, dict):
                continue
            try:
                kind = int(joint.get("type"))
            except (TypeError, ValueError):
                continue
            if int(joint.get("status") or 0) < min_status:
                continue
            screen = joint.get("screen") or {}
            if not isinstance(screen, dict) or not screen.get("ok"):
                continue
            try:
                u, v = float(screen["x"]), float(screen["y"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0.0 <= u < width and 0.0 <= v < height:
                found[kind] = (u, v)
        return found

    def joint(self, joint_type: int):
        """World position (mm) of a joint on the first tracked body, or None."""
        body = self._tracked_body()
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

    def joints(self) -> dict[int, tuple[float, float, float]]:
        """Every tracked joint as ``{type: (x, y, z)}`` in millimetres.

        Untracked and malformed joints are left out instead of being given a
        placeholder position: the preview draws what the receiver would accept,
        so a joint that disappears here is one Unity would have ignored too.
        """
        body = self._tracked_body()
        if body is None:
            return {}
        found: dict[int, tuple[float, float, float]] = {}
        for joint in body.get("joints") or []:
            if not isinstance(joint, dict):
                continue
            try:
                kind = int(joint.get("type"))
            except (TypeError, ValueError):
                continue
            if int(joint.get("status") or 0) < 1:
                continue
            position = joint.get("position") or {}
            try:
                values = (float(position["x"]), float(position["y"]), float(position["z"]))
            except (KeyError, TypeError, ValueError):
                continue
            found[kind] = values
        return found

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
