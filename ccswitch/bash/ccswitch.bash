#!/usr/bin/env bash
# Source from bash/zsh to synchronize the current shell after a successful apply.

_ccswitch_version_check() {
    # Validate both versions and compare numerically, including multi-digit parts.
    python3 - "$1" "$2" <<'PY'
import re, sys
versions = sys.argv[1:]
if not all(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', v) for v in versions):
    sys.exit('ccswitch: invalid version; keeping current installation')
if tuple(map(int, versions[1].split('.'))) < tuple(map(int, versions[0].split('.'))):
    sys.exit('ccswitch: refusing downgrade; keeping current installation')
PY
}

_ccswitch_update() {
    local shell_name="${1:-bash}"
    if [[ -z "${1:-}" && -n "${ZSH_VERSION:-}" ]]; then shell_name=zsh; fi
    local backend="${CCSWITCH_BACKEND:-${HOME}/.local/share/ccswitch/ccswitch_backend.py}"
    local base="https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch"
    local current latest installer result
    current="$(python3 "$backend" version)" || return $?
    latest="$(curl --fail --show-error --silent --location --connect-timeout 5 --max-time 15 "$base/VERSION")" || return $?
    _ccswitch_version_check "$current" "$latest" || return $?
    installer="$(mktemp "${TMPDIR:-/tmp}/ccswitch-update.XXXXXX")" || return 1
    if curl --fail --show-error --silent --location --connect-timeout 5 --max-time 30 "$base/install.sh" -o "$installer"; then
        if bash "$installer" --shell "$shell_name" --update; then result=0; else result=$?; fi
    else
        result=$?
    fi
    rm -f -- "$installer"
    if [[ "$result" -eq 0 && "$shell_name" != fish ]]; then
        source "${HOME}/.local/share/ccswitch/ccswitch.bash"
    fi
    return "$result"
}

_ccswitch_version() {
    local backend="${CCSWITCH_BACKEND:-${HOME}/.local/share/ccswitch/ccswitch_backend.py}"
    local current latest
    current="$(python3 "$backend" version)" || return $?
    printf 'ccswitch %s\n' "$current"
    if latest="$(curl --fail --silent --location --connect-timeout 3 --max-time 5 \
        https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/VERSION 2>/dev/null)"; then
        if _ccswitch_version_check "$current" "$latest"; then
            printf 'Remote version: %s\n' "$latest"
            [[ "$current" == "$latest" ]] || printf 'Run ccswitch update to update.\n'
        fi
    else
        printf 'Remote version unavailable.\n'
    fi
    return 0
}

ccswitch() {
    local backend="${CCSWITCH_BACKEND:-${HOME}/.local/share/ccswitch/ccswitch_backend.py}"
    local command_name="${1:-status}"
    case "$command_name" in
        update) _ccswitch_update; return $? ;;
        version|-v|--version)
            if [[ $# -eq 1 ]]; then _ccswitch_version; return $?; fi ;;
    esac
    local exports_file result line key value
    exports_file="$(mktemp "${TMPDIR:-/tmp}/ccswitch-env.XXXXXX")" || return 1
    # Preserve the terminal: stdout/stdin must reach the backend directly.
    if python3 "$backend" "$@" --shell-output "$exports_file"; then result=0; else result=$?; fi
    if [[ "$result" -eq 0 ]]; then
        while IFS= read -r line; do
            [[ "$line" == *=* ]] || continue
            key="${line%%=*}"
            value="${line#*=}"
            case "$key" in
                ANTHROPIC_BASE_URL|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|\
                ANTHROPIC_MODEL|ANTHROPIC_SMALL_FAST_MODEL|ANTHROPIC_DEFAULT_MODEL|\
                ANTHROPIC_DEFAULT_OPUS_MODEL|ANTHROPIC_DEFAULT_SONNET_MODEL|\
                ANTHROPIC_DEFAULT_HAIKU_MODEL|ANTHROPIC_DEFAULT_FABLE_MODEL|\
                CLAUDE_CODE_SUBAGENT_MODEL|CLAUDE_CODE_SUBAGENT_MODEL_FORCE|\
                ANTHROPIC_CUSTOM_MODEL_OPTION|ANTHROPIC_CUSTOM_MODEL_OPTION_NAME|\
                ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION|ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES|\
                ANTHROPIC_DEFAULT_OPUS_MODEL_NAME|ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION|ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES|\
                ANTHROPIC_DEFAULT_SONNET_MODEL_NAME|ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION|ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES|\
                ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME|ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION|ANTHROPIC_DEFAULT_HAIKU_MODEL_SUPPORTED_CAPABILITIES|\
                ANTHROPIC_DEFAULT_FABLE_MODEL_NAME|ANTHROPIC_DEFAULT_FABLE_MODEL_DESCRIPTION|ANTHROPIC_DEFAULT_FABLE_MODEL_SUPPORTED_CAPABILITIES)
                    export "$key=$value" ;;
            esac
        done < "$exports_file"
    fi
    rm -f -- "$exports_file"
    return "$result"
}
