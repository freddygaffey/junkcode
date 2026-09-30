#!/usr/bin/env python3
"""
Microphone capture, with a fallback for Linux boxes that lack PortAudio.

sounddevice is the good path: cross-platform, callback-driven, low latency. But
it needs libportaudio, which on Linux means root to install. Plenty of machines
- servers, locked-down work laptops, containers - do not have it and will not be
getting it.

So on Linux we fall back to piping raw PCM out of `arecord`, which ships with
alsa-utils and is present almost everywhere. Same interface, no root required.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading

import numpy as np


def has_sounddevice() -> bool:
    try:
        import sounddevice  # noqa: F401
        return True
    except Exception:
        return False


def has_arecord() -> bool:
    return sys.platform.startswith("linux") and shutil.which("arecord") is not None


def backend_name() -> str:
    if has_sounddevice():
        return "sounddevice"
    if has_arecord():
        return "arecord"
    return "none"


def describe() -> str:
    name = backend_name()
    return {
        "sounddevice": "PortAudio (sounddevice)",
        "arecord": "ALSA (arecord) - PortAudio not installed",
        "none": "no capture backend available",
    }[name]


class BaseCapture:
    def start(self) -> None: raise NotImplementedError
    def stop(self) -> np.ndarray | None: raise NotImplementedError


class SoundDeviceCapture(BaseCapture):
    def __init__(self, sample_rate: int, channels: int, on_chunk=None):
        self.sample_rate, self.channels, self.on_chunk = sample_rate, channels, on_chunk
        self._frames: list[np.ndarray] = []
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        self._frames = []

        def callback(indata, frames, time_info, status):
            block = indata.copy()
            self._frames.append(block)
            if self.on_chunk:
                mono = block.mean(axis=1) if block.ndim > 1 else block
                self.on_chunk(mono.astype("float32"))

        self._stream = sd.InputStream(samplerate=self.sample_rate,
                                      channels=self.channels, dtype="float32",
                                      callback=callback)
        self._stream.start()

    def stop(self) -> np.ndarray | None:
        if self._stream is not None:
            self._stream.stop(); self._stream.close(); self._stream = None
        if not self._frames:
            return None
        audio = np.concatenate(self._frames, axis=0)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio.astype("float32")


class ARecordCapture(BaseCapture):
    """Raw 16-bit PCM piped out of arecord, read on a worker thread."""

    CHUNK_FRAMES = 1600                      # 0.1s at 16kHz

    def __init__(self, sample_rate: int, channels: int, on_chunk=None,
                 device: str = "default"):
        self.sample_rate, self.channels, self.on_chunk = sample_rate, channels, on_chunk
        self.device = device
        self._proc: subprocess.Popen | None = None
        self._frames: list[np.ndarray] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._frames = []
        self._stop.clear()
        self._proc = subprocess.Popen(
            ["arecord", "-D", self.device, "-f", "S16_LE",
             "-r", str(self.sample_rate), "-c", str(self.channels), "-t", "raw", "-q"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        want = self.CHUNK_FRAMES * self.channels * 2      # bytes
        while not self._stop.is_set() and self._proc and self._proc.stdout:
            raw = self._proc.stdout.read(want)
            if not raw:
                break
            block = np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
            if self.channels > 1:
                block = block.reshape(-1, self.channels).mean(axis=1)
            self._frames.append(block)
            if self.on_chunk:
                self.on_chunk(block)

    def stop(self) -> np.ndarray | None:
        self._stop.set()
        if self._proc:
            try:
                self._proc.terminate(); self._proc.wait(timeout=3)
            except Exception:                    # noqa: BLE001
                self._proc.kill()
            self._proc = None
        if self._thread:
            self._thread.join(timeout=3)
        if not self._frames:
            return None
        return np.concatenate(self._frames).astype("float32")


def build(sample_rate: int, channels: int, on_chunk=None) -> BaseCapture:
    if has_sounddevice():
        return SoundDeviceCapture(sample_rate, channels, on_chunk)
    if has_arecord():
        return ARecordCapture(sample_rate, channels, on_chunk)
    raise RuntimeError(
        "No audio capture available. Install PortAudio "
        "(macOS: brew install portaudio, Linux: apt install portaudio19-dev) "
        "or alsa-utils for the arecord fallback."
    )
