#!/usr/bin/env python3
"""
Menu bar / system tray indicator.

Dictation is global: it works in whatever application has focus, which means the
app itself is usually invisible. Without an indicator there is no way to tell
whether it is listening, and a microphone you cannot see the state of is one you
will not trust.

  macOS   -> menu bar item
  Windows -> system tray icon
  Linux   -> tray icon (AppIndicator/GTK where available)

Three states: idle (dim), listening (accent), busy (warm).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INK = (18, 26, 24)
DIM = (128, 140, 136)
LISTENING = (31, 111, 107)
BUSY = (201, 123, 60)

STATES = {"idle": DIM, "listening": LISTENING, "busy": BUSY}


def _icon_image(state: str, size: int = 64):
    """A microphone glyph, tinted by state.

    Drawn rather than loaded from a file so it stays crisp at any menu bar
    scaling and needs no asset shipped alongside the binary.
    """
    from PIL import Image, ImageDraw

    colour = STATES.get(state, DIM)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0

    # capsule body
    d.rounded_rectangle([24 * s, 12 * s, 40 * s, 38 * s],
                        radius=8 * s, fill=colour)
    # cradle arc
    d.arc([18 * s, 24 * s, 46 * s, 48 * s], start=0, end=180,
          fill=colour, width=int(max(2, 4 * s)))
    # stem and base
    d.rectangle([30.5 * s, 44 * s, 33.5 * s, 52 * s], fill=colour)
    d.rounded_rectangle([23 * s, 51 * s, 41 * s, 55 * s],
                        radius=2 * s, fill=colour)

    if state == "listening":
        # a filled dot reads as "live" at 16px, where fine detail disappears
        d.ellipse([46 * s, 8 * s, 60 * s, 22 * s], fill=BUSY)
    return img


class Indicator:
    """Runs the tray icon on its own thread and exposes set_state()."""

    def __init__(self, on_settings=None, on_quit=None, on_toggle=None):
        self.on_settings = on_settings
        self.on_quit = on_quit
        self.on_toggle = on_toggle
        self._icon = None
        self._thread: threading.Thread | None = None
        self._state = "idle"

    def available(self) -> bool:
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> bool:
        if not self.available():
            print("[tray] pystray not available - running without an indicator",
                  file=sys.stderr)
            return False
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Lyrebird", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start / stop dictation",
                             lambda *_: self.on_toggle and self.on_toggle()),
            pystray.MenuItem("Settings…",
                             lambda *_: self.on_settings and self.on_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon("lyrebird", _icon_image("idle"), "Lyrebird", menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        return True

    def set_state(self, state: str) -> None:
        """idle | listening | busy"""
        if state == self._state or self._icon is None:
            return
        self._state = state
        try:
            self._icon.icon = _icon_image(state)
            self._icon.title = {
                "idle": "Lyrebird — ready",
                "listening": "Lyrebird — listening",
                "busy": "Lyrebird — transcribing",
            }.get(state, "Lyrebird")
        except Exception:                          # noqa: BLE001
            pass

    def _quit(self, *_):
        try:
            if self.on_quit:
                self.on_quit()
        finally:
            if self._icon:
                self._icon.stop()

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:                      # noqa: BLE001
                pass


def preview() -> None:
    """Write the three states to build/icon/ so they can be eyeballed."""
    out = ROOT / "build" / "icon"
    out.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    strip = Image.new("RGBA", (64 * 3 + 40, 80), (245, 247, 244, 255))
    for i, st in enumerate(("idle", "listening", "busy")):
        img = _icon_image(st)
        strip.paste(img, (10 + i * 74, 8), img)
    strip.save(out / "tray-states.png")
    print(f"wrote {out / 'tray-states.png'}")


if __name__ == "__main__":
    preview()
