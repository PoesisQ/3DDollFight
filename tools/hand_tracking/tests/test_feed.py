"""Tests for the bridge colour feed parser and the MediaPipe wrapper."""

from __future__ import annotations

import socket
import struct
import sys
import threading
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import feed as feed_module  # noqa: E402


def serve_once(
    connection: socket.socket, width: int, height: int, index: int, stamp: int, pixels: bytes
):
    header = struct.pack("<4sIIIII", b"DFCF", width, height, index, stamp & 0xFFFFFFFF, stamp >> 32)
    connection.sendall(header + pixels)
    connection.close()


class ColorFeedTests(unittest.TestCase):
    def _roundtrip(self, width: int, height: int, payload: bytes | None = None):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        pixels = payload if payload is not None else bytes([7, 8, 9] * width * height)
        thread = threading.Thread(
            target=lambda: serve_once(server.accept()[0], width, height, 42, 5_000_000_123, pixels)
        )
        thread.start()
        try:
            client = feed_module.ColorFeed(port=port)
            client.connect()
            received = client.read()
            client.close()
        finally:
            thread.join(2)
            server.close()
        return received

    def test_reads_header_and_pixels(self):
        width, height, index, stamp, image = self._roundtrip(4, 3)
        self.assertEqual((width, height, index), (4, 3, 42))
        self.assertEqual(stamp, 5_000_000_123)
        self.assertEqual(image.shape, (3, 4, 3))
        self.assertEqual(image.dtype, np.uint8)
        self.assertEqual(int(image[0, 0, 0]), 7)

    def test_rejects_bad_magic(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def bad():
            connection, _ = server.accept()
            connection.sendall(struct.pack("<4sIIIII", b"XXXX", 1, 1, 0, 0, 0) + b"\0\0\0")
            connection.close()

        thread = threading.Thread(target=bad)
        thread.start()
        try:
            client = feed_module.ColorFeed(port=port)
            client.connect()
            with self.assertRaises(feed_module.ColorFeedError):
                client.read()
            client.close()
        finally:
            thread.join(2)
            server.close()


class TrackerTests(unittest.TestCase):
    def test_model_loads_and_returns_list_on_blank_frame(self):
        try:
            from tracker import HandTracker
        except Exception as error:  # pragma: no cover - environment without MediaPipe
            self.skipTest(f"MediaPipe unavailable: {error}")
        try:
            tracker = HandTracker()
        except RuntimeError as error:
            self.skipTest(str(error))
        try:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            hands = tracker.process(blank, 0)
            self.assertIsInstance(hands, list)
            self.assertEqual(hands, [])
            hands = tracker.process(blank, 33)
            self.assertEqual(hands, [])
        finally:
            tracker.close()


if __name__ == "__main__":
    unittest.main()
