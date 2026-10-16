function ccswitch --description 'Manage Claude connections and model slots'
    set -l backend "$HOME/.local/share/ccswitch/ccswitch_backend.py"
    if set -q CCSWITCH_BACKEND; and test -n "$CCSWITCH_BACKEND"
        set backend "$CCSWITCH_BACKEND"
    end
    set -l command_name status
    if test (count $argv) -gt 0
        set command_name "$argv[1]"
    end
    if test "$command_name" = update; or begin
        contains -- "$command_name" version -v --version; and test (count $argv) -eq 1
    end
        # Share download/version checks with bash; this subprocess does not apply profiles.
        set -l wrapper (dirname "$backend")/ccswitch.bash
        if not test -f "$wrapper"
            set wrapper (dirname "$backend")/../bash/ccswitch.bash
        end
        if test "$command_name" = update
            bash -c 'source "$1"; _ccswitch_update fish' ccswitch "$wrapper"
            set -l result $status
            if test $result -eq 0
                source "$HOME/.local/share/ccswitch/ccswitch.fish"
            end
            return $result
        else
            bash -c 'source "$1"; _ccswitch_version' ccswitch "$wrapper"
            return $status
        end
    end
    set -l temp_root /tmp
    if set -q TMPDIR; and test -n "$TMPDIR"
        set temp_root "$TMPDIR"
    end
    set -l exports_file (mktemp "$temp_root/ccswitch-env.XXXXXX")
    or return 1
    python3 "$backend" $argv --shell-output "$exports_file"
    set -l result $status
    if test $result -eq 0
        while read -l line
            set -l kv (string split -m1 '=' -- "$line")
            if test (count $kv) -ne 2
                continue
            end
            switch "$kv[1]"
                case ANTHROPIC_BASE_URL ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL ANTHROPIC_DEFAULT_FABLE_MODEL CLAUDE_CODE_SUBAGENT_MODEL CLAUDE_CODE_SUBAGENT_MODEL_FORCE ANTHROPIC_CUSTOM_MODEL_OPTION ANTHROPIC_DEFAULT_OPUS_MODEL_NAME ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES ANTHROPIC_DEFAULT_SONNET_MODEL_NAME ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION ANTHROPIC_DEFAULT_HAIKU_MODEL_SUPPORTED_CAPABILITIES ANTHROPIC_DEFAULT_FABLE_MODEL_NAME ANTHROPIC_DEFAULT_FABLE_MODEL_DESCRIPTION ANTHROPIC_DEFAULT_FABLE_MODEL_SUPPORTED_CAPABILITIES ANTHROPIC_CUSTOM_MODEL_OPTION_NAME ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES
                    set -gx "$kv[1]" "$kv[2]"
            end
        end < "$exports_file"
    end
    command rm -f -- "$exports_file"
    return $result
end
