#!/usr/bin/env python3
"""
Benchmark every available backend/model combination on THIS machine.

Speed alone is a bad way to choose — the fastest model is often the one that
mishears your vocabulary. So this measures both, using a reference sentence full
of the technical terms this project cares about, and reports word error rate
alongside throughput.

    python src/benchmark.py                 # standard sweep
    python src/benchmark.py --quick         # fewer combinations
    python src/benchmark.py --apply         # write the best result into config.ini
    python src/benchmark.py --audio my.wav --reference "what I said"
"""
from __future__ import annotations

import argparse
import configparser
import json
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import backends  # noqa: E402
import paths  # noqa: E402

paths.ensure_user_config()
CONFIG = paths.config_dir() / "config.ini"
RESULTS = paths.config_dir() / "benchmark-results.json"

REFERENCE = ("I used Onshape to model the servo horn, then added a chamfer to the "
             "louvres and printed it in PETG on the Bambu Lab printer.")


# ------------------------------------------------------------------------- audio
def synthesise(text: str) -> Path:
    """Generate reference audio with the OS text-to-speech voice."""
    tmp = Path(tempfile.mkdtemp())
    wav = tmp / "sample.wav"
    if sys.platform == "darwin":
        aiff = tmp / "sample.aiff"
        subprocess.run(["say", "-o", str(aiff), text], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff),
                        "-ar", "16000", "-ac", "1", str(wav)], check=True)
    else:
        subprocess.run(["espeak-ng", "-w", str(wav), text], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav),
                        "-ar", "16000", "-ac", "1", str(wav)], check=True)
    return wav


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        raw = w.readframes(w.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return data


# --------------------------------------------------------------------- accuracy
def normalise(text: str) -> list[str]:
    keep = "".join(c.lower() if (c.isalnum() or c.isspace()) else " " for c in text)
    return keep.split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein distance over words, divided by reference length."""
    r, h = normalise(reference), normalise(hypothesis)
    if not r:
        return 0.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


# ---------------------------------------------------------------------- matrix
def candidates(quick: bool) -> list[dict]:
    combos: list[dict] = []
    models = ["large-v3-turbo"] if quick else ["large-v3-turbo", "small", "base"]

    if backends.has_mlx():
        for m in models:
            combos.append({"backend": "mlx", "model": m,
                           "device": "-", "compute_type": "-", "cpu_threads": 0})

    import os
    cores = os.cpu_count() or 4
    ct_models = ["large-v3-turbo"] if quick else models
    for m in ct_models:
        for comp in (["float32"] if quick else ["float32", "int8"]):
            combos.append({"backend": "ctranslate2", "model": m, "device": "cpu",
                           "compute_type": comp, "cpu_threads": cores})
    if backends.has_cuda():
        for m in ct_models:
            combos.append({"backend": "ctranslate2", "model": m, "device": "cuda",
                           "compute_type": "float16", "cpu_threads": 0})
    return combos


def run(combo: dict, audio: np.ndarray, duration: float,
        prompt: str, reference: str) -> dict:
    result = dict(combo)
    try:
        t0 = time.monotonic()
        engine = backends.build(combo["backend"], combo["model"],
                                device=combo["device"] if combo["device"] != "-" else "auto",
                                compute_type=combo["compute_type"] if combo["compute_type"] != "-" else "auto",
                                cpu_threads=combo["cpu_threads"])
        engine.warm()
        result["load_s"] = round(time.monotonic() - t0, 1)

        t1 = time.monotonic()
        text = engine.transcribe(audio, "en", prompt or None)
        elapsed = max(time.monotonic() - t1, 1e-6)

        result["run_s"] = round(elapsed, 2)
        result["speed"] = round(duration / elapsed, 1)
        result["wer"] = round(word_error_rate(reference, text) * 100, 1)
        result["text"] = text
        result["ok"] = True
    except Exception as exc:                     # noqa: BLE001
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}",
                      load_s=0, run_s=0, speed=0.0, wer=100.0, text="")
    return result


def score(row: dict) -> float:
    """Rank by accuracy first, then speed. A fast model that mishears is useless."""
    if not row["ok"]:
        return -1e9
    return -(row["wer"] * 10) + min(row["speed"], 20)


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark transcription backends.")
    ap.add_argument("--quick", action="store_true", help="fewer combinations")
    ap.add_argument("--apply", action="store_true", help="write the winner to config.ini")
    ap.add_argument("--audio", type=Path, help="your own 16kHz mono wav")
    ap.add_argument("--reference", type=str, help="what the audio actually says")
    ap.add_argument("--json", action="store_true", help="machine-readable output only")
    args = ap.parse_args()

    reference = args.reference or REFERENCE
    wav = args.audio or synthesise(reference)
    audio = load_wav(wav)
    duration = len(audio) / 16000
    prompt = backends.load_dictionary()

    combos = candidates(args.quick)
    if not args.json:
        print(f"\nBenchmarking {len(combos)} configurations on {duration:.1f}s of audio.")
        print("First run of each model downloads weights — be patient.\n")
        print(f"{'backend':<13}{'model':<17}{'device':<8}{'compute':<10}"
              f"{'load':>7}{'run':>8}{'speed':>9}{'errors':>9}")
        print("-" * 81)

    rows = []
    for combo in combos:
        row = run(combo, audio, duration, prompt, reference)
        rows.append(row)
        if not args.json:
            if row["ok"]:
                print(f"{row['backend']:<13}{row['model']:<17}{row['device']:<8}"
                      f"{row['compute_type']:<10}{row['load_s']:>6}s{row['run_s']:>7}s"
                      f"{row['speed']:>8}x{row['wer']:>8}%")
            else:
                print(f"{row['backend']:<13}{row['model']:<17}  failed: {row['error'][:38]}")

    rows.sort(key=score, reverse=True)
    RESULTS.write_text(json.dumps({"duration": duration, "reference": reference,
                                   "results": rows}, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    best = rows[0] if rows and rows[0]["ok"] else None
    if not best:
        sys.exit("\nEvery configuration failed. Run ./setup.sh --check")

    print(f"\nRecommended: {best['backend']} / {best['model']}"
          f"{'' if best['device'] == '-' else ' / ' + best['device']}"
          f"  ->  {best['speed']}x realtime, {best['wer']}% word errors")
    print(f"  transcribed: {best['text']}")
    print(f"\nFull results saved to {RESULTS}")

    if args.apply:
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG)
        cfg["transcription"]["backend"] = best["backend"]
        cfg["transcription"]["model"] = best["model"]
        if best["device"] != "-":
            cfg["transcription"]["device"] = best["device"]
        if best["compute_type"] != "-":
            cfg["transcription"]["compute_type"] = best["compute_type"]
        with CONFIG.open("w", encoding="utf-8") as fh:
            cfg.write(fh)
        print("Applied to config.ini. Restart dictate.py to use it.")
    else:
        print("Re-run with --apply to write this into config.ini")


if __name__ == "__main__":
    main()
