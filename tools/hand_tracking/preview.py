"""A preview window that cannot stall the tracker.

Dragging an OpenCV window on Windows runs a modal resize loop inside
``waitKey``. When that window lives on the tracking thread -- which is where
``imshow`` is normally called -- the whole pipeline stops for as long as the
drag lasts: hands freeze, nothing is sent to Unity, and every frame the camera
produced meanwhile piles up on the socket, so the picture is late afterwards
too.

Here the tracker only drops the newest frame into a slot. A slow or blocked
window costs dropped preview frames and nothing else: the slot is overwritten,
never queued.
"""

from __future__ import annotations

import threading
import time

WINDOW_NAME = "DollFight camera + body skeleton"
ESC = 27


class PreviewWindow:
    """Shows the newest frame on a thread of its own."""

    def __init__(self, cv2, name: str = WINDOW_NAME, idle: float = 0.005):
        self.cv2 = cv2
        self.name = name
        self.idle = idle
        self._lock = threading.Lock()
        self._frame = None
        self._closed = threading.Event()
        # Set when the window itself fails, so the caller can tell "the user
        # pressed Esc" apart from "there is no display".
        self.error = None
        self._thread = threading.Thread(target=self._run, name="preview", daemon=True)
        self._thread.start()

    def __getattr__(self, item):
        # Drawing helpers -- circle, putText, line -- only touch the array they
        # are handed, so they stay on the caller's thread and are proxied to cv2.
        # Every window call is defined here instead, so they never reach this.
        return getattr(self.cv2, item)

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def show(self, frame) -> None:
        """Hand over one frame; the newest one wins if the window is behind."""
        with self._lock:
            self._frame = frame

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        try:
            while not self._closed.is_set():
                with self._lock:
                    frame, self._frame = self._frame, None
                if frame is None:
                    time.sleep(self.idle)
                    continue
                try:
                    self.cv2.imshow(self.name, frame)
                    pressed = self.cv2.waitKey(1) & 0xFF
                except Exception as error:
                    self.error = error
                    break
                if pressed == ESC:
                    break
        finally:
            self._closed.set()
            try:
                self.cv2.destroyWindow(self.name)
            except Exception:
                pass
