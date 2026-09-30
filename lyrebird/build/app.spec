# PyInstaller spec — builds the desktop app for macOS and Windows.
# Driven by build/build-macos.sh or build/build-windows.ps1.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_NAME = os.environ.get("APP_NAME", "Lyrebird")
ROOT = Path(os.environ.get("PROJECT_ROOT", os.getcwd()))

ICON_DIR = ROOT / "build" / "icon"
ICON_MAC = ICON_DIR / "icon.icns"
ICON_WIN = ICON_DIR / "icon.ico"

hidden = (
    collect_submodules("faster_whisper")
    + collect_submodules("mlx_whisper")
    + collect_submodules("webview")
    + collect_submodules("mlx_lm")
    + collect_submodules("mlx")
    + ["flask", "pynput", "sounddevice", "requests", "ctranslate2",
       # local modules imported dynamically, which Analysis cannot see
       "paths", "backends", "capture", "cleanup", "streaming", "tray",
       "dictate", "webui", "benchmark"]
)

datas = [
    (str(ROOT / "config" / "config.ini"), "config"),
    (str(ROOT / "config" / "dictionary.txt"), "config"),
]
for pack in sorted((ROOT / "config" / "packs").glob("*.txt")):
    datas.append((str(pack), "config/packs"))
datas += collect_data_files("faster_whisper")
datas += collect_data_files("mlx_whisper")
datas += collect_data_files("webview")

# MLX ships its Metal shaders as a separate 174MB .metallib that PyInstaller's
# analysis does not see, because nothing imports it - it is loaded at runtime by
# the native library. Without it MLX cannot initialise the GPU and the app falls
# back to "MLX unavailable", silently losing the 5.5x speedup.
# mlx is a namespace package, so __file__ is None - __path__ is the only way in.
# Failing silently here ships a bundle that cannot use the GPU, so be loud.
try:
    import mlx
    mlx_lib = Path(list(mlx.__path__)[0]) / "lib"
    found = []
    for pattern in ("*.metallib", "*.dylib"):
        for f in sorted(mlx_lib.glob(pattern)):
            datas.append((str(f), "mlx/lib"))
            found.append(f.name)
    if not any(n.endswith(".metallib") for n in found):
        raise RuntimeError(f"no .metallib found in {mlx_lib}")
    print(f"[spec] bundling MLX Metal libraries: {', '.join(found)}")
except ImportError:
    print("[spec] mlx not installed - building without GPU support")
except Exception as exc:
    raise SystemExit(f"[spec] MLX present but unusable: {exc}")

a = Analysis(
    [str(ROOT / "src" / "app.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    # torch is a declared dependency of mlx-whisper but is never touched at
    # runtime - verified by blocking the import and transcribing successfully.
    # Excluding it removes ~511MB from the bundle.
    excludes=[
        "torch", "torchvision", "torchaudio",
        "tkinter", "matplotlib", "pytest", "IPython", "notebook",
        # NOTE: scipy must NOT be excluded - mlx_whisper.timing imports it, and
        # excluding it silently disables the entire Metal backend.
        "pandas", "transformers", "datasets",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_WIN) if ICON_WIN.exists() else None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name=APP_NAME,
)

import sys
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ICON_MAC) if ICON_MAC.exists() else None,
        bundle_identifier=f"com.freddygaffey.{APP_NAME.lower()}",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            # Both are mandatory or macOS silently denies access with no error.
            "NSMicrophoneUsageDescription":
                f"{APP_NAME} needs the microphone to turn your speech into text. "
                "Audio never leaves this Mac.",
            "NSAppleEventsUsageDescription":
                f"{APP_NAME} types the transcribed text into the app you are using.",
        },
    )
