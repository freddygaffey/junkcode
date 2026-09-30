# Lyrebird

**Offline dictation that gets your words right.**

Named after the Australian bird that reproduces any sound it hears with uncanny
precision — which is the whole job.


Offline speech-to-text with optional local grammar cleanup. No cloud, no subscription,
no audio or text ever leaves the machine.

Built after a real problem: a long document dictated with macOS's built-in dictation
accumulated ~140 transcription errors — `servo` → "server", `louvres` → "luvers",
`CAD` → "card", `revolve` split across a line break. Whisper plus a custom vocabulary
fixes most of that class of error before it reaches the page.

## What it does

```
  F5 pressed
      |
      v
  record mic  ->  faster-whisper (local)  ->  [optional] Ollama LLM (local)  ->  typed into focused field
                  large-v3-turbo                 grammar / filler cleanup
```

Everything runs on your machine. Ollama is optional — turn it off and you get raw
Whisper output, which is already well punctuated and noticeably faster.

## Install (no terminal required)

Download `Lyrebird.dmg`, drag Lyrebird to Applications, open it.

macOS will ask for **Microphone** and **Accessibility** permission. Both are
required: microphone to hear you, accessibility to type for you. The settings
window opens by itself. Press **F5** to dictate.

First launch downloads the speech model (about 1.6 GB). After that it is fully
offline. On an unsigned build macOS may say the developer cannot be verified —
right-click the app and choose **Open**.

Windows: run `Lyrebird-Setup.exe`. Linux: build from source, below.

## Build it yourself

One script does everything, on macOS and Linux alike:

```bash
cd ~/dev/lyrebird
./setup.sh                # install + self-test
./setup.sh --cleanup      # also install Ollama for grammar cleanup
./setup.sh --check        # verify an existing install
```

Windows: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`

Then:

```bash
.venv/bin/python src/dictate.py     # start dictating
.venv/bin/python src/webui.py       # settings page, http://127.0.0.1:5000
```

Press **F5**, talk, press **F5** again. Text appears wherever your cursor is.

## Settings without touching a config file

```bash
.venv/bin/python src/webui.py
```

Opens a plain settings page in your browser: hotkey, accuracy, grammar cleanup,
and your word list, with a live health check at the top. It writes the same config
files, and backs them up before every save. Nothing is exposed to the network —
it binds to `127.0.0.1` only.

## Building the installers

```bash
./build/build-macos.sh                  # -> dist/Lyrebird.app and dist/Lyrebird.dmg
powershell -File build\build-windows.ps1  # -> dist/Lyrebird.exe (+ installer)
```

The bundle is ~118 MB. `torch` is a declared dependency of `mlx-whisper` but is
never used at runtime, so it is excluded — that alone saves 511 MB.

## Platform support

| Platform | Status | Notes |
|---|---|---|
| macOS (Apple Silicon) | primary | Needs Accessibility + Microphone permission |
| macOS (Intel) | works | Slower; use `small` or `medium` model |
| Linux | works | Let your WM bind the key — see [Linux](#linux-let-the-wm-bind-the-key) |
| Windows | works | Run PowerShell as your normal user, not admin |

## Linux: let the WM bind the key

On macOS and Windows, Lyrebird grabs a global hotkey itself. On Linux, don't —
your window manager already does that job, doing it twice means two things
fighting over one key, and `pynput`'s X11 grab doesn't work under Wayland at all.

So there are two pieces:

```sh
./.venv/bin/python src/dictate.py --daemon    # resident, holds the model
./.venv/bin/python src/dictate.py --toggle    # start/stop recording, then exits
```

The daemon exists for one reason: loading `large-v3-turbo` takes seconds, so the
model can't be loaded per keypress. It stays warm; `--toggle` signals it
(`SIGUSR1` via a pidfile in `$XDG_RUNTIME_DIR`) and returns immediately, so the
keypress feels instant.

Bind the key in your WM and start the daemon from the same place. i3:

```
exec --no-startup-id sh -c 'cd "$HOME/lyrebird" && exec ./.venv/bin/python src/dictate.py --daemon'
bindsym F9 exec --no-startup-id sh -c 'cd "$HOME/lyrebird" && ./.venv/bin/python src/dictate.py --toggle'
```

Use `exec`, not `exec_always` — reloading the WM shouldn't throw away a model
that took seconds to load.

`push_to_talk` mode isn't available this way: it needs key-release events, which a
WM binding can't hand over. The daemon runs in toggle mode and says so.

Two Linux config settings that differ from the macOS defaults:

```ini
[transcription]
backend = auto        # NOT mlx — that's the Apple Metal backend
compute_type = int8   # several times faster than float32 on CPU
```

`backend` is returned verbatim when it isn't `auto`, so leaving `mlx` in place on
Linux tries to load the Metal backend and fails.

## Configuration

Everything lives in `config/config.ini` — plain INI, safe to edit by hand.
Custom vocabulary lives in `config/dictionary.txt`, one term per line.

Adding a term to `dictionary.txt` is the single highest-value thing you can do.
It is what stops "servo" becoming "server".

## Where to look when it breaks

- `docs/ARCHITECTURE.md` — how the pieces fit, and why each choice was made
- `docs/MAINTENANCE.md` — updating models, changing hotkeys, routine upkeep
- `docs/TROUBLESHOOTING.md` — symptoms and fixes

## Licence

MIT. See LICENSE.
