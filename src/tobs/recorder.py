"""Combined recorder: both camera feeds in one split frame + mic audio, one file.

The two live camera frames are scaled and placed **side-by-side into a single
video frame** (a split view). That video, together with audio captured from a
selected microphone, is muxed into **one** MP4/MKV file using PyAV (ffmpeg).

OpenCV's ``VideoWriter`` cannot write audio, which is why this path uses PyAV.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from datetime import datetime
from fractions import Fraction
from typing import Callable, Sequence

import cv2
import numpy as np

try:  # PyAV provides the muxer/encoders (bundled ffmpeg).
    import av
except Exception:  # pragma: no cover - import guard
    av = None

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - import guard
    sd = None


# Callable returning the latest BGR frame (or None) for each panel, in order.
FramesSource = Callable[[], Sequence["np.ndarray | None"]]


def _letterbox(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize ``frame`` into a ``width``x``height`` canvas, preserving aspect."""
    h, w = frame.shape[:2]
    if w == 0 or h == 0:
        return np.zeros((height, width, 3), np.uint8)
    scale = min(width / w, height / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((height, width, 3), np.uint8)
    x, y = (width - nw) // 2, (height - nh) // 2
    canvas[y : y + nh, x : x + nw] = resized
    return canvas


class CombinedRecorder:
    """Encode a split side-by-side video plus microphone audio into one file."""

    def __init__(
        self,
        get_frames: FramesSource,
        mic_index: int | None = None,
        panel_size: tuple[int, int] = (640, 480),
        fps: float = 25.0,
        samplerate: int = 48000,
    ):
        self._get_frames = get_frames
        self._mic_index = mic_index
        self._pw = panel_size[0] - (panel_size[0] % 2)  # even dims for yuv420p
        self._ph = panel_size[1] - (panel_size[1] % 2)
        self._fps = max(1, int(round(fps)))
        self._samplerate = int(samplerate)

        self._container = None
        self._vstream = None
        self._astream = None
        self._fifo = None
        self._resampler = None
        self._audio_input = None
        self._has_audio = False
        self._audio_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=128)

        self._thread: threading.Thread | None = None
        self._running = False
        self._recording = False
        self._path: str | None = None
        self._error: str | None = None

    # -- public API --------------------------------------------------------
    @staticmethod
    def available() -> bool:
        return av is not None

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def path(self) -> str | None:
        return self._path

    def start(self, out_dir: str, container: str = "mp4") -> str | None:
        if self._recording:
            return None
        if av is None:
            self._error = "PyAV ('av') is not installed — cannot record combined file."
            return None

        panels = max(1, len(self._get_frames()))
        width, height = self._pw * panels, self._ph

        os.makedirs(out_dir, exist_ok=True)
        container = container.lower().lstrip(".")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"combined_{stamp}.{container}")

        try:
            self._container = av.open(path, mode="w")
            self._vstream = self._add_video_stream(width, height)
            if self._vstream is None:
                raise RuntimeError("no usable H.264/MPEG-4 video encoder available")

            self._has_audio = self._mic_index is not None and sd is not None
            if self._has_audio:
                self._astream = self._container.add_stream("aac", rate=self._samplerate)
                self._astream.layout = "mono"
                self._fifo = av.AudioFifo()
                self._resampler = av.AudioResampler(
                    format="fltp", layout="mono", rate=self._samplerate
                )
        except Exception as exc:
            self._error = f"Failed to start recorder: {exc}"
            self._close_container()
            return None

        self._error = None
        self._path = path
        self._running = True
        self._recording = True

        if self._has_audio:
            self._start_microphone()

        self._thread = threading.Thread(
            target=self._worker, name="combined-rec", daemon=True
        )
        self._thread.start()
        return path

    def stop(self) -> str | None:
        if not self._recording:
            return None
        self._running = False
        if self._audio_input is not None:
            try:
                self._audio_input.stop()
                self._audio_input.close()
            except Exception:
                pass
            self._audio_input = None
        if self._thread is not None:
            self._thread.join(timeout=8.0)
            self._thread = None
        self._recording = False
        return self._path

    # -- setup helpers -----------------------------------------------------
    def _add_video_stream(self, width: int, height: int):
        for codec in ("libx264", "mpeg4"):
            try:
                stream = self._container.add_stream(codec, rate=self._fps)
                stream.width = width
                stream.height = height
                stream.pix_fmt = "yuv420p"
                if codec == "libx264":
                    stream.options = {"crf": "23", "preset": "veryfast"}
                return stream
            except Exception:
                continue
        return None

    def _start_microphone(self) -> None:
        try:
            self._audio_input = sd.InputStream(
                device=self._mic_index,
                channels=1,
                samplerate=self._samplerate,
                dtype="int16",
                blocksize=1024,
                callback=self._audio_callback,
            )
            self._audio_input.start()
        except Exception as exc:
            # Degrade to video-only rather than aborting the whole recording.
            self._has_audio = False
            self._astream = None
            self._fifo = None
            self._resampler = None
            self._audio_input = None
            self._error = f"Microphone unavailable — recording video only ({exc})."

    def _audio_callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        try:
            self._audio_q.put_nowait(indata.copy())
        except queue.Full:
            pass

    # -- encode loop -------------------------------------------------------
    def _worker(self) -> None:
        start = time.monotonic()
        v_count = 0
        a_pts = 0
        try:
            while self._running:
                target = int((time.monotonic() - start) * self._fps)
                while v_count <= target:
                    self._encode_video_frame(v_count)
                    v_count += 1
                if self._has_audio:
                    a_pts = self._encode_audio(a_pts)
                time.sleep(0.003)

            # Flush remaining audio, then drain the encoders.
            if self._has_audio:
                a_pts = self._encode_audio(a_pts, final=True)
                for pkt in self._astream.encode(None):
                    self._container.mux(pkt)
            for pkt in self._vstream.encode(None):
                self._container.mux(pkt)
        except Exception as exc:  # keep the file closable even on failure
            self._error = f"Recording error: {exc}"
        finally:
            self._close_container()

    def _encode_video_frame(self, index: int) -> None:
        frames = self._get_frames()
        canvas = self._combine(frames)
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        vframe = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        vframe.pts = index
        vframe.time_base = Fraction(1, self._fps)
        for pkt in self._vstream.encode(vframe):
            self._container.mux(pkt)

    def _combine(self, frames: Sequence["np.ndarray | None"]) -> np.ndarray:
        panels = [
            _letterbox(f, self._pw, self._ph)
            if f is not None
            else np.zeros((self._ph, self._pw, 3), np.uint8)
            for f in frames
        ]
        if not panels:
            panels = [np.zeros((self._ph, self._pw, 3), np.uint8)]
        return np.hstack(panels)

    def _encode_audio(self, a_pts: int, final: bool = False) -> int:
        while True:
            try:
                block = self._audio_q.get_nowait()
            except queue.Empty:
                break
            aframe = av.AudioFrame.from_ndarray(
                block.reshape(1, -1), format="s16", layout="mono"
            )
            aframe.sample_rate = self._samplerate
            self._write_resampled(aframe)

        if final and self._resampler is not None:
            self._write_resampled(None)  # flush the resampler

        frame_size = self._astream.codec_context.frame_size or 1024
        while self._fifo.samples >= frame_size:
            a_pts = self._mux_audio(self._fifo.read(frame_size), a_pts)
        if final:
            remaining = self._fifo.read()
            if remaining is not None:
                a_pts = self._mux_audio(remaining, a_pts)
        return a_pts

    def _write_resampled(self, aframe) -> None:  # noqa: ANN001
        resampled = self._resampler.resample(aframe)
        if resampled is None:
            return
        if not isinstance(resampled, list):
            resampled = [resampled]
        for rf in resampled:
            self._fifo.write(rf)

    def _mux_audio(self, out, a_pts: int) -> int:  # noqa: ANN001
        out.pts = a_pts
        out.time_base = Fraction(1, self._samplerate)
        out.sample_rate = self._samplerate
        for pkt in self._astream.encode(out):
            self._container.mux(pkt)
        return a_pts + out.samples

    def _close_container(self) -> None:
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
        self._vstream = None
        self._astream = None
        self._fifo = None
        self._resampler = None
