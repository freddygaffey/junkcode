#!/usr/bin/env python3
"""
Desktop entry point — the thing a non-technical user double-clicks.

Starts the settings server on a free local port, opens it in a native window
(WKWebView on macOS, WebView2 on Windows), and runs the dictation listener in
the background. No terminal, no command line.

    python src/app.py              # native window
    python src/app.py --browser    # use the default browser instead
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import paths  # noqa: E402
import tray as tray_mod  # noqa: E402

APP_NAME = "Lyrebird"          # <- change here to rename everywhere
WINDOW_W, WINDOW_H = 900, 860


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def start_settings_server(port: int) -> None:
    import webui

    threading.Thread(
        target=lambda: webui.app.run(host="127.0.0.1", port=port,
                                     debug=False, use_reloader=False),
        daemon=True,
    ).start()


def start_dictation(indicator=None) -> None:
    """Run the hotkey listener in the background.

    Deliberately non-fatal: if the microphone or Accessibility permission is
    missing, the settings window must still open so the user can see why.
    """
    def runner() -> None:
        try:
            import dictate

            cfg = dictate.load_config()
            if indicator is not None:
                dictate.STATE_HOOK = indicator.set_state
            dictate.run_listener(cfg)
        except Exception as exc:                  # noqa: BLE001
            print(f"[dictation] not started: {type(exc).__name__}: {exc}", file=sys.stderr)
            if indicator is not None:
                indicator.set_state("idle")

    threading.Thread(target=runner, daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} — offline dictation.")
    ap.add_argument("--browser", action="store_true",
                    help="open in the default browser instead of a native window")
    ap.add_argument("--no-dictation", action="store_true",
                    help="settings only; do not start the hotkey listener")
    ap.add_argument("--no-tray", action="store_true",
                    help="do not show the menu bar indicator")
    # Ignore anything we do not recognise: a frozen app can be re-launched by the
    # OS or a child process with extra argv, and a hard argparse exit would kill it.
    args, _unknown = ap.parse_known_args()

    paths.ensure_user_config()
    port = free_port()
    start_settings_server(port)

    if not wait_for_server(port):
        sys.exit("Settings server failed to start.")

    indicator = None
    if not args.no_tray:
        indicator = tray_mod.Indicator(
            on_settings=lambda: __import__("webbrowser").open(f"http://127.0.0.1:{port}"),
            on_quit=lambda: os._exit(0),
        )
        if not indicator.start():
            indicator = None

    if not args.no_dictation:
        start_dictation(indicator)

    url = f"http://127.0.0.1:{port}"
    if args.browser:
        import webbrowser

        webbrowser.open(url)
        print(f"{APP_NAME} running at {url}\nPress Ctrl+C to quit.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    import webview

    webview.create_window(APP_NAME, url, width=WINDOW_W, height=WINDOW_H,
                          min_size=(720, 560))
    webview.start()          # blocks until the window closes


if __name__ == "__main__":
    # Without this, PyInstaller re-executes this entry point in every child
    # process a library spawns, and the app restarts itself in a loop.
    multiprocessing.freeze_support()
    main()
