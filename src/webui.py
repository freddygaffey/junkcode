#!/usr/bin/env python3
"""
local-dictation — browser-based configuration.

A small Flask app so the settings can be changed without touching an INI file.
Binds to 127.0.0.1 only: it is never reachable from the network.

    python src/webui.py            # http://127.0.0.1:5000
    python src/webui.py --port 8080
"""
from __future__ import annotations

import argparse
import configparser
import json
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import backends  # noqa: E402
import paths  # noqa: E402
paths.ensure_user_config()
CONFIG = paths.config_dir() / "config.ini"
DICTIONARY = paths.config_dir() / "dictionary.txt"
BACKUPS = paths.config_dir() / "backups"

app = Flask(__name__)

# (value, friendly name, download size, what you gain, what it costs, show in simple mode)
MODELS = [
    ("tiny",            "Fastest",        "75 MB",  "Instant, runs on anything",
     "Noticeably more mistakes. Fine for short notes, not for documents.", False),
    ("base",            "Very fast",      "145 MB", "Quick, very light on memory",
     "Struggles with technical words and accents.", False),
    ("small",           "Balanced",       "480 MB", "Good accuracy, quick on any laptop",
     "Misses some unusual or technical words.", True),
    ("medium",          "More accurate",  "1.5 GB", "Handles accents and difficult audio well",
     "Slower, and uses about 2 GB of memory.", False),
    ("large-v3-turbo",  "Recommended",    "1.6 GB", "Best balance: near-top accuracy, still fast",
     "Larger download. Needs roughly 2 GB of memory.", True),
    ("large-v3",        "Most accurate",  "3 GB",   "The best accuracy available",
     "About 5x slower than Recommended for a barely noticeable accuracy gain.", True),
    ("distil-large-v3", "Distilled",      "1.5 GB", "Almost as accurate as Most accurate, much faster",
     "English only.", False),
]
MODEL_VALUES = [m[0] for m in MODELS]
KEYS = ["f5", "f6", "f7", "f8", "f13", "f14", "cmd_r", "alt_r", "ctrl_r"]
BACKENDS = [("auto", "Automatic - pick the fastest available"),
            ("mlx", "Apple GPU (Metal) - fastest on a Mac"),
            ("ctranslate2", "CPU / NVIDIA GPU - works everywhere")]
DEVICES = [("auto", "Automatic"), ("cpu", "CPU"), ("cuda", "NVIDIA GPU (CUDA)")]
COMPUTES = [("auto", "Automatic"), ("float32", "float32 - fastest on Apple Silicon"),
            ("float16", "float16 - for NVIDIA GPUs"), ("int8", "int8 - lowest memory")]

# Benchmark runs in a worker thread; the page polls /benchmark/status.
BENCH = {"running": False, "done": False, "rows": [], "error": None, "started": 0.0}


def read_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG)
    return cfg


def backup_config() -> None:
    """Keep a timestamped copy before every write, so a bad edit is never fatal."""
    BACKUPS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(CONFIG, BACKUPS / f"config-{stamp}.ini")
    if DICTIONARY.exists():
        shutil.copy2(DICTIONARY, BACKUPS / f"dictionary-{stamp}.txt")
    # keep only the 20 most recent
    for old in sorted(BACKUPS.glob("config-*.ini"))[:-20]:
        old.unlink(missing_ok=True)
    for old in sorted(BACKUPS.glob("dictionary-*.txt"))[:-20]:
        old.unlink(missing_ok=True)


def diagnostics() -> list[tuple[str, str, bool]]:
    """(label, value, healthy) rows for the status panel."""
    rows = []
    rows.append(("Python", sys.version.split()[0], True))
    for mod, label in [
        ("faster_whisper", "Speech engine"),
        ("sounddevice", "Microphone library"),
        ("pynput", "Keyboard control"),
    ]:
        try:
            __import__(mod)
            rows.append((label, "installed", True))
        except Exception:
            rows.append((label, "MISSING — re-run setup.sh", False))
    try:
        import sounddevice as sd

        rows.append(("Microphone", sd.query_devices(kind="input")["name"], True))
    except Exception as exc:
        rows.append(("Microphone", f"unavailable ({exc.__class__.__name__})", False))

    for label, value, healthy in backends.describe_hardware():
        rows.append((label, value, healthy))
    rows.append(("Active engine",
                 backends.resolve_backend(read_config()["transcription"].get("backend", "auto")),
                 True))

    cfg = read_config()
    if cfg.has_section("cleanup") and cfg["cleanup"].getboolean("enabled", False):
        try:
            import requests

            endpoint = cfg["cleanup"].get("endpoint", "").rstrip("/")
            models = requests.get(f"{endpoint}/api/tags", timeout=3).json().get("models", [])
            rows.append(("Grammar cleanup", f"Ollama reachable, {len(models)} models", True))
        except Exception:
            rows.append(("Grammar cleanup", "Ollama not reachable — is it running?", False))
    else:
        rows.append(("Grammar cleanup", "turned off", True))
    return rows


