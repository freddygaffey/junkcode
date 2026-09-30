#!/usr/bin/env python3
"""
Acceptance test for the packaged application.

Checks the built .app/.exe the way a user meets it, rather than testing the
source it was built from. Packaging is where this project has broken repeatedly:
a missing Metal library, an over-eager exclude, a re-entrant entry point. Every
one of those passed the source tests and shipped broken.

    python build/acceptance.py                      # test the installed app
    python build/acceptance.py --app path/to/App    # test a specific build
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

results: list[tuple[str, bool | None, str]] = []


def check(name: str, ok: bool | None, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = {True: f"{GREEN}PASS{RESET}", False: f"{RED}FAIL{RESET}",
            None: f"{YELLOW}SKIP{RESET}"}[ok]
    print(f"  {mark}  {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""))


def find_binary(app: Path) -> Path | None:
    if sys.platform == "darwin" and app.suffix == ".app":
        cands = list((app / "Contents" / "MacOS").glob("*"))
        return cands[0] if cands else None
    exe = app / (app.name + ".exe")
    return exe if exe.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    default = ("/Applications/Lyrebird.app" if sys.platform == "darwin"
               else str(ROOT / "dist" / "Lyrebird"))
    ap.add_argument("--app", default=default)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()
    app = Path(args.app)

    print(f"\nAcceptance test: {app}\n")

    # ---------------------------------------------------------------- bundle
    check("bundle exists", app.exists(), str(app))
    if not app.exists():
        return 1

    binary = find_binary(app)
    check("executable present", binary is not None and binary.exists(),
          binary.name if binary else "not found")
    if binary is None:
        return 1

    if sys.platform == "darwin":
        metallib = list(app.rglob("*.metallib"))
        big = [m for m in metallib if m.stat().st_size > 10_000_000]
        check("Metal shader library bundled", bool(big),
              f"{big[0].stat().st_size // 1048576} MB" if big else
              "missing - GPU backend will silently fall back to CPU")

        packs = list(app.rglob("config/packs/*.txt"))
        check("vocabulary packs bundled", len(packs) >= 5, f"{len(packs)} packs")

        sig = subprocess.run(["codesign", "-dv", str(app)],
                             capture_output=True, text=True)
        check("code signature", "Identifier=" in sig.stderr,
              "ad-hoc" if "adhoc" in sig.stderr else "signed")

    # ---------------------------------------------------------------- launch
    print()
    env = dict(os.environ, LYREBIRD_DEBUG="1")
    proc = subprocess.Popen([str(binary), "--browser"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    port, log = None, []
    deadline = time.monotonic() + args.timeout
    ready = False
    try:
        while time.monotonic() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            log.append(line.rstrip())
            m = re.search(r"127\.0\.0\.1:(\d+)", line)
            if m and port is None:
                port = int(m.group(1))
            if "Ready. Hotkey" in line or "Model ready" in line:
                ready = True
            if port and ready:
                break

        joined = "\n".join(log)
        check("settings server started", port is not None,
              f"port {port}" if port else "no port in output")

        if port:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
                    html = r.read().decode()
                check("settings page responds", r.status == 200, f"HTTP {r.status}")
                for probe, label in [("Live typing", "live typing control"),
                                     ("My word list", "vocabulary editor"),
                                     ("Simple", "simple/expert toggle")]:
                    check(f"page contains {label}", probe in html)
            except Exception as exc:
                check("settings page responds", False, f"{type(exc).__name__}: {exc}")

        # the failures that actually shipped
        check("speech backend loaded", "Loading" in joined and "unavailable" not in joined,
              "MLX/CUDA unavailable - fell back" if "unavailable" in joined else "")
        check("dictation listener started", "[dictation] not started" not in joined,
              next((l for l in log if "not started" in l), "")[:60])
        check("accessibility trust", "not trusted" not in joined,
              "not granted - hotkey will not fire" if "not trusted" in joined else "granted")
        check("no entry-point re-entry", "usage:" not in joined,
              "app restarted itself" if "usage:" in joined else "")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    # ---------------------------------------------------------------- summary
    passed = sum(1 for _, ok, _ in results if ok is True)
    failed = sum(1 for _, ok, _ in results if ok is False)
    print(f"\n  {passed} passed, {failed} failed\n")
    if failed:
        print("  Failures:")
        for name, ok, detail in results:
            if ok is False:
                print(f"    - {name}: {detail or 'see log'}")
        print()
        print("  Last lines of app output:")
        for line in log[-12:]:
            print(f"    {DIM}{line}{RESET}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
