#!/usr/bin/env bash
# ccswitch — Claude Code API endpoint switcher (bash/zsh)
# Source this file from ~/.bashrc or ~/.zshrc, or let install.sh do it.
#
# The CCSWITCH_BACKEND variable points to ccswitch_backend.py.
# install.sh sets it automatically; override it if you move things around.

_ccswitch_normalize_model() {
    local backend="${CCSWITCH_BACKEND:-${HOME}/.local/share/ccswitch/ccswitch_backend.py}"
    MODEL="$1" python3 "$backend" normalize-model
}

_ccswitch_update() {
    local shell_name="bash"
    [[ -n "${ZSH_VERSION:-}" ]] && shell_name="zsh"
    local installer
    installer="$(mktemp "${TMPDIR:-/tmp}/ccswitch-update.XXXXXX")" || return 1
    if ! curl --fail --show-error --silent --location \
        --connect-timeout 5 --max-time 30 \
        "https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh" \
        -o "$installer"; then
        rm -f -- "$installer"
        echo "❌ ccswitch 更新脚本下载失败"
        return 1
    fi
    if ! bash "$installer" --shell "$shell_name" --update; then
        rm -f -- "$installer"
        return 1
    fi
    rm -f -- "$installer"
    source "${HOME}/.local/share/ccswitch/ccswitch.bash"
}

