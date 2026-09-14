"""Threaded camera capture with timestamp overlay and recording."""

from __future__ import annotations

import os
import platform
import threading
import time
from datetime import datetime

import cv2
import numpy as np

from .overlay import draw_timestamp

# Codecs known to work with OpenCV's VideoWriter per container.
_FOURCC = {
    "mp4": "mp4v",
    "mkv": "mp4v",
    "avi": "MJPG",
}


class CameraStream:
    """Continuously grabs frames from one capture device in a background thread.

    ``source`` may be a local device index (int, e.g. a USB webcam) or a stream
    URL (str, e.g. an RTSP/HTTP feed from a Wi-Fi camera). Each grabbed frame
    has the timestamp burned in immediately, so both the live preview and any
    recording share the exact same overlay.
    """

    def __init__(self, source: int | str, label: str = "", overlay_corner: str = "bottom-left"):
        self.source = source
        self.label = label
        self.overlay_corner = overlay_corner

        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None

        self._writer: cv2.VideoWriter | None = None
        self._recording = False
        self._record_path: str | None = None

        self.connected = False
        self._fps = 0.0
        self._frame_times: list[float] = []

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"cam-{self.source}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.stop_recording()
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # -- capture loop ------------------------------------------------------
    def _backend(self) -> int:
        if isinstance(self.source, str):
            return cv2.CAP_FFMPEG
        system = platform.system()
        if system == "Darwin":
            return cv2.CAP_AVFOUNDATION
        if system == "Windows":
            return cv2.CAP_DSHOW
        return cv2.CAP_ANY

    def _open(self) -> bool:
        if isinstance(self.source, str) and self.source.lower().startswith("rtsp"):
            # Prefer TCP for RTSP: more reliable than UDP over Wi-Fi.
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

        cap = cv2.VideoCapture(self.source, self._backend())
        if not cap.isOpened():
            cap.release()
            return False
        if isinstance(self.source, str):
            # Keep latency low on live network streams.
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except cv2.error:
                pass
        self._cap = cap
        self.connected = True
        return True

    def _loop(self) -> None:
        while self._running:
            if self._cap is None:
                if not self._open():
                    self.connected = False
                    time.sleep(1.0)  # wait before retrying a missing device
                    continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                # Device dropped: release and try to reconnect.
                self.connected = False
                if self._cap is not None:
                    self._cap.release()
                    self._cap = None
                time.sleep(0.5)
                continue

            draw_timestamp(frame, label=self.label, corner=self.overlay_corner)
            self._update_fps()

            with self._lock:
                self._latest = frame
                if self._recording and self._writer is not None:
                    self._writer.write(frame)

    def _update_fps(self) -> None:
        now = time.time()
        self._frame_times.append(now)
        # Keep a ~1 second sliding window.
        cutoff = now - 1.0
        while self._frame_times and self._frame_times[0] < cutoff:
            self._frame_times.pop(0)
        if len(self._frame_times) > 1:
            span = self._frame_times[-1] - self._frame_times[0]
            self._fps = (len(self._frame_times) - 1) / span if span > 0 else 0.0

    # -- accessors ---------------------------------------------------------
    @property
    def fps(self) -> float:
        return self._fps

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def record_path(self) -> str | None:
        return self._record_path

    def latest_frame(self) -> np.ndarray | None:
        """Return a copy of the most recent overlaid frame (BGR), or None."""
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    # -- recording ---------------------------------------------------------
    def start_recording(self, out_dir: str, container: str = "mp4") -> str | None:
        with self._lock:
            if self._recording or self._latest is None:
                return None
            h, w = self._latest.shape[:2]
            container = container.lower().lstrip(".")
            fourcc_code = _FOURCC.get(container, "mp4v")
            fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
            fps = self._fps if self._fps >= 1.0 else 30.0

            os.makedirs(out_dir, exist_ok=True)
            safe = (self.label or "cam").replace(" ", "_")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(out_dir, f"{safe}_{stamp}.{container}")

            writer = cv2.VideoWriter(path, fourcc, fps, (w, h))
            if not writer.isOpened():
                return None
            self._writer = writer
            self._record_path = path
            self._recording = True
            return path

    def stop_recording(self) -> str | None:
        with self._lock:
            path = self._record_path
            self._recording = False
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            self._record_path = None
            return path

    def snapshot(self, out_dir: str) -> str | None:
        frame = self.latest_frame()
        if frame is None:
            return None
        os.makedirs(out_dir, exist_ok=True)
        safe = (self.label or "cam").replace(" ", "_")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"{safe}_{stamp}.jpg")
        cv2.imwrite(path, frame)
        return path
