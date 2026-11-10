"""Client for the raw RGB stream exposed by ``AstraUnityBridge --color-port``."""

from __future__ import annotations

import socket
import struct

import numpy as np

MAGIC = b"DFCF"
HEADER = struct.Struct("<4sIIIII")  # magic, width, height, index, timestamp low, timestamp high


class ColorFeedError(RuntimeError):
    pass


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    buffer = bytearray(size)
    view = memoryview(buffer)
    received = 0
    while received < size:
        count = connection.recv_into(view[received:], size - received)
        if count == 0:
            raise ColorFeedError("colour feed closed by the bridge")
        received += count
    return bytes(buffer)


class ColorFeed:
    """Blocking reader for the bridge's 24-byte header + RGB24 payload."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7005, timeout: float = 10.0):
        self.address = (host, port)
        self.timeout = timeout
        self.connection: socket.socket | None = None

    def connect(self) -> None:
        connection = socket.create_connection(self.address, timeout=self.timeout)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.settimeout(None)
        self.connection = connection

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None

    def read(self):
        if self.connection is None:
            raise ColorFeedError("colour feed is not connected")
        header = _recv_exact(self.connection, HEADER.size)
        magic, width, height, index, low, high = HEADER.unpack(header)
        if magic != MAGIC:
            raise ColorFeedError(f"bad colour header magic {magic!r}")
        if not (0 < width <= 4096 and 0 < height <= 4096):
            raise ColorFeedError(f"bad colour frame size {width}x{height}")
        payload = _recv_exact(self.connection, width * height * 3)
        image = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3)
        return width, height, index, (high << 32) | low, image

    def __enter__(self) -> ColorFeed:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()
