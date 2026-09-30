# Architecture

## The pipeline

```
  hotkey (F5)
      |
      v
  sounddevice ......... captures raw mic audio into memory (never written to disk)
      |
      v
  faster-whisper ...... local speech-to-text, CTranslate2 backend
      |                 biased by config/dictionary.txt via `initial_prompt`
      v
  Ollama (optional) ... local LLM tidies grammar and removes filler
      |
      v
  pynput .............. types or pastes the result into whatever has focus
```

No network calls at any stage. Ollama listens on `localhost` only.

## Why these components

**faster-whisper over openai-whisper** — same models, CTranslate2 runtime, roughly
4x faster with lower memory. Runs on CPU, which matters because CTranslate2 has no
Metal backend; on Apple Silicon the CPU path with `int8` is still comfortably faster
than real time.

**`initial_prompt` for vocabulary** — Whisper has no formal custom-vocabulary API.
Passing terms as the initial prompt biases decoding towards them. It costs nothing
and is the single most effective accuracy lever available.

**Ollama optional and off by default** — Whisper already punctuates well. The LLM
pass is the slowest stage, and its failure mode is the worst: silently rewriting
what you said. The prompt in `config.ini` is deliberately conservative, and any
error falls back to the raw transcript rather than losing it.

**pynput for output** — works across macOS, Windows and X11 from one codebase.
Clipboard mode saves and restores the previous clipboard contents.

**INI, not TOML or YAML** — `configparser` is standard library. Python 3.10 has no
`tomllib`, and YAML would mean another dependency for no benefit.

## Files

| Path | Role |
|---|---|
| `setup.sh` / `setup.ps1` | one-shot install and self-test |
| `src/dictate.py` | the dictation program |
| `src/webui.py` | Flask settings page, writes the config files |
| `config/config.ini` | all settings |
| `config/dictionary.txt` | custom vocabulary |
| `config/backups/` | automatic timestamped backups, last 20 kept |

## Failure philosophy

A transcript is expensive to produce and impossible to recreate — you have already
said the words. So every optional stage degrades rather than fails: if Ollama is
down, you get the raw transcript; if cleanup times out, you get the raw transcript.
The only unrecoverable failure is not capturing audio at all.

## Measured performance

MacBook Pro, Apple M5, 10 cores, 32 GB. 7.4 s of speech. Higher is better.

| Model | Compute | Threads | Speed |
|---|---|---|---|
| large-v3-turbo | int8 | 4 | 1.6x realtime |
| large-v3-turbo | int8 | 10 | 2.1x realtime |
| **large-v3-turbo** | **float32** | **10** | **2.7x realtime** |
| distil-large-v3 | int8 | 10 | 2.6x realtime |
| small | int8 | 10 | 4.2x realtime |
| base | int8 | 10 | 9.0x realtime |

Two things worth remembering:

**float32 beats int8 here.** CTranslate2's ARM float path is better optimised than
its int8 path, so quantisation costs more than it saves. This is the opposite of the
usual advice — measure before assuming.

**CTranslate2 is CPU-only.** There is no Metal backend, so the GPU and Neural Engine
sit idle. This is the real ceiling: a Parakeet/MLX pipeline would use that silicon
and be substantially faster. That is the obvious next improvement if latency ever
becomes annoying.

At 2.7x realtime, a 15-second dictation takes about 5.5 seconds to appear.
