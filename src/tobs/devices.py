"""Video capture device discovery helpers (macOS focused, cross-platform safe)."""

from __future__ import annotations

import json
import platform
import subprocess
import time
from dataclasses import dataclass

import cv2


@dataclass
class DeviceInfo:
    index: int
    width: int
    height: int
    name: str = ""

    @property
    def label(self) -> str:
        res = f"{self.width}x{self.height}" if self.width else "unknown"
        name = f" - {self.name}" if self.name else ""
        return f"[{self.index}] {res}{name}"


def _macos_camera_names() -> list[str]:
    """Return camera product names in the order macOS reports them.

    The order roughly follows the OpenCV/AVFoundation device index order, so we
    use it as a best-effort label. It is not guaranteed to be exact.
    """
    try:
        out = subprocess.run(
            ["system_profiler", "-json", "SPCameraDataType"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        data = json.loads(out)
        items = data.get("SPCameraDataType", [])
        return [it.get("_name", "") for it in items]
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return []


def _windows_camera_names() -> list[str]:
    """Return DirectShow device names on Windows if pygrabber is available."""
    try:
        from pygrabber.dshow_graph import FilterGraph  # type: ignore

        return list(FilterGraph().get_input_devices())
    except Exception:
        return []


def _camera_names() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        return _macos_camera_names()
    if system == "Windows":
        return _windows_camera_names()
    return []


def _capture_backends() -> list[int]:
    system = platform.system()
    if system == "Darwin":
        return [cv2.CAP_AVFOUNDATION]
    if system == "Windows":
        # Some cameras (notably the GoPro Webcam) only work under one backend.
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF]
    return [cv2.CAP_ANY]


def _probe(idx: int, api: int, reads: int = 6) -> tuple[int, int] | None:
    """Open a device index and return its (width, height) if it yields a frame.

    Reads a few times because some webcams (e.g. the GoPro Webcam virtual
    camera) need a brief warm-up before delivering the first frame.
    """
    cap = cv2.VideoCapture(idx, api)
    try:
        if not cap.isOpened():
            return None
        for _ in range(reads):
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                return w, h
            time.sleep(0.05)
        return None
    finally:
        cap.release()


def enumerate_devices(max_index: int = 10) -> list[DeviceInfo]:
    """List capture devices, keeping OS-named cameras even if slow to start.

    Devices the OS reports by name (via pygrabber on Windows / system_profiler
    on macOS) are always listed — even when a quick probe returns no frame — so
    slow-to-initialize cameras like the GoPro Webcam remain selectable.
    """
    names = _camera_names()
    backends = _capture_backends()

    found: list[DeviceInfo] = []
    seen: set[int] = set()

    for idx, name in enumerate(names):
        res = None
        for api in backends:
            res = _probe(idx, api)
            if res:
                break
        w, h = res if res else (0, 0)
        found.append(DeviceInfo(index=idx, width=w, height=h, name=name))
        seen.add(idx)

    # Probe any remaining indices the OS did not name (primary backend only).
    # Indices are contiguous, so stop at the first gap to avoid noisy probes.
    for idx in range(max_index):
        if idx in seen:
            continue
        res = _probe(idx, backends[0])
        if not res:
            break
        w, h = res
        found.append(DeviceInfo(index=idx, width=w, height=h))

    found.sort(key=lambda d: d.index)
    return found
