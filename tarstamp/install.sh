#!/usr/bin/env sh
# tarstamp installer (Linux / macOS / Git Bash / WSL)
# Usage: curl -fsSL https://raw.githubusercontent.com/freddygaffey/tarstamp/main/install.sh | sh
set -e

REPO_RAW="https://raw.githubusercontent.com/freddygaffey/tarstamp/main"
DEST="${HOME}/.tarstamp.sh"
LINE='[ -f "$HOME/.tarstamp.sh" ] && . "$HOME/.tarstamp.sh"'

echo "tarstamp: downloading -> $DEST"
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$REPO_RAW/tarstamp.sh" -o "$DEST"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$DEST" "$REPO_RAW/tarstamp.sh"
else
    echo "tarstamp: need curl or wget" >&2
    exit 1
fi
chmod +r "$DEST"

added=0
skipped=0
for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile"; do
    [ -f "$rc" ] || continue
    if grep -qF ".tarstamp.sh" "$rc"; then
        echo "tarstamp: $rc already references tarstamp, skipping"
        continue
    fi
    if [ -t 0 ] || [ -e /dev/tty ]; then
        printf "tarstamp: append the following line to %s?\n  %s\n[y/N] " "$rc" "$LINE"
        read ans < /dev/tty 2>/dev/null || ans=""
    else
        ans=""
    fi
    case "$ans" in
        [yY]|[yY][eE][sS])
            printf '\n# tarstamp\n%s\n' "$LINE" >> "$rc"
            echo "tarstamp: added source line to $rc"
            added=1
            ;;
        *)
            echo "tarstamp: skipped $rc"
            skipped=1
            ;;
    esac
done

if [ $added -eq 0 ] && [ $skipped -eq 0 ]; then
    echo "tarstamp: no rc file modified (already installed or none found)"
fi
if [ $skipped -eq 1 ]; then
    echo "tarstamp: to load manually, add to your shell rc:"
    echo "          $LINE"
fi

echo "tarstamp: done. restart shell or run:  . $DEST"
