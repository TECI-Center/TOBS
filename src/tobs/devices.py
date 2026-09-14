"""Video capture device discovery helpers (macOS focused, cross-platform safe)."""

from __future__ import annotations

import json
import platform
import subprocess
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


def _capture_backend() -> int:
    system = platform.system()
    if system == "Darwin":
        return cv2.CAP_AVFOUNDATION
    if system == "Windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def enumerate_devices(max_index: int = 8) -> list[DeviceInfo]:
    """Probe capture device indices and return the ones that open successfully."""
    names = _camera_names()
    api = _capture_backend()

    found: list[DeviceInfo] = []
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, api)
        try:
            if not cap.isOpened():
                continue
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            name = names[len(found)] if len(found) < len(names) else ""
            found.append(DeviceInfo(index=idx, width=w, height=h, name=name))
        finally:
            cap.release()
    return found
