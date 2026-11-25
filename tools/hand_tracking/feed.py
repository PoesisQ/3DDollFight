"""Client for the raw RGB stream exposed by ``AstraUnityBridge --color-port``."""

from __future__ import annotations

import select
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

    def read_latest(self, max_skip: int = 30):
        """Return the newest frame, dropping any the caller was too slow to take.

        The camera keeps producing while the previous frame is being processed.
        Reading strictly in order leaves that backlog on the socket, so the
        preview and the hand data drift further behind the person with every
        second of heavy processing. Skipping to the newest frame holds the delay
        at one frame however slow the caller is: the skipped frames could not
        have been processed in time anyway.
        """
        frame = self.read()
        skipped = 0
        while skipped < max_skip and self._pending():
            frame = self.read()
            skipped += 1
        return frame

    def _pending(self) -> bool:
        """True only when a frame is waiting, not when the bridge has hung up.

        ``select`` cannot tell data from end-of-file, so peek at one byte: a
        closed connection is readable but yields nothing, and treating that as
        another frame would turn a normal shutdown into a read error.
        """
        connection = self.connection
        if connection is None:
            return False
        try:
            ready, _, _ = select.select([connection], [], [], 0)
        except (OSError, ValueError):
            return False
        if not ready:
            return False
        try:
            return bool(connection.recv(1, socket.MSG_PEEK))
        except (BlockingIOError, InterruptedError):
            return False
        except OSError:
            return False

    def __enter__(self) -> ColorFeed:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()
