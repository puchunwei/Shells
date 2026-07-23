#!/usr/bin/env bash
# ccswitch — Claude Code API endpoint switcher (bash/zsh)
# Source this file from ~/.bashrc or ~/.zshrc, or let install.sh do it.
#
# The CCSWITCH_BACKEND variable points to ccswitch_backend.py.
# install.sh sets it automatically; override it if you move things around.

_ccswitch_normalize_model() {
    local m="$1"
    if [[ -n "$m" && "$m" != *'[1m]'* ]]; then
        m="${m}[1m]"
    fi
    printf '%s' "$m"
}

ccswitch() {
    local target="${1:-status}"
    local backend="${CCSWITCH_BACKEND:-${HOME}/.local/share/ccswitch/ccswitch_backend.py}"
    local settings="${HOME}/.claude/settings.json"
    local defaults="${HOME}/.claude/ccswitch-defaults.json"
    local profile="${HOME}/.claude/ccswitch-profile"

    if [[ ! -f "$backend" ]]; then
        echo "❌ 找不到后端脚本: $backend"
        echo "   请检查 CCSWITCH_BACKEND 变量或重新运行 install.sh"
        return 1
    fi

    if [[ ! -f "$settings" ]]; then
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
            echo "   模型名自动补 [1m]，直接输 claude-sonnet-5 即可"
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
            echo "   ccswitch help             显示此帮助"
            echo ""
            echo "模型名自动补 [1m]，直接输短名即可，例如："
            echo "   ccswitch default claude-sonnet-5   → claude-sonnet-5[1m] (所有模型统一)"
            echo "   ccswitch mo claude-opus-4-8        → claude-opus-4-8[1m]"
            echo "   ccswitch default                   → 从快照恢复 (opus/haiku/sonnet 各自独立)"
            echo ""
            echo "MO 端点配置（在 shell 配置文件中添加）:"
            echo "   export MO_ANTHROPIC_BASE_URL=\"https://...\""
            echo "   export MO_ANTHROPIC_API_KEY=\"...\""
            ;;

        *)
            echo "❌ 未知子命令: $target"
            echo "   可用: init, mo, default, status, help"
            return 1
            ;;
    esac
}
