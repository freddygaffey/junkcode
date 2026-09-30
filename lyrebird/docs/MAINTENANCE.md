# Maintenance

## Routine tasks

**Change the hotkey or model** — easiest through the settings page:

```bash
.venv/bin/python src/webui.py     # then open http://127.0.0.1:5000
```

Or edit `config/config.ini` directly. Restart `dictate.py` to apply.

**Add vocabulary** — append to `config/dictionary.txt`, one term per line. Do this
whenever a word is misheard twice. It is the highest-return maintenance action.

**Update dependencies**

```bash
.venv/bin/pip install --upgrade -r requirements.txt
./setup.sh --check
```

**Update the cleanup model**

```bash
ollama pull llama3.1:8b
ollama list
```

## Switching models

Models download automatically on first use and cache in `~/.cache/huggingface`.

| Model | Size | When to use |
|---|---|---|
| `tiny` / `base` | 75 MB / 145 MB | Older or low-memory machines |
| `small` | 480 MB | Intel Macs |
| `large-v3-turbo` | 1.6 GB | **Default.** Apple Silicon, 16 GB+ |
| `large-v3` | 3 GB | Maximum accuracy, noticeably slower |

To reclaim disk space: `rm -rf ~/.cache/huggingface/hub/models--Systran--*`

## Backups

`src/webui.py` copies both config files to `config/backups/` before every save and
keeps the 20 most recent. To roll back:

```bash
cp config/backups/config-20260823-143022.ini config/config.ini
```

## Verifying an install

```bash
./setup.sh --check                          # full diagnostics
.venv/bin/python src/dictate.py --devices   # list microphones
.venv/bin/python src/dictate.py --once      # one recording, printed not typed
```

`--once` is the safest test: it never types into another application.

## If you come back to this in a year

Read `docs/ARCHITECTURE.md` first — it explains why each component was chosen,
which is the part that is hard to reconstruct. Then run `./setup.sh --check`,
which tells you what is actually broken rather than what you assume is broken.
