# Troubleshooting

Start here: `./setup.sh --check`. It reports what is actually wrong.

## The hotkey does nothing

**macOS — most common cause.** The terminal needs Accessibility permission to see
global key presses:

*System Settings > Privacy & Security > Accessibility* > enable your terminal app.
You must fully quit and reopen the terminal afterwards.

**F5 does something else.** macOS assigns F5 to keyboard backlight.
*System Settings > Keyboard > Keyboard Shortcuts > Function Keys* >
turn on "Use F1, F2, etc. as standard function keys". Or press `Fn`+`F5`.

**Apple's own dictation is grabbing the key.**
*System Settings > Keyboard > Dictation* > turn it off.

**Linux/Wayland.** Wayland blocks global hotkey capture by design. Either use an X11
session, or bind your compositor's own shortcut to run `dictate.py --once`.

## No audio captured / "too short, ignored"

```bash
.venv/bin/python src/dictate.py --devices
```

If your microphone is not listed, macOS has not granted Microphone permission:
*System Settings > Privacy & Security > Microphone* > enable your terminal.

If the wrong device is default, change it in *System Settings > Sound > Input*.

## Text appears in the wrong window

Increase `delay_before_type` in `config.ini` (try `0.4`) to give yourself time to
click into the target field.

## Transcription is slow

- Switch to a smaller model — `small` or `distil-large-v3`
- Set `compute_type = int8` in `config.ini`
- Turn off grammar cleanup; it is usually the slow stage, not transcription
- Check nothing else is saturating the CPU

## Transcription is inaccurate

1. **Add the misheard words to `config/dictionary.txt`.** This fixes most cases.
2. Set `language = en` rather than `auto`.
3. Move to a larger model.
4. Check your microphone — a poor input signal defeats any model.

Note that no speech model reliably fixes homophones (`their`/`there`, `to`/`too`),
because both are real words. That class of error still needs a proofread.

## Grammar cleanup does nothing / times out

```bash
ollama list                 # is the model pulled?
ollama serve                # is the server running?
curl http://localhost:11434/api/tags
```

Cleanup failures are deliberately non-fatal: you get the raw transcript instead.
Look for `cleanup skipped` in the terminal output.

## Settings page will not load

```bash
.venv/bin/pip install flask
.venv/bin/python src/webui.py --port 5001    # 5000 clashes with AirPlay on macOS
```

macOS uses port 5000 for AirPlay Receiver. Either use another port or turn AirPlay
Receiver off in *System Settings > General > AirDrop & Handoff*.

## Reset everything

```bash
rm -rf .venv
./setup.sh
```

Your settings survive: `config/` is untouched, and `config/backups/` holds the
last 20 versions.

## The hotkey stops working after an update (macOS)

macOS ties Accessibility permission to an application's **code signature**, not its
path or name. Every unsigned rebuild produces a different signature, so macOS sees
a different application and the permission you granted no longer applies.

Symptom: after installing a new version, F5 silently does nothing, and the log
says `This process is not trusted!`

Fix: *System Settings > Privacy & Security > Accessibility*, remove the old
Lyrebird entry with the minus button, then add the new one.

The permanent fix is a stable signing identity, which needs a paid Apple
Developer account. Until then, expect to re-grant after each update. Verified:
granting permission to one build, then replacing it, reproduced the failure
immediately.

## Windows: the GPU is detected but transcription fails

Symptom: `Library cublas64_12.dll is not found or cannot be loaded`

The engine ships without NVIDIA's CUDA runtime. Install the libraries:

```
.venv\Scripts\python.exe -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

CPU transcription is unaffected and needs nothing extra - on a test sentence
dense with technical vocabulary it scored 0% word error rate on Windows.
