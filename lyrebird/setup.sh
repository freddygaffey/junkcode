#!/usr/bin/env bash
# local-dictation — single setup script for macOS and Linux.
# Windows users: run setup.ps1 instead.
#
#   ./setup.sh          install everything, then self-test
#   ./setup.sh --check   verify an existing install, change nothing
#   ./setup.sh --cleanup also install Ollama + pull the grammar model
#   ./setup.sh --help
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
WITH_CLEANUP=0
CHECK_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --check)   CHECK_ONLY=1 ;;
    --cleanup) WITH_CLEANUP=1 ;;
    --help|-h) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '    \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '    \033[31mfail\033[0m %s\n' "$*"; exit 1; }

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM=macos ;;
  Linux)  PLATFORM=linux ;;
  *) die "Unsupported OS '$OS'. Windows users: run setup.ps1" ;;
esac

# --------------------------------------------------------------------- check only
if [ "$CHECK_ONLY" -eq 1 ]; then
  say "Checking existing install"
  [ -d "$VENV" ] || die "No virtualenv at $VENV — run ./setup.sh first"
  exec "$VENV/bin/python" "$ROOT/src/dictate.py" --check
fi

say "local-dictation setup ($PLATFORM)"

# --------------------------------------------------------------- system packages
if [ "$PLATFORM" = macos ]; then
  command -v brew >/dev/null 2>&1 || die "Homebrew not found. Install from https://brew.sh"
  ok "homebrew $(brew --version | head -1 | awk '{print $2}')"
  if brew list portaudio >/dev/null 2>&1; then
    ok "portaudio already installed"
  else
    say "Installing portaudio (needed for microphone capture)"
    brew install portaudio || die "portaudio install failed"
  fi
else
  # Check before installing: on a shared or locked-down box we may have no sudo,
  # and that must not stop the rest of the setup.
  need_pkgs=0
  python3 -c "import venv" 2>/dev/null || need_pkgs=1
  ls /usr/include/portaudio.h >/dev/null 2>&1 || ls /usr/include/*/portaudio.h >/dev/null 2>&1 || need_pkgs=1

  if [ "$need_pkgs" -eq 0 ]; then
    ok "system packages already present"
  elif ! sudo -n true 2>/dev/null; then
    warn "no passwordless sudo - skipping system packages"
    warn "if the build fails, install these yourself:"
    warn "  python3-venv python3-dev portaudio19-dev xclip"
  elif command -v apt-get >/dev/null 2>&1; then
    say "Installing system packages (apt)"
    sudo apt-get update -qq
    sudo apt-get install -y python3-venv python3-dev portaudio19-dev xclip \
      || warn "apt install failed - continuing"
  elif command -v dnf >/dev/null 2>&1; then
    say "Installing system packages (dnf)"
    sudo dnf install -y python3-devel portaudio-devel xclip || die "dnf install failed"
  elif command -v pacman >/dev/null 2>&1; then
    say "Installing system packages (pacman)"
    sudo pacman -S --needed --noconfirm python portaudio xclip || die "pacman install failed"
  else
    warn "Unknown package manager — install portaudio and xclip yourself"
  fi
fi

# ------------------------------------------------------------------------ python
command -v python3 >/dev/null 2>&1 || die "python3 not found"
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
ok "python $PYV"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' \
  || die "Python 3.9+ required (found $PYV)"

if [ -d "$VENV" ]; then
  ok "virtualenv exists"
else
  say "Creating virtualenv"
  python3 -m venv "$VENV" || die "venv creation failed"
fi

say "Installing Python dependencies"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt" || die "pip install failed"
ok "dependencies installed"

# ------------------------------------------------------------------------ ollama
if [ "$WITH_CLEANUP" -eq 1 ]; then
  if command -v ollama >/dev/null 2>&1; then
    ok "ollama $(ollama --version 2>&1 | awk '{print $NF}')"
  else
    say "Installing Ollama"
    if [ "$PLATFORM" = macos ]; then
      brew install ollama || die "ollama install failed"
    else
      curl -fsSL https://ollama.com/install.sh | sh || die "ollama install failed"
    fi
  fi
  MODEL="$(awk -F'= *' '/^model *=/ && f {print $2; exit} /^\[cleanup\]/ {f=1}' "$ROOT/config/config.ini")"
  MODEL="${MODEL:-llama3.1:8b}"
  say "Pulling cleanup model: $MODEL (this can take a while)"
  ollama pull "$MODEL" || warn "could not pull $MODEL — pull it manually later"
  # enable cleanup in config
  "$VENV/bin/python" - "$ROOT/config/config.ini" <<'PYEOF'
import configparser, sys
p = sys.argv[1]
c = configparser.ConfigParser(); c.read(p)
c["cleanup"]["enabled"] = "true"
with open(p, "w") as fh: c.write(fh)
print("    ok   cleanup enabled in config.ini")
PYEOF
fi

# ----------------------------------------------------------------- warm the model
say "Downloading the speech model (first run only)"
"$VENV/bin/python" - <<'PYEOF'
import configparser, pathlib, sys, time
root = pathlib.Path(__file__).resolve().parent if "__file__" in dir() else pathlib.Path.cwd()
PYEOF
"$VENV/bin/python" -c "
import configparser, sys, time
from pathlib import Path
cfg = configparser.ConfigParser(); cfg.read('$ROOT/config/config.ini')
name = cfg['transcription'].get('model', 'large-v3-turbo')
print(f'    pulling {name} ...')
t0 = time.time()
from faster_whisper import WhisperModel
WhisperModel(name, device='cpu', compute_type='int8')
print(f'    ok   model ready ({time.time()-t0:.0f}s)')
" || die "model download failed"

# ---------------------------------------------------------------------- self-test
say "Self-test"
"$VENV/bin/python" "$ROOT/src/dictate.py" --check || warn "diagnostics reported problems"

say "Done"
cat <<EOF

  Run it:      $VENV/bin/python $ROOT/src/dictate.py
  Diagnose:    ./setup.sh --check
  Configure:   $ROOT/config/config.ini
  Vocabulary:  $ROOT/config/dictionary.txt

EOF
if [ "$PLATFORM" = macos ]; then
cat <<'EOF'
  macOS permissions — required before the hotkey will work:
    System Settings > Privacy & Security > Accessibility  -> allow your Terminal
    System Settings > Privacy & Security > Microphone     -> allow your Terminal
    System Settings > Keyboard > Keyboard Shortcuts > Function Keys
      -> "Use F1, F2, etc. as standard function keys"
    System Settings > Keyboard > Dictation -> turn OFF, so it does not grab the key

EOF
fi
