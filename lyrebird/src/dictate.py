#!/usr/bin/env python3
"""
local-dictation — offline push-to-talk / toggle dictation.

Pipeline:  mic -> faster-whisper (local) -> [optional] Ollama (local) -> focused text field

Everything runs on this machine. Nothing is uploaded.

Usage:
    python src/dictate.py              # grab a global hotkey (macOS, Windows)
    python src/dictate.py --daemon     # stay resident, model loaded (Linux)
    python src/dictate.py --toggle     # tell the daemon to start/stop, then exit
    python src/dictate.py --check      # diagnose the install, change nothing
    python src/dictate.py --once       # record one utterance, print it, exit
    python src/dictate.py --devices    # list audio input devices

Two front ends, because the platforms want different things:

  macOS / Windows   this process grabs a global hotkey with pynput.
  Linux             the window manager binds the key and runs `--toggle`, which
                    signals a resident `--daemon`. The WM already owns key
                    binding, so grabbing one here would be a second thing
                    fighting for the same key — and pynput's X11 grab does not
                    work under Wayland at all. The daemon exists because loading
                    large-v3-turbo takes seconds; it cannot happen per keypress.
"""
from __future__ import annotations

import argparse
import configparser
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"  # replaced at runtime by paths.config_dir()
sys.path.insert(0, str(ROOT / "src"))

import backends  # noqa: E402  (needs sys.path set above)
import capture as capture_mod  # noqa: E402
import cleanup as cleanup_mod  # noqa: E402
import editguard as editguard_mod  # noqa: E402
import streaming as streaming_mod  # noqa: E402
import paths  # noqa: E402


# --------------------------------------------------------------------------- config
def load_config() -> configparser.ConfigParser:
    """Load config.ini, then overlay config.local.ini if present (gitignored)."""
    cfg = configparser.ConfigParser()
    paths.ensure_user_config()
    base = paths.config_dir() / "config.ini"
    if not base.exists():
        sys.exit(f"Missing config file: {base}")
    cfg.read(base)
    local = paths.config_dir() / "config.local.ini"
    if local.exists():
        cfg.read(local)
    return cfg


def load_dictionary() -> str:
    """Dictionary terms as a comma-separated Whisper `initial_prompt`.

    Whisper has no formal custom-vocabulary API; the initial prompt biases decoding
    towards the words it contains. Cheapest, most effective accuracy win available.
    """
    return backends.load_dictionary()


