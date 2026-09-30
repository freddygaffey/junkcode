#!/usr/bin/env python3
"""
Live transcription — words appear while you are still talking.

Whisper is a batch model: it transcribes a finished recording. Apple's dictation
and Dragon feel instant because they are streaming models. This module gets the
same behaviour out of a batch model.

The method is local agreement. Every interval we re-transcribe the audio so far,
which produces a slightly different guess each time as more context arrives. Text
is only emitted once two consecutive guesses agree on it. Anything still changing
is held back.

The consequence is that emitted text is never retracted. You do not get the
flicker of words rewriting themselves, at the cost of running roughly one
interval behind your voice.
"""
from __future__ import annotations

import threading
import time

import numpy as np

SAMPLE_RATE = 16000

# Whisper invents text when fed silence or room tone - "and the", "...", "Thank
# you.", "you". In live mode that means words appearing in your document every
# time you pause, so silence is gated out before it ever reaches the model.
SILENCE_RMS = 0.006

# Phrases Whisper commonly emits for non-speech audio. Matched on a whole pass,
# never on a substring, so genuine uses of these words survive.
HALLUCINATIONS = {
    "you", "thank you.", "thank you", "thanks for watching!", "bye.", "bye",
    ".", "...", "the", "and the", "so", "okay.", "oh.", "yeah.", "hmm.",
    "subtitles by the amara.org community", "please subscribe!",
}


def _words(text: str) -> list[str]:
    return text.split()


def _is_hallucination(text: str) -> bool:
    stripped = text.strip().lower()
    if not stripped:
        return True
    if stripped in HALLUCINATIONS:
        return True
    # Nothing but dots, commas and spaces carries no information.
    return not any(c.isalnum() for c in stripped)


def _rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def _common_prefix(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b):
        if x.strip(".,!?;:").lower() != y.strip(".,!?;:").lower():
            break
        n += 1
    return n


class StreamingTranscriber:
    """Feed audio in, get confirmed words out."""

    def __init__(self, backend, language: str = "en", initial_prompt: str | None = None,
                 interval: float = 1.4, max_buffer_s: float = 28.0,
                 on_words=None):
        self.backend = backend
        self.language = language
        self.initial_prompt = initial_prompt
        self.interval = interval
        self.max_buffer_s = max_buffer_s
        self.on_words = on_words or (lambda _w: None)

        self._buf = np.zeros(0, dtype="float32")
        self._lock = threading.Lock()
        self._prev: list[str] = []
        self._committed_in_buf = 0
        self._all: list[str] = []
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def add_audio(self, chunk: np.ndarray) -> None:
        with self._lock:
            self._buf = np.concatenate([self._buf, chunk.astype("float32")])

    def finish(self) -> str:
        """Stop, transcribe whatever is left, return the complete text."""
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=20)
        self._flush(final=True)
        return " ".join(self._all).strip()

    # ------------------------------------------------------------------ internals
    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.interval)
            if self._stop.is_set():
                break
            try:
                self._flush(final=False)
            except Exception as exc:              # noqa: BLE001 - never kill the stream
                print(f"  [streaming] {type(exc).__name__}: {exc}")

    def _flush(self, final: bool) -> None:
        with self._lock:
            audio = self._buf.copy()
        if len(audio) < SAMPLE_RATE * 0.4:        # under 0.4s is not worth a pass
            return

        # Gate on loudness before spending a transcription pass. This is both a
        # correctness fix (no invented words) and a large saving in compute,
        # since most of a dictation session is pauses.
        if _rms(audio) < SILENCE_RMS:
            return

        text = self.backend.transcribe(audio, self.language, self.initial_prompt)
        if _is_hallucination(text):
            return
        words = _words(text)
        if not words:
            return

        if final:
            stable = len(words)
        else:
            # Only trust what this pass and the previous one both produced.
            stable = _common_prefix(self._prev, words)

        new = words[self._committed_in_buf:stable]
        if new:
            self._all.extend(new)
            self._committed_in_buf = stable
            self.on_words(new)

        self._prev = words

        # Whisper's context window is 30s. Past that, commit and start a fresh
        # buffer rather than re-transcribing an ever-growing recording.
        if not final and len(audio) > SAMPLE_RATE * self.max_buffer_s:
            leftover = words[self._committed_in_buf:]
            if leftover:
                self._all.extend(leftover)
                self.on_words(leftover)
            with self._lock:
                self._buf = np.zeros(0, dtype="float32")
            self._prev = []
            self._committed_in_buf = 0
