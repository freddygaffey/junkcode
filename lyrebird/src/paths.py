#!/usr/bin/env python3
"""
Where things live.

Running from source, config sits in the repo. Inside a packaged .app or .exe the
bundle is read-only, so config has to move somewhere writable in the user's profile.
This module hides that difference from the rest of the code.

  macOS    ~/Library/Application Support/local-dictation/
  Windows  %APPDATA%\\local-dictation\\
  Linux    ~/.config/local-dictation/
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Lyrebird"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def bundled_dir() -> Path:
    """Read-only directory holding the shipped default config."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_dir() -> Path:
    """Writable per-user directory for settings."""
    if not is_frozen():
        return bundled_dir()                       # dev: keep everything in the repo
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def config_dir() -> Path:
    return user_dir() / "config"


def ensure_user_config() -> Path:
    """Seed the user's config from the bundled defaults on first run.

    Never overwrites an existing file: an upgrade must not discard someone's
    carefully built word list.
    """
    target = config_dir()
    target.mkdir(parents=True, exist_ok=True)
    source = bundled_dir() / "config"
    if source.exists():
        for name in ("config.ini", "dictionary.txt"):
            src, dst = source / name, target / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
    return target
