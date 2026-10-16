#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch"
LOCAL=0
FORCE_SHELL=""
UPDATE_ONLY=0
TEMP_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --local) LOCAL=1; shift ;;
        --update) UPDATE_ONLY=1; shift ;;
        --shell)
            [[ $# -ge 2 ]] || { echo '--shell requires bash, zsh or fish' >&2; exit 1; }
            case "$2" in bash|zsh|fish) FORCE_SHELL="$2" ;; *) echo 'Unsupported shell' >&2; exit 1 ;; esac
            shift 2 ;;
        --url|--key)
            echo 'Credential installer options were removed. Run ccswitch add NAME in a terminal, or import a private JSON file.' >&2
            exit 1 ;;
        -h|--help)
            echo 'usage: install.sh [--local] [--shell bash|zsh|fish] [--update]'
            echo '--local copies from this script directory without network access.'
            echo '--update replaces program files; settings and the profile store are preserved.'
            exit 0 ;;
        *) echo 'Unknown installer option; see --help' >&2; exit 1 ;;
    esac
done

cleanup() { [[ -z "$TEMP_DIR" ]] || rm -rf -- "$TEMP_DIR"; }
trap cleanup EXIT
fetch_url() {
    curl --fail --show-error --silent --location --connect-timeout 5 --max-time 30 "$1" -o "$2"
}
detect_shell() {
    local pid="${PPID:-0}" process_name shell_name depth
    if [[ -n "$FORCE_SHELL" ]]; then USER_SHELL="$FORCE_SHELL"; return; fi
    for ((depth=0; depth<8 && pid>1; depth++)); do
        process_name="$(ps -p "$pid" -o comm= 2>/dev/null | tr -d '[:space:]')"
        shell_name="${process_name##*/}"
        case "${shell_name#-}" in bash|zsh|fish) USER_SHELL="${shell_name#-}"; return ;; esac
        pid="$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d '[:space:]')"
        [[ "$pid" =~ ^[0-9]+$ ]] || break
    done
    echo 'Cannot detect current shell; use --shell bash|zsh|fish' >&2
    return 1
}
version_guard() {
    python3 - "$1" "$2" <<'PY'
import re, sys
old, new = sys.argv[1:]
if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', new):
    sys.exit('Invalid package version; installation preserved')
if old:
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', old):
        sys.exit('Invalid installed version; installation preserved')
    if tuple(map(int, new.split('.'))) < tuple(map(int, old.split('.'))):
        sys.exit('Refusing downgrade; installation preserved')
PY
}

detect_shell
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ccswitch-install.XXXXXX")"
SOURCE_DIR=""
if [[ "$LOCAL" -eq 1 ]]; then
    SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    cp "$SOURCE_DIR/VERSION" "$TEMP_DIR/VERSION"
else
    fetch_url "$REPO_RAW/VERSION" "$TEMP_DIR/VERSION"
fi
DEST="$HOME/.local/share/ccswitch"
CURRENT=""
if [[ -f "$DEST/VERSION" ]]; then CURRENT="$(cat "$DEST/VERSION")"; fi
CANDIDATE="$(cat "$TEMP_DIR/VERSION")"
version_guard "$CURRENT" "$CANDIDATE"

# Stage the complete package before replacing any installed program.
FILES=(lib/cloudcli-models.json lib/ccswitch_backend.py lib/ccswitch_profiles.py lib/ccswitch_cli.py lib/ccswitch_slots.py lib/ccswitch_ui.py bash/ccswitch.bash fish/ccswitch.fish bin/ccswitch)
for relative in "${FILES[@]}"; do
    name="${relative##*/}"
    # The launcher has the same basename as no other package file.
    if [[ "$LOCAL" -eq 1 ]]; then cp "$SOURCE_DIR/$relative" "$TEMP_DIR/$name"
    else fetch_url "$REPO_RAW/$relative" "$TEMP_DIR/$name"; fi
done
mkdir -p "$DEST" "$HOME/.local/bin"
for name in cloudcli-models.json VERSION ccswitch_backend.py ccswitch_profiles.py ccswitch_cli.py ccswitch_slots.py ccswitch_ui.py ccswitch.bash ccswitch.fish; do
    install -m 644 "$TEMP_DIR/$name" "$DEST/$name"
done
install -m 755 "$TEMP_DIR/ccswitch" "$HOME/.local/bin/ccswitch"
case "$USER_SHELL" in
    fish)
        FISH_FUNCTIONS="${XDG_CONFIG_HOME:-$HOME/.config}/fish/functions"
        mkdir -p "$FISH_FUNCTIONS"
        install -m 644 "$TEMP_DIR/ccswitch.fish" "$FISH_FUNCTIONS/ccswitch.fish" ;;
    bash|zsh)
        RC_FILE="$HOME/.${USER_SHELL}rc"
        # A literal HOME expression is safe even when the actual path has spaces/quotes.
        SOURCE_LINE='source "$HOME/.local/share/ccswitch/ccswitch.bash"'
        if ! python3 - "$RC_FILE" "$DEST/ccswitch.bash" <<'PYRC'
import os, shlex, sys
from pathlib import Path
rc, destination = sys.argv[1:]
try:
    lines = Path(rc).read_text().splitlines()
except FileNotFoundError:
    lines = []
for line in lines:
    try:
        lexer = shlex.shlex(line, posix=False)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        continue
    if len(words) == 2 and words[0] in ('source', '.'):
        # Recognize official HOME/tilde/absolute spellings without executing RC.
        token = words[1]
        quoted = token[:1] in ("'", '"')
        path = token[1:-1] if quoted else token
        if not token.startswith("'"):
            path = path.replace('${HOME}', os.environ['HOME']).replace('$HOME', os.environ['HOME'])
        if not quoted:
            path = os.path.expanduser(path)
        if path == destination:
            sys.exit(0)
sys.exit(1)
PYRC
        then
            printf '\n# ccswitch\n%s\n' "$SOURCE_LINE" >> "$RC_FILE"
        fi ;;
esac
printf 'ccswitch %s installed for %s. Open a new shell.\n' "$CANDIDATE" "$USER_SHELL"
printf '%s\n' 'Run ccswitch add NAME to enter a connection, then ccswitch use and ccswitch slots.'
printf '%s\n' 'Add ~/.local/bin to PATH for the standalone command; it cannot update parent-shell exports.'
