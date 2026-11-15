"""Wire formats: the body JSON the Astra bridge emits and the hands datagrams.

Both senders are deliberately byte-compatible with what Unity already parses,
so switching the camera does not touch the Unity project.
"""

from __future__ import annotations

import json
import socket

import numpy as np

IDENTITY = [
    1.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    1.0,
]


def body_packet(
    bodies,
    sequence: int,
    source_frame: int,
    session: str,
    timestamp_ms: int,
) -> bytes:
    """Same shape as ``packet()`` in the Astra bridge's main.cpp."""
    payload = {
        "version": 1,
        "session": session,
        "sequence": int(sequence),
        "sourceFrame": int(source_frame),
        "timestampMs": int(timestamp_ms),
        "simulated": False,
        "units": "mm",
        "bodies": [
            {
                "id": int(body.body_id),
                "status": 2,  # ASTRA_BODY_STATUS_TRACKING
                "joints": [
                    {
                        "type": joint,
                        # Astra: 0 = not tracked, 1 = low confidence,
                        # 2 = tracked. The game only treats 2 as a good joint.
                        "status": 2 if body.status[joint] else 0,
                        "position": {
                            "x": round(float(body.joints[joint][0]), 2),
                            "y": round(float(body.joints[joint][1]), 2),
                            "z": round(float(body.joints[joint][2]), 2),
                        },
                        "orientation": IDENTITY,
                    }
                    for joint in range(len(body.joints))
                ],
            }
            for body in bodies
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class UdpSender:
    def __init__(self, host: str, port: int):
        self.target = (host, int(port))
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, payload: bytes) -> None:
        self.socket.sendto(payload, self.target)

    def close(self) -> None:
        self.socket.close()


def sort_bodies(bodies, previous: dict[int, np.ndarray] | None = None):
    """Stable ids: keep a body on the same id by nearest hip, not by left-right.

    Sorting by screen x alone swaps ids the moment two players cross, which
    teleports both avatars for a frame and, worse, swaps their hands.
    """
    previous = previous or {}
    taken: dict[int, object] = {}
    free = [body for body in bodies]

    for body_id, hip in previous.items():
        best = None
        best_distance = 900.0
        for body in free:
            joint = body.joints[9]  # BASE_SPINE
            distance = float(np.linalg.norm(joint - hip))
            if distance < best_distance:
                best, best_distance = body, distance
        if best is not None:
            taken[body_id] = best
            free.remove(best)

    next_id = 1
    for body in free:
        while next_id in taken:
            next_id += 1
        taken[next_id] = body

    ordered = []
    for body_id in sorted(taken):
        body = taken[body_id]
        body.body_id = body_id
        ordered.append(body)
    return ordered
