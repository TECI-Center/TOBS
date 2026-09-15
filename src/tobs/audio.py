"""Microphone discovery helpers (cross-platform safe)."""

from __future__ import annotations

from dataclasses import dataclass

try:  # sounddevice is optional; the app still runs (video-only) without it.
    import sounddevice as sd
except Exception:  # pragma: no cover - import guard
    sd = None


@dataclass
class AudioDevice:
    index: int
    name: str
    channels: int
    samplerate: int

    @property
    def label(self) -> str:
        return f"[{self.index}] {self.name}"


def audio_available() -> bool:
    """True when a microphone backend (sounddevice/PortAudio) is importable."""
    return sd is not None


def enumerate_microphones() -> list[AudioDevice]:
    """Return input-capable audio devices, or an empty list if none/unavailable."""
    if sd is None:
        return []
    mics: list[AudioDevice] = []
    try:
        for idx, info in enumerate(sd.query_devices()):
            if int(info.get("max_input_channels", 0)) <= 0:
                continue
            rate = int(info.get("default_samplerate", 0) or 0) or 44100
            mics.append(
                AudioDevice(
                    index=idx,
                    name=str(info.get("name", f"device {idx}")).strip(),
                    channels=int(info.get("max_input_channels", 1)),
                    samplerate=rate,
                )
            )
    except Exception:
        return []
    return mics