_ccswitch_version() {
    local backend="${CCSWITCH_BACKEND:-${HOME}/.local/share/ccswitch/ccswitch_backend.py}"
    local current latest
    current="$(python3 "$backend" version)" || return 1
    echo "ccswitch 版本："
    echo "   当前版本: $current"
    if latest="$(curl --fail --silent --location --connect-timeout 3 --max-time 5 \
        "https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/VERSION" 2>/dev/null)" \
        && [[ "$latest" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "   最新版本: $latest"
        if [[ "$current" == "$latest" ]]; then
            echo "   状态:     ✓ 已是最新版本"
        else
            echo "   状态:     ↑ 有新版本，请运行 ccswitch update"
        fi
    else
        echo "   最新版本: 无法获取（请检查网络）"
    fi
}

ccswitch() {
    local target="${1:-status}"
    local backend="${CCSWITCH_BACKEND:-${HOME}/.local/share/ccswitch/ccswitch_backend.py}"
    local settings="${HOME}/.claude/settings.json"
    local defaults="${HOME}/.claude/ccswitch-defaults.json"
    local profile="${HOME}/.claude/ccswitch-profile"

    if [[ "$target" == "update" ]]; then
        _ccswitch_update
        return $?
    fi

    if [[ ! -f "$backend" ]]; then
        echo "❌ 找不到后端脚本: $backend"
        echo "   请检查 CCSWITCH_BACKEND 变量或重新运行 install.sh"
        return 1
    fi

    if [[ "$target" != "models" && "$target" != "version" && "$target" != "-v" && "$target" != "--version" && "$target" != "help" && "$target" != "-h" && "$target" != "--help" && ! -f "$settings" ]]; then
        echo "❌ $settings 不存在，请先启动一次 Claude Code 让它生成配置文件"
        return 1
    fi

    case "$target" in
        init)
            python3 "$backend" init || { echo "❌ 保存默认配置失败"; return 1; }
            echo "✅ 已保存默认端点配置到 $defaults"
            echo "   后续 ccswitch default 将从此文件恢复"
            ;;

        mo)
            if [[ -z "$MO_ANTHROPIC_BASE_URL" || -z "$MO_ANTHROPIC_API_KEY" ]]; then
                # 尝试从 rc 文件加载（可能当前 shell 启动时还没配置）
                local _rc="${HOME}/.$(basename "${SHELL:-bash}")rc"
                [[ -f "$_rc" ]] && source "$_rc" 2>/dev/null
            fi
            if [[ -z "$MO_ANTHROPIC_BASE_URL" || -z "$MO_ANTHROPIC_API_KEY" ]]; then
                echo "❌ 未设置 MO_ANTHROPIC_BASE_URL 或 MO_ANTHROPIC_API_KEY"
                echo ""
                echo "请在你的 shell 配置文件中添加，例如:"
                echo "   export MO_ANTHROPIC_BASE_URL=\"https://your-endpoint.example.com/api/anthropic\""
                echo "   export MO_ANTHROPIC_API_KEY=\"your-api-key\""
                return 1
            fi

            local model
            model=$(_ccswitch_normalize_model "${2:-claude-opus-4-6}")

            MO_BASE_URL="$MO_ANTHROPIC_BASE_URL" \
            MO_API_KEY="$MO_ANTHROPIC_API_KEY" \
            MODEL="$model" \
            python3 "$backend" mo || { echo "❌ 修改 settings.json 失败"; return 1; }

            export ANTHROPIC_BASE_URL="$MO_ANTHROPIC_BASE_URL"
            export ANTHROPIC_API_KEY="$MO_ANTHROPIC_API_KEY"
            local v
            for v in ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL; do
                export "$v=$model"
            done
            unset ANTHROPIC_AUTH_TOKEN
            printf 'mo\n' > "$profile"

            echo "✅ 已切换到 MO 端点 (settings.json 已更新)"
            echo "   BASE_URL: $MO_ANTHROPIC_BASE_URL"
            echo "   MODEL:    $model"
            echo ""
            echo "⚠️  已启动的 Claude Code 进程需要重启；当前 shell 后续运行 claude 已生效"
            ;;

        default|local)
            if [[ ! -f "$defaults" ]]; then
                echo "❌ 默认配置文件不存在: $defaults"
                echo "   请先运行 ccswitch init 保存默认端点配置"
                return 1
            fi

            local unified_model=""
            if [[ -n "$2" ]]; then
                unified_model=$(_ccswitch_normalize_model "$2")
            fi

            local output
            output=$(UNIFIED_MODEL="$unified_model" python3 "$backend" default) || {
                echo "❌ 修改 settings.json 失败"
                return 1
            }

            local key val
            while IFS='=' read -r key val; do
                [[ -n "$key" ]] && export "$key=$val"
            done <<< "$output"
            unset ANTHROPIC_API_KEY
            [[ -z "$ANTHROPIC_AUTH_TOKEN" ]] && unset ANTHROPIC_AUTH_TOKEN
            printf 'default\n' > "$profile"

            echo "✅ 已切换回默认端点 (settings.json 已更新)"
            echo "   BASE_URL:      $ANTHROPIC_BASE_URL"
            echo "   MODEL:         $ANTHROPIC_MODEL"
            if [[ -z "$unified_model" ]]; then
                echo "   SMALL_FAST:    $ANTHROPIC_SMALL_FAST_MODEL"
                echo "   SONNET:        $ANTHROPIC_DEFAULT_SONNET_MODEL"
                echo "   HAIKU:         $ANTHROPIC_DEFAULT_HAIKU_MODEL"
            fi
            echo ""
            echo "⚠️  已启动的 Claude Code 进程需要重启；当前 shell 后续运行 claude 已生效"
            ;;

        status)
            echo "📡 Claude Code settings.json 当前 env 配置:"
            local active_profile="default"
            if [[ -r "$profile" ]]; then
                read -r active_profile < "$profile"
            fi
            echo "   PROFILE:    $active_profile"

            python3 "$backend" status || { echo "❌ 读取 settings.json 失败"; return 1; }

            echo ""
            echo "📋 用法:"
            echo "   ccswitch init             - 保存当前环境为默认端点配置（首次必须执行）"
            echo "   ccswitch mo [model]       - 切换到 MO 端点"
            echo "   ccswitch default [model]  - 切换回默认端点"
            echo "   ccswitch status           - 显示当前配置"
            echo "   ccswitch models           - 显示默认网关模型"
            echo "   ccswitch version          - 检查是否为最新版本"
            echo "   ccswitch update           - 更新 ccswitch"
            echo "   不再自动追加 [1m]，会清理历史 [1m] 后缀"
            ;;

        models)
            python3 "$backend" models
            ;;

        version|-v|--version)
            _ccswitch_version
            ;;

        help|-h|--help)
            echo "ccswitch — Claude Code API 端点切换工具"
            echo ""
            echo "首次使用:"
            echo "   ccswitch init             保存当前环境变量为默认端点配置"
            echo ""
            echo "切换端点:"
            echo "   ccswitch mo [model]       切换到 MO 端点 (所有模型统一为该值)"
            echo "   ccswitch default [model]  切换回默认端点 (所有模型统一为该值)"
            echo "   ccswitch default          不指定模型时，恢复各模型的独立配置"
            echo "   ccswitch status           显示当前配置"
            echo "   ccswitch models           显示默认网关模型"
            echo "   ccswitch version          显示本地版本并检查更新"
            echo "   ccswitch update           更新 ccswitch（保留端点配置）"
            echo "   ccswitch help             显示此帮助"
            echo ""
            echo "不会自动追加 [1m]；会自动清理历史 [1m] 后缀，例如："
            echo "   ccswitch default claude-sonnet-5   → claude-sonnet-5 (所有模型统一)"
            echo "   ccswitch default claude-opus-4-6[1m] → claude-opus-4-6"
            echo "   ccswitch default qwen3.7-max        → qwen3.7-max"
            echo "   ccswitch default GLM-5.2            → GLM-5.2"
            echo "   ccswitch default                   → 从快照恢复 (opus/haiku/sonnet 各自独立)"
            echo ""
            echo "MO 端点配置（在 shell 配置文件中添加）:"
            echo "   export MO_ANTHROPIC_BASE_URL=\"https://...\""
            echo "   export MO_ANTHROPIC_API_KEY=\"...\""
            ;;

        *)
            echo "❌ 未知子命令: $target"
            echo "   可用: init, mo, default, status, models, version, update, help"
            return 1
            ;;
    esac
}
