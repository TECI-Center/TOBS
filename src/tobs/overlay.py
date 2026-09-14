"""Timestamp overlay drawing utilities."""

from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def timestamp_text() -> str:
    """Return the current local time formatted for display."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def draw_timestamp(
    frame: np.ndarray,
    label: str | None = None,
    corner: str = "bottom-left",
) -> np.ndarray:
    """Burn the current timestamp (and optional label) onto ``frame`` in place.

    The text is drawn with a dark outline so it stays readable over any
    background. ``frame`` is modified and also returned for convenience.
    """
    text = timestamp_text()
    if label:
        text = f"{label}  {text}"

    h, w = frame.shape[:2]
    # Scale text to the frame width so it stays legible on any resolution.
    scale = max(0.5, w / 1280.0)
    thickness = max(1, int(round(scale * 2)))
    (tw, th), baseline = cv2.getTextSize(text, _FONT, scale, thickness)

    margin = int(12 * scale)
    if "top" in corner:
        y = th + margin
    else:
        y = h - margin
    if "right" in corner:
        x = w - tw - margin
    else:
        x = margin

    # Outline (drawn thicker & darker) then the bright text on top.
    cv2.putText(frame, text, (x, y), _FONT, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), _FONT, scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return frame