TEMPLATE = """
<!doctype html><meta charset="utf-8">
<title>Dictation Settings</title>
<style>
 :root{--bg:#fbfbfd;--fg:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--acc:#0071e3;--card:#fff}
 @media(prefers-color-scheme:dark){:root{--bg:#161618;--fg:#f5f5f7;--mut:#98989d;--line:#38383c;--card:#1f1f22}}
 *{box-sizing:border-box}
 body:not([data-mode]) .expert-only{display:none}
 body{margin:0;padding:2rem 1rem 4rem;background:var(--bg);color:var(--fg);
      font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
 .wrap{max-width:760px;margin:0 auto}
 h1{font-size:1.6rem;margin:0 0 .25rem}
 .sub{color:var(--mut);margin:0 0 2rem}
 .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:1.25rem 1.5rem;margin-bottom:1.25rem}
 h2{font-size:1.05rem;margin:0 0 .35rem}
 .hint{color:var(--mut);font-size:.87rem;margin:0 0 1rem}
 label{display:block;font-weight:600;font-size:.9rem;margin:1rem 0 .3rem}
 label:first-of-type{margin-top:0}
 .fh{font-weight:400;color:var(--mut);font-size:.85rem;display:block;margin-top:.15rem}
 select,input[type=text],input[type=number],textarea{
   width:100%;padding:.55rem .7rem;border:1px solid var(--line);border-radius:8px;
   background:var(--bg);color:var(--fg);font:inherit;font-size:.95rem}
 textarea{min-height:260px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem}
 .row{display:flex;gap:1rem;flex-wrap:wrap}.row>div{flex:1;min-width:190px}
 .check{display:flex;align-items:flex-start;gap:.6rem;margin:1rem 0 0}
 .check input{margin-top:.3rem}.check label{margin:0}
 table{width:100%;border-collapse:collapse;font-size:.9rem}
 td{padding:.4rem 0;border-bottom:1px solid var(--line)}
 td:first-child{color:var(--mut);width:42%}
 .good{color:#1a7f37;font-weight:600}.bad{color:#c00;font-weight:600}
 button{background:var(--acc);color:#fff;border:0;border-radius:8px;
        padding:.7rem 1.4rem;font:inherit;font-weight:600;cursor:pointer}
 .saved{background:#1a7f37;color:#fff;padding:.7rem 1rem;border-radius:8px;margin-bottom:1.25rem}
 code{background:var(--bg);border:1px solid var(--line);padding:.1rem .35rem;border-radius:4px;font-size:.85em}
 button.ghost{background:transparent;color:var(--acc);border:1px solid var(--acc)}
 button:disabled{opacity:.5;cursor:default}
 .bench{margin-top:1rem;font-size:.88rem}
 .bench th{text-align:left;color:var(--mut);font-weight:600;border-bottom:1px solid var(--line);padding:.35rem 0}
 .bench td{padding:.35rem .5rem .35rem 0}
 .win{font-weight:700;color:#1a7f37}
 .choices{display:flex;flex-direction:column;gap:.6rem}
 .choice{display:flex;gap:.7rem;align-items:flex-start;margin:0;padding:.75rem .85rem;
         border:1px solid var(--line);border-radius:10px;cursor:pointer;font-weight:400}
 .choice:hover{border-color:var(--acc)}
 .choice:has(input:checked){border-color:var(--acc);box-shadow:inset 0 0 0 1px var(--acc)}
 .choice input{margin-top:.28rem;flex:none}
 .choice-body{display:flex;flex-direction:column;gap:.15rem}
 .choice-head{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
 .tag{font-size:.75rem;color:var(--mut);border:1px solid var(--line);
      border-radius:999px;padding:.05rem .45rem}
 .tag.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
 .gain{font-size:.87rem}
 .cost{font-size:.82rem;color:var(--mut)}
 .warn{font-size:.87rem;background:rgba(201,123,60,.12);border:1px solid rgba(201,123,60,.4);
       border-radius:8px;padding:.6rem .8rem;margin:.6rem 0 1rem}
 .head{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;margin-bottom:2rem}
 .modes{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:3px;background:var(--card)}
 .mode{background:transparent;color:var(--mut);border:0;border-radius:999px;
       padding:.4rem 1rem;font:inherit;font-size:.85rem;font-weight:600;cursor:pointer}
 .mode.on{background:var(--acc);color:#fff}
 body[data-mode="simple"] .expert-only{display:none}
 .spin{display:inline-block;width:.8em;height:.8em;border:2px solid var(--line);
       border-top-color:var(--acc);border-radius:50%;animation:sp .7s linear infinite;vertical-align:-1px}
 @keyframes sp{to{transform:rotate(360deg)}}
</style>
<div class="wrap" id="top">
<div class="head">
  <div>
    <h1>Lyrebird</h1>
    <p class="sub">Changes save straight away. Restart Lyrebird to apply them.</p>
  </div>
  <div class="modes" role="group" aria-label="Detail level">
    <button type="button" class="mode on" data-mode="simple" onclick="setMode('simple')">Simple</button>
    <button type="button" class="mode" data-mode="expert" onclick="setMode('expert')">Expert</button>
  </div>
</div>

{% if saved %}<div class="saved">Saved. Restart the dictation program for changes to take effect.</div>{% endif %}

<div class="card expert-only">
  <h2>Status</h2>
  <p class="hint">A quick health check of the parts that have to work.</p>
  <table>
  {% for label, value, healthy in diags %}
    <tr><td>{{ label }}</td><td class="{{ 'good' if healthy else 'bad' }}">{{ value }}</td></tr>
  {% endfor %}
  </table>
</div>

<form method="post" action="{{ url_for('save') }}">
<div class="card">
  <h2>How you start dictating</h2>
  <p class="hint">Pick the key you press to begin talking.<br>
  <b>Press once to start and stop</b> suits long dictation &mdash; you are not holding a key down for minutes. <b>Hold while talking</b> suits short bursts and makes it impossible to leave the microphone on by accident.</p>
  <div class="row">
    <div><label>Key<select name="hotkey_key">
      {% for k in keys %}<option value="{{k}}" {{ 'selected' if cfg['hotkey']['key']==k }}>{{k.upper()}}</option>{% endfor %}
    </select></label></div>
    <div><label>Style<select name="hotkey_mode">
      <option value="toggle" {{ 'selected' if cfg['hotkey']['mode']=='toggle' }}>Press once to start, once to stop</option>
      <option value="push_to_talk" {{ 'selected' if cfg['hotkey']['mode']=='push_to_talk' }}>Hold down while talking</option>
    </select></label></div>
  </div>
</div>

<div class="card expert-only">
  <h2>Engine</h2>
  <p class="hint">Which hardware does the work. <b>Automatic</b> is right for almost everyone &mdash; on this Mac it selects the Apple GPU, which measured about 6&times; faster than the CPU.</p>
  <label>Engine<select name="backend">
    {% for v,d in bkends %}<option value="{{v}}" {{ 'selected' if cfg['transcription'].get('backend','auto')==v }}>{{d}}</option>{% endfor %}
  </select></label>
  <div class="row">
    <div><label>Processor <span class="fh">CPU/NVIDIA engine only</span><select name="device">
      {% for v,d in devs %}<option value="{{v}}" {{ 'selected' if cfg['transcription'].get('device','auto')==v }}>{{d}}</option>{% endfor %}
    </select></label></div>
    <div><label>Precision <span class="fh">CPU/NVIDIA engine only</span><select name="compute_type">
      {% for v,d in comps %}<option value="{{v}}" {{ 'selected' if cfg['transcription'].get('compute_type','auto')==v }}>{{d}}</option>{% endfor %}
    </select></label></div>
    <div><label>CPU threads <span class="fh">0 = automatic</span>
      <input type="number" name="cpu_threads" min="0" max="64" value="{{ cfg['transcription'].get('cpu_threads','0') }}"></label></div>
  </div>
</div>

<div class="card expert-only">
  <h2>Find the best settings automatically</h2>
  <p class="hint">Tries every engine and model available on this computer and measures both <b>speed</b> and <b>mistakes</b>. The fastest option is not always the best, so results are ranked by accuracy first. First run downloads models and can take several minutes.</p>
  <div style="display:flex;gap:.75rem;align-items:center;flex-wrap:wrap">
    <button type="button" id="benchBtn" onclick="startBench(false)">Run benchmark</button>
    <button type="button" class="ghost" onclick="startBench(true)">Quick benchmark</button>
    <span id="benchMsg" class="hint" style="margin:0"></span>
  </div>
  <div id="benchOut"></div>
</div>

<div class="card">
  <h2>Live typing</h2>
  <p class="hint">Show words as you speak, instead of waiting until you stop &mdash; the way Apple's dictation behaves.<br>
  <b>What it costs:</b> the speech engine runs continuously rather than once, so it uses noticeably more processor. Words appear about a second and a half behind your voice. Nothing you see is ever rewritten &mdash; text only appears once the engine is sure of it.</p>
  <div class="check">
    <input type="checkbox" id="lv" name="live" {{ 'checked' if cfg['transcription'].getboolean('live', False) }}>
    <label for="lv">Type words as I speak <span class="fh">Turn off on an older or battery-powered machine.</span></label>
  </div>
  <div class="check">
    <input type="checkbox" id="hwe" name="hold_while_editing" {{ 'checked' if cfg['transcription'].getboolean('hold_while_editing', True) }}>
    <label for="hwe">Pause typing while I edit <span class="fh">If you go back to fix a word, new text waits instead of landing in the middle of your correction. It appears once you stop.</span></label>
  </div>
  <div class="row expert-only">
    <div><label>Update interval <span class="fh">Seconds between passes. Lower feels more immediate but uses more processor.</span>
      <input type="number" step="0.1" min="0.4" max="5" name="live_interval" value="{{ cfg['transcription'].get('live_interval','1.4') }}"></label></div>
    <div><label>Wait after editing <span class="fh">Seconds of stillness before held text is typed.</span>
      <input type="number" step="0.1" min="0.3" max="5" name="edit_idle_seconds" value="{{ cfg['transcription'].get('edit_idle_seconds','1.2') }}"></label></div>
  </div>
</div>

<div class="card">
  <h2>Accuracy</h2>
  <p class="hint">Every model is a trade between accuracy, speed and download size. There is no best one &mdash; only the right one for your machine and your work. Each option below states what it costs you, not just what it gives you.</p>
  <div class="choices">
    {% for value, name, size, gain, cost, simple in models %}
    <label class="choice {{ '' if simple else 'expert-only' }}">
      <input type="radio" name="model" value="{{value}}" {{ 'checked' if cfg['transcription']['model']==value }}>
      <span class="choice-body">
        <span class="choice-head"><b>{{ name }}</b><span class="tag">{{ size }}</span>
          <span class="tag mono expert-only">{{ value }}</span></span>
        <span class="gain">{{ gain }}</span>
        <span class="cost">Trade-off: {{ cost }}</span>
      </span>
    </label>
    {% endfor %}
  </div>
  <label class="expert-only">Language <span class="fh">Use <code>en</code> for English. <code>auto</code> is slower and less accurate.</span>
    <input type="text" name="language" value="{{ cfg['transcription']['language'] }}"></label>
  <div class="check">
    <input type="checkbox" id="ud" name="use_dictionary" {{ 'checked' if cfg['transcription'].getboolean('use_dictionary') }}>
    <label for="ud">Use my word list <span class="fh">Strongly recommended. This is what stops "servo" becoming "server".</span></label>
  </div>
</div>

<div class="card">
  <h2>Grammar cleanup</h2>
  <p class="hint">Tidies grammar and removes "um" and "uh" using a second AI model, also running on this computer.<br>
  <b>What it costs:</b> a few seconds before your text appears, a one-off 1 GB download, and a small risk the model rewords something slightly. Leave it off if you want your words exactly as spoken.</p>
  <div class="check">
    <input type="checkbox" id="ce" name="cleanup_enabled" {{ 'checked' if cfg['cleanup'].getboolean('enabled') }}>
    <label for="ce">Turn on grammar cleanup <span class="fh">Requires Ollama to be installed and running.</span></label>
  </div>
  <label class="expert-only">Cleanup model <span class="fh">Leave blank for the built-in default.</span>
    <input type="text" name="cleanup_model" value="{{ cfg['cleanup']['model'] }}"></label>
</div>

<div class="card">
  <h2>Where the text goes</h2>
  <div class="row">
    <div><label>Method<select name="output_method">
      <option value="type" {{ 'selected' if cfg['output']['method']=='type' }}>Type it out (works everywhere)</option>
      <option value="clipboard" {{ 'selected' if cfg['output']['method']=='clipboard' }}>Paste it (faster for long text)</option>
    </select></label></div>
    <div class="expert-only"><label>Pause before typing <span class="fh">seconds, to refocus a window</span>
      <input type="number" step="0.05" min="0" max="5" name="delay_before_type" value="{{ cfg['output'].get('delay_before_type','0.15') }}"></label></div>
    <div class="expert-only"><label>Max recording <span class="fh">seconds, safety net</span>
      <input type="number" min="10" max="3600" name="max_seconds" value="{{ cfg['audio'].get('max_seconds','300') }}"></label></div>
  </div>
</div>

<div class="card">
  <h2>My word list</h2>
  <p class="hint">One word or phrase per line. Add anything unusual you say often — technical terms, product names, people's names. Lines starting with <code>#</code> are notes and are ignored.<br>
  <b>This is the single most effective setting here.</b> It is what stops “servo” being written as “server”, and it costs nothing in speed.</p>
  {% if dict_used > dict_limit %}
  <p class="warn"><b>Your list is too long.</b> It needs about {{ dict_used }} of the {{ dict_limit }} the speech engine accepts, so words near the bottom are being ignored. Remove the ones you rarely say.</p>
  {% elif dict_used > dict_limit * 0.8 %}
  <p class="warn"><b>Nearly full.</b> About {{ dict_used }} of {{ dict_limit }} used. Once it is full, extra words are ignored silently rather than flagged.</p>
  {% else %}
  <p class="hint" style="margin:.4rem 0 1rem">{{ dict_terms }} terms, using about {{ dict_used }} of {{ dict_limit }} — room for roughly {{ ((dict_limit - dict_used) / 2.4) | int }} more.</p>
  {% endif %}
  <textarea name="dictionary" spellcheck="false">{{ dictionary }}</textarea>
</div>

<button type="submit">Save settings</button>
</form>
</div>
<script>
function setMode(m){
  document.body.setAttribute('data-mode', m);
  document.querySelectorAll('.mode').forEach(function(b){
    b.classList.toggle('on', b.dataset.mode === m);
  });
  try { localStorage.setItem('lyrebird-mode', m); } catch(e) {}
}
(function(){
  var m = 'simple';
  try { m = localStorage.getItem('lyrebird-mode') || 'simple'; } catch(e) {}
  setMode(m);
})();
function startBench(quick){
  document.getElementById('benchBtn').disabled = true;
  document.getElementById('benchMsg').innerHTML = '<span class="spin"></span> running — this can take several minutes';
  fetch('/benchmark/start?quick=' + (quick?1:0), {method:'POST'}).then(poll);
}
function poll(){
  setTimeout(function(){
    fetch('/benchmark/status').then(r=>r.json()).then(function(s){
      if(s.running){ poll(); return; }
      document.getElementById('benchBtn').disabled = false;
      if(s.error){ document.getElementById('benchMsg').textContent = 'Failed: ' + s.error; return; }
      document.getElementById('benchMsg').textContent = 'Done. Ranked by accuracy, then speed.';
      var h = '<table class="bench"><tr><th>Engine</th><th>Model</th><th>Speed</th><th>Mistakes</th><th></th></tr>';
      s.rows.forEach(function(r,i){
        h += '<tr class="'+(i===0?'win':'')+'"><td>'+r.backend+'</td><td>'+r.model+'</td>'
           + '<td>'+(r.ok? r.speed+'x realtime':'failed')+'</td>'
           + '<td>'+(r.ok? r.wer+'%':'-')+'</td>'
           + '<td>'+(i===0?'best':'')+'</td></tr>';
      });
      h += '</table><p class="hint" style="margin-top:.75rem">'
         + '<button type="button" onclick="applyBest()">Use the best settings</button></p>';
      document.getElementById('benchOut').innerHTML = h;
    });
  }, 1500);
}
function applyBest(){
  fetch('/benchmark/apply', {method:'POST'}).then(()=>location.href='/?saved=1');
}
</script>
"""


