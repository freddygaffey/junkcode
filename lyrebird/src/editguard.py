#!/usr/bin/env python3
"""
Do not type over someone who is editing.

Live dictation injects keystrokes into whatever has focus. If the user is
mid-correction - cursor moved, a word selected, halfway through retyping
something - a burst of transcribed text landing at the caret destroys the edit
and is very hard to undo.

So watch for human input. While the user is typing or clicking, hold transcribed
words in a queue. Release them once they have been still for a moment, or
immediately on an explicit resume.

The user always wins: their keystrokes are never delayed, never swallowed, and
never competed with.
"""
from __future__ import annotations

import threading
import time


class EditGuard:
    """Holds output back while the user is editing."""

    def __init__(self, idle_seconds: float = 1.2, on_flush=None,
                 on_state=None):
        self.idle_seconds = idle_seconds
        self.on_flush = on_flush or (lambda _text: None)
        self.on_state = on_state or (lambda _held: None)

        self._queue: list[str] = []
        self._lock = threading.Lock()
        self._last_input = 0.0
        self._paused = False
        self._stop = threading.Event()
        self._listener = None
        self._worker: threading.Thread | None = None
        self._own_output_until = 0.0

    # ------------------------------------------------------------------ control
    def start(self) -> bool:
        try:
            from pynput import keyboard, mouse
        except Exception:
            return False

        def on_key(_key):
            self._note_input()

        def on_click(_x, _y, _button, _pressed):
            self._note_input()

        self._listener = keyboard.Listener(on_press=on_key)
        self._listener.start()
        self._mouse = mouse.Listener(on_click=on_click)
        self._mouse.start()

        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        for l in (getattr(self, "_listener", None), getattr(self, "_mouse", None)):
            try:
                if l:
                    l.stop()
            except Exception:                      # noqa: BLE001
                pass
        self.flush()

    def pause(self) -> None:
        """Hold all output until resumed. For deliberate editing."""
        self._paused = True
        self.on_state(True)

    def resume(self) -> None:
        self._paused = False
        self.flush()
        self.on_state(False)

    @property
    def paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------- input
    def _note_input(self) -> None:
        # Ignore the keystrokes we synthesise ourselves, or the guard would
        # treat its own typing as the user editing and never release anything.
        if time.monotonic() < self._own_output_until:
            return
        self._last_input = time.monotonic()

    def expect_own_output(self, seconds: float) -> None:
        self._own_output_until = time.monotonic() + seconds

    # ------------------------------------------------------------------ output
    def submit(self, text: str) -> None:
        """Offer transcribed text. Typed now, or queued if the user is busy."""
        if not text:
            return
        if self._can_type():
            self._write(text)
        else:
            with self._lock:
                self._queue.append(text)
                held = len(self._queue)
            self.on_state(True)
            if held == 1:
                print("  [hold] you are editing — text is waiting", flush=True)

    def _can_type(self) -> bool:
        if self._paused:
            return False
        return (time.monotonic() - self._last_input) >= self.idle_seconds

    def _write(self, text: str) -> None:
        # Reserve a window so our own keystrokes are not mistaken for the user's.
        self.expect_own_output(0.4 + len(text) * 0.01)
        self.on_flush(text)

    def flush(self) -> None:
        with self._lock:
            pending, self._queue = self._queue, []
        if pending:
            self._write(" ".join(pending))
            self.on_state(False)

    def _drain(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.2)
            if self._paused:
                continue
            with self._lock:
                waiting = bool(self._queue)
            if waiting and self._can_type():
                self.flush()
                print("  [resume] typing what you missed", flush=True)