# --------------------------------------------------------------------------- audio
class Recorder:
    """Buffers microphone input until stopped.

    Delegates to capture.py, which uses PortAudio where present and falls back
    to piping arecord on Linux machines that do not have it.
    """

    def __init__(self, sample_rate: int, channels: int, max_seconds: int,
                 on_chunk=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_seconds = max_seconds
        self.on_chunk = on_chunk
        self._impl = None
        self._started_at = 0.0

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._impl = capture_mod.build(
            self.sample_rate, self.channels,
            on_chunk=lambda c: self.on_chunk(c) if self.on_chunk else None,
        )
        self._impl.start()

    def stop(self):
        if self._impl is None:
            return None
        audio = self._impl.stop()
        self._impl = None
        return audio


# --------------------------------------------------------------------- transcription
class Transcriber:
    """Loads the configured backend once and reuses it."""

    def __init__(self, cfg: configparser.ConfigParser):
        section = cfg["transcription"]
        model = section.get("model", "large-v3-turbo")
        requested = section.get("backend", "auto")
        resolved = backends.resolve_backend(requested)

        print(f"Loading '{model}' on {resolved} backend"
              f"{'' if requested == resolved else f' (auto-selected from {requested})'}...")
        t0 = time.monotonic()
        self.backend = backends.build(
            requested,
            model,
            device=section.get("device", "auto"),
            compute_type=section.get("compute_type", "auto"),
            cpu_threads=section.getint("cpu_threads", 0),
        )
        try:
            self.backend.warm()
        except Exception as exc:            # noqa: BLE001 - warming is best-effort
            print(f"  (warm-up skipped: {exc})", file=sys.stderr)
        print(f"Model ready in {time.monotonic() - t0:.1f}s")

        self.language = section.get("language", "en")
        self.initial_prompt = (
            load_dictionary() if section.getboolean("use_dictionary", True) else ""
        )

    def transcribe(self, audio) -> str:
        return self.backend.transcribe(audio, self.language, self.initial_prompt or None)


# -------------------------------------------------------------------------- cleanup
_CLEANER = None

# Set by app.py so the menu bar icon can reflect what the listener is doing.
STATE_HOOK = None


# Where the i3 bar looks to draw a recording indicator. XDG_RUNTIME_DIR is
# tmpfs and cleared at logout, so a stale "recording" cannot outlive the session.
STATE_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / "lyrebird.state"

# Distinct cues, so start and stop cannot be confused by ear.
_SOUNDS = {"listening": "message-new-instant.oga", "idle": "complete.oga"}


def _play(name: str) -> None:
    path = f"/usr/share/sounds/freedesktop/stereo/{name}"
    if not os.path.exists(path):
        return
    for player in ("paplay", "pw-play", "aplay"):
        if shutil.which(player):
            try:
                # Detached and discarded: dictation must never block on audio.
                subprocess.Popen([player, path],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
            return


def _set_state(state: str) -> None:
    """Publish what the mic is doing: menu bar, status bar, sound, notification.

    Toggle-mode dictation with no feedback is unusable — nothing tells you the
    mic is live, so you either talk to a mic that is not listening or leave it
    recording after you walk away. Everything here is best-effort: a missing
    sound theme or notification daemon must never break dictation.
    """
    if STATE_HOOK is not None:
        try:
            STATE_HOOK(state)
        except Exception:                          # noqa: BLE001 - cosmetic only
            pass

    try:
        STATE_PATH.write_text(state)
    except OSError:
        pass

    sound = _SOUNDS.get(state)
    if sound:
        _play(sound)

    if state in _SOUNDS and shutil.which("notify-send"):
        title = "\u25cf Recording" if state == "listening" else "Dictation done"
        try:
            # x-canonical-private-synchronous replaces the previous popup rather
            # than stacking one per utterance.
            subprocess.Popen(
                ["notify-send", "-t", "1200",
                 "-h", "string:x-canonical-private-synchronous:lyrebird", title],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def clean_text(text: str, cfg: configparser.ConfigParser) -> str:
    """Optional grammar pass. Loads the model once, on first use."""
    global _CLEANER

    section = cfg["cleanup"]
    if not section.getboolean("enabled", False) or not text:
        return text
    if _CLEANER is None:
        engine = cleanup_mod.resolve(section.get("engine", "auto"),
                                     section.get("endpoint", "http://localhost:11434"))
        if engine == "none":
            print("  cleanup enabled but no engine available — skipping", file=sys.stderr)
            section["enabled"] = "false"
            return text
        print(f"  loading cleanup model ({engine})...")
        _CLEANER = cleanup_mod.Cleaner(
            engine=engine,
            model=section.get("model", "").strip(),
            endpoint=section.get("endpoint", "http://localhost:11434"),
            timeout=section.getint("timeout_seconds", 60),
        )
    return _CLEANER.clean(text)


# --------------------------------------------------------------------------- output
def emit(text: str, cfg: configparser.ConfigParser) -> None:
    if not text:
        return
    if cfg["output"].getboolean("echo_to_stdout", True):
        print(f"> {text}")
    time.sleep(cfg["output"].getfloat("delay_before_type", 0.15))
    emit_raw(text, cfg)


def emit_raw(text: str, cfg: configparser.ConfigParser) -> None:
    """Send text to the focused field with no logging and no delay."""
    if not text:
        return
    section = cfg["output"]
    method = section.get("method", "type")

    if method == "clipboard":
        _emit_clipboard(text)
    else:
        from pynput.keyboard import Controller

        Controller().type(text)


def erase(count: int) -> None:
    """Send `count` backspaces to the focused field.

    Used by the second pass to take back text the live pass typed. Deliberately
    the only place that deletes anything, and callers must be certain the cursor
    is still where they left it — see the guards in finish().
    """
    if count <= 0:
        return
    from pynput.keyboard import Controller, Key

    kb = Controller()
    for _ in range(count):
        kb.press(Key.backspace)
        kb.release(Key.backspace)


def _emit_clipboard(text: str) -> None:
    """Copy then paste, restoring the previous clipboard afterwards."""
    import subprocess

    from pynput.keyboard import Controller, Key

    kb = Controller()
    previous = None
    try:
        if sys.platform == "darwin":
            previous = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
            modifier = Key.cmd
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text,
                           text=True, check=True)
            modifier = Key.ctrl
        with kb.pressed(modifier):
            kb.press("v")
            kb.release("v")
        time.sleep(0.15)
    finally:
        if previous is not None and sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=previous, text=True)


# --------------------------------------------------------------------------- runtime
def resolve_key(name: str):
    from pynput.keyboard import Key, KeyCode

    name = name.strip().lower()
    if hasattr(Key, name):
        return getattr(Key, name)
    if len(name) == 1:
        return KeyCode.from_char(name)
    sys.exit(f"Unrecognised hotkey '{name}'. Try f5, f6, f13, cmd_r, alt_r.")


def _make_controller(cfg: configparser.ConfigParser):
    """Build the recorder and transcriber, and return (begin, finish, state, mode).

    Split out so the recording machinery is shared by both front ends:
    `run_listener` (pynput grabs a global hotkey — macOS, Windows) and
    `run_daemon` (the window manager owns the key and signals us — Linux).
    """
    audio_cfg = cfg["audio"]
    recorder = Recorder(
        audio_cfg.getint("sample_rate", 16000),
        audio_cfg.getint("channels", 1),
        audio_cfg.getint("max_seconds", 300),
    )
    transcriber = Transcriber(cfg)

    live = cfg["transcription"].getboolean("live", False)
    stream_holder: dict = {"st": None}
    guard = None

    if live and cfg["transcription"].getboolean("hold_while_editing", True):
        guard = editguard_mod.EditGuard(
            idle_seconds=cfg["transcription"].getfloat("edit_idle_seconds", 1.2),
            on_flush=lambda t: emit_raw(t, cfg),
            on_state=lambda held: _set_state("busy" if held else "listening"),
        )
        if not guard.start():
            print("  (edit protection unavailable)", file=sys.stderr)
            guard = None

    # How many characters the live pass has typed. The second pass needs this to
    # take them back; it is the only safe way to know, since the text went into
    # somebody else's window and cannot be read back.
    typed = {"chars": 0}

    if live:
        def on_chunk(mono):
            st = stream_holder["st"]
            if st is not None:
                st.add_audio(mono)
        recorder.on_chunk = on_chunk

    mode = cfg["hotkey"].get("mode", "toggle").strip().lower()
    state = {"recording": False, "busy": False}
    lock = threading.Lock()

    def begin():
        with lock:
            if state["recording"] or state["busy"]:
                return
            state["recording"] = True
        _set_state("listening")
        print("● recording — press again to stop" if mode == "toggle" else "● recording")
        if live:
            typed_any = {"v": False}

            def emit(words):
                # Type as the words are confirmed, so text appears while talking.
                text = (" " if typed_any["v"] else "") + " ".join(words)
                typed_any["v"] = True
                typed["chars"] += len(text)
                try:
                    if guard is not None:
                        guard.submit(text)        # held back if you are editing
                    else:
                        emit_raw(text, cfg)
                except Exception as exc:          # noqa: BLE001
                    print(f"  [live] could not type: {exc}", file=sys.stderr)

            stream_holder["st"] = streaming_mod.StreamingTranscriber(
                transcriber.backend,
                transcriber.language,
                transcriber.initial_prompt or None,
                interval=cfg["transcription"].getfloat("live_interval", 1.4),
                on_words=emit,
            )
            stream_holder["st"].start()
        recorder.start()

    def _second_pass(audio, live_text: str) -> None:
        """Re-transcribe the whole recording and correct what the live pass typed.

        Live transcription runs on partial audio, so it commits words before the
        model has heard the end of the sentence — it cannot use later context to
        fix an earlier guess, and it never retracts. Running once more over the
        complete recording gets the accurate version. Where they differ, the
        typed text is taken back and replaced.

        This is the only code that deletes anything, so it refuses unless it is
        certain the cursor is still where the live pass left it:

          - the guard must not be holding text, and must not have seen you type
            or click since (otherwise the backspaces land in your own edits)
          - the character count must match what we believe we typed
          - the two passes must actually differ, after normalising whitespace

        Any doubt and it leaves the live text alone: a slightly wrong sentence is
        a far better failure than eating the surrounding paragraph.
        """
        if not cfg["transcription"].getboolean("second_pass", True):
            return
        if audio is None or len(audio) < 1600:          # under ~0.1s
            return
        count = typed["chars"]
        if count <= 0:
            return
        if guard is not None and not guard.safe_to_type():
            print("  second pass skipped: you were typing", file=sys.stderr)
            return

        _set_state("busy")
        print("… second pass")
        try:
            final = transcriber.transcribe(audio)
            final = clean_text(final, cfg)
        except Exception as exc:                        # noqa: BLE001
            print(f"  second pass failed: {exc}", file=sys.stderr)
            return

        if not final.strip():
            return
        if " ".join(final.split()) == " ".join(live_text.split()):
            print("  second pass: no change")
            return

        if guard is not None:
            # Our own backspaces and typing must not look like you editing.
            guard.expect_own_output(3.0)
        erase(count)
        emit_raw(final, cfg)
        print(f"  corrected: {final[:80]}")

    def finish():
        with lock:
            if not state["recording"]:
                return
            state["recording"] = False
            state["busy"] = True
        if live:
            st = stream_holder["st"]
            # Keep the audio: the second pass re-transcribes the whole recording.
            audio = recorder.stop()
            try:
                text = st.finish() if st else ""
                if guard is not None:
                    guard.flush()                 # never lose held words
                print(f"  live: {len(text.split())} words")
                _second_pass(audio, text)
            finally:
                _set_state("idle")
                stream_holder["st"] = None
                typed["chars"] = 0
                with lock:
                    state["busy"] = False
            return

        _set_state("busy")
        print("… transcribing")
        try:
            audio = recorder.stop()
            if audio is None or len(audio) < 1600:      # under ~0.1s of audio
                print("  (too short, ignored)")
                return
            t0 = time.monotonic()
            text = transcriber.transcribe(audio)
            took = time.monotonic() - t0
            secs = len(audio) / recorder.sample_rate
            speed = f"{secs / took:.1f}x realtime" if took else "instant"
            print(f"  transcribed {secs:.1f}s of audio in {took:.1f}s ({speed})")
            text = clean_text(text, cfg)
            emit(text, cfg)
        finally:
            _set_state("idle")
            with lock:
                state["busy"] = False

    return begin, finish, state, mode


def run_listener(cfg: configparser.ConfigParser) -> None:
    """Grab a global hotkey with pynput and dictate on it.

    The right front end on macOS and Windows. On Linux prefer --daemon plus
    --toggle: the window manager already owns key binding, doing it twice is
    redundant, and pynput's X11 grab does not work under Wayland at all.
    """
    from pynput import keyboard

    begin, finish, state, mode = _make_controller(cfg)
    hotkey = resolve_key(cfg["hotkey"].get("key", "f5"))

    def on_press(key):
        if key != hotkey:
            return
        if mode == "push_to_talk":
            begin()
        else:
            finish() if state["recording"] else begin()

    def on_release(key):
        if key == hotkey and mode == "push_to_talk":
            finish()

    print(f"\nReady. Hotkey: {cfg['hotkey'].get('key')} ({mode}).  Ctrl+C to quit.\n")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


# --------------------------------------------------------------- daemon + toggle
# On Linux the window manager binds the key, so Lyrebird should not also grab one.
# But the model cannot be loaded per keypress — large-v3-turbo takes seconds — so
# something has to stay resident holding it. Hence: a daemon that keeps the model
# warm, and a one-shot `--toggle` that signals it and exits immediately.
#
# Signals rather than a socket because that is all this needs: one verb, no
# payload, no reply.

def _pid_path() -> Path:
    """Where the daemon records its pid.

    XDG_RUNTIME_DIR is tmpfs and cleared on logout, so a stale file cannot
    outlive the session it belongs to.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "lyrebird.pid"


def run_daemon(cfg: configparser.ConfigParser) -> None:
    """Stay resident with the model loaded; toggle recording on SIGUSR1."""
    begin, finish, state, mode = _make_controller(cfg)

    if mode == "push_to_talk":
        print("note: push_to_talk needs key-release events, which a window-manager\n"
              "      binding cannot give us. Running in toggle mode instead.",
              file=sys.stderr)

    # The handler must not do the work: transcription takes seconds, and a signal
    # handler blocking for that long would swallow anything arriving meanwhile.
    # So the handler only enqueues, and the loop below does the work.
    events: queue.Queue[str] = queue.Queue()
    signal.signal(signal.SIGUSR1, lambda *_: events.put("toggle"))

    pid_file = _pid_path()
    pid_file.write_text(str(os.getpid()))
    print(f"\nReady (daemon, pid {os.getpid()}). Toggle with:\n"
          f"  {sys.executable} {__file__} --toggle\n")
    try:
        while True:
            # A timeout rather than a bare blocking get(), so the loop cannot
            # wedge if a signal lands at an awkward moment.
            try:
                event = events.get(timeout=1.0)
            except queue.Empty:
                continue
            if event == "toggle":
                finish() if state["recording"] else begin()
    finally:
        pid_file.unlink(missing_ok=True)


def send_toggle() -> None:
    """Signal a running daemon to start or stop recording, then exit."""
    pid_file = _pid_path()
    if not pid_file.exists():
        sys.exit("No daemon running. Start one with:  dictate.py --daemon")
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        sys.exit("Unreadable pidfile — removed. Start the daemon again.")
    try:
        os.kill(pid, signal.SIGUSR1)
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        sys.exit("Daemon is gone (stale pidfile removed). Start it again.")
    except PermissionError:
        sys.exit(f"pid {pid} is not ours — refusing to signal it.")


def run_live_test(cfg: configparser.ConfigParser) -> None:
    """Stream from the microphone and print words as they are recognised.

    Needs microphone access only - no Accessibility permission, no hotkey, and
    nothing is typed into other applications. This isolates "does streaming
    work" from "is the app allowed to type", which fail for different reasons.
    """
    import sounddevice as sd

    audio_cfg = cfg["audio"]

    dev = sd.query_devices(kind="input")
    print(f"\nInput device : {dev['name']}")
    print(f"Sample rate  : {audio_cfg.getint('sample_rate', 16000)} Hz, "
          f"{audio_cfg.getint('channels', 1)} channel(s)")

    transcriber = Transcriber(cfg)

    recorder = Recorder(
        audio_cfg.getint("sample_rate", 16000),
        audio_cfg.getint("channels", 1),
        audio_cfg.getint("max_seconds", 300),
    )
    st = streaming_mod.StreamingTranscriber(
        transcriber.backend,
        transcriber.language,
        transcriber.initial_prompt or None,
        interval=cfg["transcription"].getfloat("live_interval", 1.4),
        on_words=lambda ws: (sys.stdout.write(("\r\033[K" if sys.stdout.isatty() else "")
                                              + " ".join(ws) + "\n"),
                             sys.stdout.flush()),
    )

    stats = {"peak": 0.0, "chunks": 0, "samples": 0}
    # Only draw the meter to a real terminal. Piped or redirected, the escape
    # codes become unreadable noise.
    interactive = sys.stdout.isatty()

    def tap(chunk):
        stats["chunks"] += 1
        stats["samples"] += len(chunk)
        p = float(abs(chunk).max()) if len(chunk) else 0.0
        stats["peak"] = max(stats["peak"], p)
        # Live meter, so it is obvious whether audio is arriving at all.
        if interactive:
            bars = int(min(p, 0.5) / 0.5 * 30)
            sys.stdout.write("\r\033[K  mic |" + "#" * bars + "-" * (30 - bars) +
                             f"| {p:.3f}")
            sys.stdout.flush()
        st.add_audio(chunk)

    recorder.on_chunk = tap

    print("\nSpeak now - the meter below should move while you talk.")
    print("Press Enter when you have finished.\n")
    st.start()
    recorder.start()
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    recorder.stop()
    final = st.finish()

    print(("\r\033[K" if interactive else "") + "-" * 60)
    print(f"Final text   : {final or '(nothing recognised)'}")
    print(f"Audio chunks : {stats['chunks']}  "
          f"({stats['samples'] / max(audio_cfg.getint('sample_rate', 16000), 1):.1f}s captured)")
    print(f"Mic peak     : {stats['peak']:.4f}", end="")
    if stats["chunks"] == 0:
        print("   <-- the audio callback never fired: capture never started")
    elif stats["peak"] < 0.001:
        print("   <-- callback fired but every sample was zero:")
        print("                    microphone access denied, or the device is muted")
    elif stats["peak"] < 0.02:
        print("   <-- very quiet")
    else:
        print("   (healthy)")


def run_once(cfg: configparser.ConfigParser) -> None:
    audio_cfg = cfg["audio"]
    recorder = Recorder(
        audio_cfg.getint("sample_rate", 16000),
        audio_cfg.getint("channels", 1),
        audio_cfg.getint("max_seconds", 300),
    )
    transcriber = Transcriber(cfg)
    input("Press Enter to start recording...")
    recorder.start()
    input("● recording — press Enter to stop...")
    audio = recorder.stop()
    if audio is None:
        sys.exit("No audio captured.")
    text = transcriber.transcribe(audio)
    print(f"\nRaw:     {text}")
    cleaned = clean_text(text, cfg)
    if cleaned != text:
        print(f"Cleaned: {cleaned}")


def run_check(cfg: configparser.ConfigParser) -> None:
    print("local-dictation — diagnostics\n")
    ok = True

    print(f"python           {sys.version.split()[0]}")
    print(f"platform         {sys.platform}")

    for module in ("numpy", "sounddevice", "faster_whisper", "pynput", "requests"):
        try:
            __import__(module)
            print(f"  {module:<16} ok")
        except Exception as exc:                  # noqa: BLE001
            print(f"  {module:<16} MISSING ({exc})")
            ok = False

    try:
        import sounddevice as sd

        default_in = sd.query_devices(kind="input")
        print(f"\nmicrophone       {default_in['name']}")
    except Exception as exc:                      # noqa: BLE001
        print(f"\nmicrophone       UNAVAILABLE ({exc})")
        ok = False

    terms = load_dictionary()
    print()
    for label, value, _ok in backends.describe_hardware():
        print(f"  {label:<18} {value}")
    print(f"\nbackend          {backends.resolve_backend(cfg['transcription'].get('backend','auto'))}"
          f"  (config: {cfg['transcription'].get('backend','auto')})")
    print(f"dictionary       {len(terms.split(',')) if terms else 0} terms")
    print(f"hotkey           {cfg['hotkey'].get('key')} ({cfg['hotkey'].get('mode')})")
    print(f"model            {cfg['transcription'].get('model')}")

    for label, value, _ok in cleanup_mod.describe():
        print(f"  {label:<26} {value}")
    if cfg["cleanup"].getboolean("enabled", False):
        engine = cleanup_mod.resolve(cfg["cleanup"].get("engine", "auto"))
        print(f"cleanup          on, engine = {engine}")
        if engine == "none":
            print("                 no engine available")
            ok = False
    else:
        print("cleanup          off")

    print("\n" + ("All good." if ok else "Problems found — see docs/TROUBLESHOOTING.md"))
    sys.exit(0 if ok else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline local dictation.")
    parser.add_argument("--check", action="store_true", help="diagnose the install")
    parser.add_argument("--once", action="store_true", help="record one utterance and print")
    parser.add_argument("--devices", action="store_true", help="list audio input devices")
    parser.add_argument("--live", action="store_true",
                        help="stream from the mic and print words; no typing, no permissions needed")
    parser.add_argument("--daemon", action="store_true",
                        help="stay resident with the model loaded; toggle via --toggle "
                             "(use this on Linux, and let the WM bind the key)")
    parser.add_argument("--toggle", action="store_true",
                        help="tell a running --daemon to start/stop recording, then exit")
    args = parser.parse_args()

    if args.toggle:          # before load_config: this path needs nothing loaded
        send_toggle()
        return

    cfg = load_config()

    if args.devices:
        import sounddevice as sd

        print(sd.query_devices())
        return
    if args.check:
        run_check(cfg)
        return
    if args.live:
        cfg["transcription"]["live"] = "true"
        run_live_test(cfg)
        return
    if args.once:
        run_once(cfg)
        return
    if args.daemon:
        run_daemon(cfg)
        return
    run_listener(cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