def _run_benchmark(quick: bool) -> None:
    import subprocess

    BENCH.update(running=True, done=False, rows=[], error=None, started=time.time())
    try:
        cmd = [sys.executable, str(ROOT / "src" / "benchmark.py"), "--json"]
        if quick:
            cmd.append("--quick")
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr else "benchmark failed")
        payload = out.stdout[out.stdout.index("["):]
        BENCH["rows"] = json.loads(payload)
        BENCH["done"] = True
    except Exception as exc:                      # noqa: BLE001
        BENCH["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        BENCH["running"] = False


@app.post("/benchmark/start")
def benchmark_start():
    if not BENCH["running"]:
        threading.Thread(target=_run_benchmark,
                         args=(request.args.get("quick") == "1",), daemon=True).start()
    return jsonify(ok=True)


@app.get("/benchmark/status")
def benchmark_status():
    return jsonify(running=BENCH["running"], done=BENCH["done"],
                   rows=BENCH["rows"], error=BENCH["error"])


@app.post("/benchmark/apply")
def benchmark_apply():
    rows = [r for r in BENCH["rows"] if r.get("ok")]
    if not rows:
        return jsonify(ok=False, error="no successful results"), 400
    best = rows[0]
    backup_config()
    cfg = read_config()
    cfg["transcription"]["backend"] = best["backend"]
    cfg["transcription"]["model"] = best["model"]
    if best.get("device") not in (None, "-"):
        cfg["transcription"]["device"] = best["device"]
    if best.get("compute_type") not in (None, "-"):
        cfg["transcription"]["compute_type"] = best["compute_type"]
    with CONFIG.open("w", encoding="utf-8") as fh:
        cfg.write(fh)
    return jsonify(ok=True)


@app.get("/")
def index():
    n_terms, used, limit = backends.dictionary_budget()
    return render_template_string(
        TEMPLATE,
        cfg=read_config(),
        dict_terms=n_terms,
        dict_used=used,
        dict_limit=limit,
        dictionary=DICTIONARY.read_text(encoding="utf-8") if DICTIONARY.exists() else "",
        diags=diagnostics(),
        models=MODELS,
        model_values=MODEL_VALUES,
        keys=KEYS,
        bkends=BACKENDS,
        devs=DEVICES,
        comps=COMPUTES,
        saved=request.args.get("saved") == "1",
    )


@app.post("/save")
def save():
    backup_config()
    cfg = read_config()
    f = request.form

    cfg["hotkey"]["key"] = f.get("hotkey_key", "f5")
    cfg["hotkey"]["mode"] = f.get("hotkey_mode", "toggle")
    cfg["transcription"]["model"] = f.get("model", "large-v3-turbo")
    cfg["transcription"]["language"] = f.get("language", "en").strip() or "en"
    cfg["transcription"]["use_dictionary"] = str("use_dictionary" in f).lower()
    cfg["transcription"]["backend"] = f.get("backend", "auto")
    cfg["transcription"]["device"] = f.get("device", "auto")
    cfg["transcription"]["compute_type"] = f.get("compute_type", "auto")
    cfg["transcription"]["cpu_threads"] = f.get("cpu_threads", "0").strip() or "0"
    cfg["transcription"]["live"] = str("live" in f).lower()
    cfg["transcription"]["live_interval"] = f.get("live_interval", "1.4").strip() or "1.4"
    cfg["transcription"]["hold_while_editing"] = str("hold_while_editing" in f).lower()
    cfg["transcription"]["edit_idle_seconds"] = f.get("edit_idle_seconds", "1.2").strip() or "1.2"
    cfg["output"]["delay_before_type"] = f.get("delay_before_type", "0.15").strip() or "0.15"
    cfg["audio"]["max_seconds"] = f.get("max_seconds", "300").strip() or "300"
    cfg["cleanup"]["enabled"] = str("cleanup_enabled" in f).lower()
    cfg["cleanup"]["model"] = f.get("cleanup_model", "llama3.1:8b").strip()
    cfg["output"]["method"] = f.get("output_method", "type")

    with CONFIG.open("w", encoding="utf-8") as fh:
        cfg.write(fh)
    DICTIONARY.write_text(f.get("dictionary", ""), encoding="utf-8")
    return redirect(url_for("index", saved="1"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser settings for local-dictation.")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    print(f"\n  Settings page:  http://127.0.0.1:{args.port}\n  Ctrl+C to stop.\n")
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
