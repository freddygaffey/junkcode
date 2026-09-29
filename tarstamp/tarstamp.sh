# tarstamp — timestamped tar snapshots
# https://github.com/freddygaffey/tarstamp

tarstamp() {
    [ -z "$1" ]   && { echo "usage: tarstamp <path>" >&2; return 1; }
    [ $# -gt 1 ]  && { echo "tarstamp: only one path allowed" >&2; return 1; }
    [ ! -e "$1" ] && { echo "tarstamp: '$1' does not exist" >&2; return 1; }
    local name archive start elapsed size
    name=$(basename "${1%/}")
    archive="${name}_$(date +%Y%m%d_%H%M%S).tar"
    start=$(perl -MTime::HiRes=time -e 'printf "%.3f", time' 2>/dev/null || date +%s)
    tar cf "$archive" "$1" || return 1
    elapsed=$(perl -MTime::HiRes=time -e "printf \"%.1f\", time - $start" 2>/dev/null \
              || echo "$(($(date +%s) - start))")
    size=$(du -h "$archive" | cut -f1)
    echo "→ $archive | ${elapsed}s | $size"
}

untarstamp() {
    [ -z "$1" ] && { echo "usage: untarstamp <archive>" >&2; return 1; }
    [ ! -f "$1" ] && { echo "untarstamp: '$1' not found" >&2; return 1; }
    local dest
    dest="$(dirname "$1")/$(basename "$1" .tar).extracted"
    mkdir -p "$dest"
    tar xf "$1" -C "$dest" && echo "→ $dest"
}

if [ -n "$BASH_VERSION" ]; then
    complete -f -d tarstamp
    complete -f untarstamp
elif [ -n "$ZSH_VERSION" ]; then
    autoload -Uz compinit && compinit -i 2>/dev/null
    compdef _files tarstamp 2>/dev/null
    compdef _files untarstamp 2>/dev/null
fi
