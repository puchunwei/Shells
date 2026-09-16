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

_ccswitch_persist_codex() {
    local rc="${HOME}/.bashrc"
    [[ -n "${ZSH_VERSION:-}" ]] && rc="${HOME}/.zshrc"
    if [[ -f "$rc" ]] && grep -q 'CODEX_ANTHROPIC_BASE_URL' "$rc"; then
        echo "   ⚠ $rc 里已有 CODEX_ANTHROPIC_BASE_URL，未重复写入"
        echo "     如需更新请手动编辑 $rc"
        return 0
    fi
    {
        printf '\n# ccswitch codex endpoint\n'
        printf 'export CODEX_ANTHROPIC_BASE_URL=%q\n' "$CODEX_ANTHROPIC_BASE_URL"
        printf 'export CODEX_ANTHROPIC_API_KEY=%q\n' "$CODEX_ANTHROPIC_API_KEY"
    } >> "$rc" || { echo "   ❌ 写入 $rc 失败"; return 1; }
    echo "   ✅ 已写入 $rc"
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

        codex)
            if [[ -z "$CODEX_ANTHROPIC_BASE_URL" || -z "$CODEX_ANTHROPIC_API_KEY" ]]; then
                # 尝试从 rc 文件加载（可能当前 shell 启动时还没配置）
                local _rc="${HOME}/.$(basename "${SHELL:-bash}")rc"
                [[ -f "$_rc" ]] && source "$_rc" 2>/dev/null
            fi

            local need_persist=0

            # 端点缺失时，先尝试复用本机 Codex CLI 已有的配置。
            # Codex CLI 用同一个网关的 /v1/responses，Claude Code 用 /v1/messages，
            # base URL 可以原样沿用。
            if [[ -z "$CODEX_ANTHROPIC_BASE_URL" || -z "$CODEX_ANTHROPIC_API_KEY" ]]; then
                local detected detected_url="" detected_key="" dline dkey dvalue
                detected=$(python3 "$backend" detect-codex 2>/dev/null || true)
                while IFS= read -r dline; do
                    [[ -z "$dline" ]] && continue
                    dkey="${dline%%=*}"
                    dvalue="${dline#*=}"
                    case "$dkey" in
                        CODEX_DETECTED_BASE_URL) detected_url="$dvalue" ;;
                        CODEX_DETECTED_API_KEY) detected_key="$dvalue" ;;
                    esac
                done <<< "$detected"
                if [[ -n "$detected_url" && -n "$detected_key" ]]; then
                    local use_detected=1
                    if [[ -t 0 ]]; then
                        echo "🔍 检测到本机 Codex CLI 配置（~/.codex）:"
                        echo "   Base URL: $detected_url"
                        echo "   API Key:  ${detected_key:0:6}…${detected_key: -4}"
                        local reuse_answer
                        read -r -p "   复用这份配置？[Y/n] " reuse_answer
                        [[ "$reuse_answer" =~ ^[Nn] ]] && use_detected=0
                    fi
                    if [[ $use_detected -eq 1 ]]; then
                        [[ -z "$CODEX_ANTHROPIC_BASE_URL" ]] && export CODEX_ANTHROPIC_BASE_URL="$detected_url"
                        [[ -z "$CODEX_ANTHROPIC_API_KEY" ]] && export CODEX_ANTHROPIC_API_KEY="$detected_key"
                        # 不设 need_persist：下次运行会再次自动检测到，
                        # 写进 rc 只会让密钥在磁盘上多一份副本。
                    fi
                fi
            fi

            if [[ -z "$CODEX_ANTHROPIC_BASE_URL" || -z "$CODEX_ANTHROPIC_API_KEY" ]]; then
                if [[ ! -t 0 ]]; then
                    echo "❌ 未设置 CODEX_ANTHROPIC_BASE_URL 或 CODEX_ANTHROPIC_API_KEY"
                    echo "   当前不是交互式终端，无法提示输入。请先手动设置:"
                    echo "   export CODEX_ANTHROPIC_BASE_URL=\"https://your-gateway\""
                    echo "   export CODEX_ANTHROPIC_API_KEY=\"your-api-key\""
                    return 1
                fi
                echo "🔧 codex 端点尚未配置，现在录入（默认只在当前 shell 生效）"
                local entered_url entered_key
                if [[ -z "$CODEX_ANTHROPIC_BASE_URL" ]]; then
                    read -r -p "   Base URL: " entered_url
                    entered_url="${entered_url#"${entered_url%%[![:space:]]*}"}"
                    entered_url="${entered_url%"${entered_url##*[![:space:]]}"}"
                    if [[ -z "$entered_url" ]]; then
                        echo "❌ Base URL 不能为空"
                        return 1
                    fi
                    export CODEX_ANTHROPIC_BASE_URL="$entered_url"
                fi
                if [[ -z "$CODEX_ANTHROPIC_API_KEY" ]]; then
                    read -r -s -p "   API Key（不回显）: " entered_key
                    echo ""
                    entered_key="${entered_key#"${entered_key%%[![:space:]]*}"}"
                    entered_key="${entered_key%"${entered_key##*[![:space:]]}"}"
                    if [[ -z "$entered_key" ]]; then
                        echo "❌ API Key 不能为空"
                        return 1
                    fi
                    export CODEX_ANTHROPIC_API_KEY="$entered_key"
                fi
                need_persist=1
            fi

            # 不做 [1m] 规范化：codex 上游是 GPT 模型，1M 标记会让 Claude Code 迟迟不压缩上下文
            local model="${2:-}"
            model="${model%\[1m\]}"
            model="${model%\[1M\]}"

            local output
            output=$(CODEX_BASE_URL="$CODEX_ANTHROPIC_BASE_URL" \
                CODEX_API_KEY="$CODEX_ANTHROPIC_API_KEY" \
                MODEL="$model" \
                python3 "$backend" codex) || { echo "❌ 修改 settings.json 失败"; return 1; }

            local exported_keys=" ANTHROPIC_BASE_URL ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL "
            local line key value
            while IFS= read -r line; do
                key="${line%%=*}"
                value="${line#*=}"
                if [[ "$exported_keys" == *" $key "* ]]; then
                    export "$key=$value"
                fi
            done <<< "$output"
            export ANTHROPIC_API_KEY="$CODEX_ANTHROPIC_API_KEY"
            unset ANTHROPIC_CUSTOM_MODEL_OPTION
            unset ANTHROPIC_CUSTOM_MODEL_OPTION_NAME
            unset ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION
            unset ANTHROPIC_AUTH_TOKEN
            printf 'codex\n' > "$profile"

            echo "✅ 已切换到 codex 端点 (settings.json 已更新)"
            echo "   BASE_URL:   $ANTHROPIC_BASE_URL"
            echo "   MODEL:      $ANTHROPIC_MODEL"
            echo "   OPUS 槽位:  $ANTHROPIC_DEFAULT_OPUS_MODEL"
            echo "   SONNET 槽位:$ANTHROPIC_DEFAULT_SONNET_MODEL"
            echo "   HAIKU 槽位: $ANTHROPIC_DEFAULT_HAIKU_MODEL"
            echo "   三档保持独立，由网关侧映射到各自的上游模型；不写 [1m]"

            if [[ $need_persist -eq 1 ]]; then
                echo ""
                local save_answer
                read -r -p "   写入 shell 配置永久保存？[y/N] " save_answer
                if [[ "$save_answer" =~ ^[Yy] ]]; then
                    _ccswitch_persist_codex
                else
                    echo "   已跳过：这份端点配置只在当前 shell 有效"
                fi
            fi

            echo ""
            echo "⚠️  已启动的 Claude Code 进程需要重启；当前 shell 后续运行 claude 已生效"
            ;;

        single|only)
            if [[ ! -f "$defaults" ]]; then
                echo "❌ 默认配置文件不存在: $defaults"
                echo "   请先运行 ccswitch init 保存默认端点配置"
                return 1
            fi
            if [[ -z "${2:-}" ]]; then
                echo "❌ 请指定模型 ID，例如: ccswitch single claude-opus-5"
                return 1
            fi

            local selected_model
            selected_model=$(MODEL="$2" python3 "$backend" resolve-model)
            local resolve_status=$?
            if [[ $resolve_status -ne 0 ]]; then
                return $resolve_status
            fi

            local output
            output=$(DEFAULT_SLOT_MODE=1 UNIFY_SELECTED_MODEL=1 SELECTED_MODEL="$selected_model" python3 "$backend" default) || {
                echo "❌ 修改 settings.json 失败"
                return 1
            }

            local key val
            while IFS='=' read -r key val; do
                case "$key" in
                    ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_MODEL|ANTHROPIC_SMALL_FAST_MODEL|ANTHROPIC_DEFAULT_SONNET_MODEL|ANTHROPIC_DEFAULT_OPUS_MODEL|ANTHROPIC_DEFAULT_HAIKU_MODEL|CLAUDE_CODE_SUBAGENT_MODEL|ANTHROPIC_CUSTOM_MODEL_OPTION|ANTHROPIC_CUSTOM_MODEL_OPTION_NAME|ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION)
                        export "$key=$val"
                        ;;
                esac
            done <<< "$output"
            unset ANTHROPIC_API_KEY
            [[ -z "$ANTHROPIC_AUTH_TOKEN" ]] && unset ANTHROPIC_AUTH_TOKEN
            printf 'default\n' > "$profile"

            echo "✅ 已切换回默认端点，并将所有模型槽位统一为 $ANTHROPIC_MODEL"
            echo "   BASE_URL:      $ANTHROPIC_BASE_URL"
            echo "   MODEL:         $ANTHROPIC_MODEL"
            echo ""
            echo "⚠️  已启动的 Claude Code 进程需要重启；当前 shell 后续运行 claude 已生效"
            ;;

        default|local)
            if [[ ! -f "$defaults" ]]; then
                echo "❌ 默认配置文件不存在: $defaults"
                echo "   请先运行 ccswitch init 保存默认端点配置"
                return 1
            fi

            local selected_model=""
            local slot_mode=0
            local restore_snapshot=0
            if [[ "${2:-}" == "--restore" ]]; then
                restore_snapshot=1
            else
                slot_mode=1
                if [[ -n "${2:-}" ]]; then
                    selected_model=$(MODEL="$2" python3 "$backend" resolve-model)
                    local resolve_status=$?
                    if [[ $resolve_status -ne 0 ]]; then
                        return $resolve_status
                    fi
                fi
            fi

            local output
            output=$(DEFAULT_SLOT_MODE="$slot_mode" SELECTED_MODEL="$selected_model" python3 "$backend" default) || {
                echo "❌ 修改 settings.json 失败"
                return 1
            }

            local key val
            while IFS='=' read -r key val; do
                case "$key" in
                    ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_MODEL|ANTHROPIC_SMALL_FAST_MODEL|ANTHROPIC_DEFAULT_SONNET_MODEL|ANTHROPIC_DEFAULT_OPUS_MODEL|ANTHROPIC_DEFAULT_HAIKU_MODEL|CLAUDE_CODE_SUBAGENT_MODEL|ANTHROPIC_CUSTOM_MODEL_OPTION|ANTHROPIC_CUSTOM_MODEL_OPTION_NAME|ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION)
                        export "$key=$val"
                        ;;
                esac
            done <<< "$output"
            unset ANTHROPIC_API_KEY
            [[ -z "$ANTHROPIC_AUTH_TOKEN" ]] && unset ANTHROPIC_AUTH_TOKEN
            printf 'default\n' > "$profile"

            echo "✅ 已切换回默认端点 (settings.json 已更新)"
            echo "   BASE_URL:      $ANTHROPIC_BASE_URL"
            echo "   MODEL:         $ANTHROPIC_MODEL"
            if [[ $restore_snapshot -eq 1 ]]; then
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
            echo "   ccswitch init             - 保存当前环境为默认端点配置（可选，codex 会自动快照）"
            echo "   ccswitch codex [model]    - 切换到 codex 端点（Anthropic 兼容网关）"
            echo "   ccswitch default          - 恢复默认网关并配置 /model 槽位"
            echo "   ccswitch default [model]  - 指定当前模型，固定槽位保持不变"
            echo "   ccswitch single <model>   - 默认网关，所有槽位统一为该模型"
            echo "   ccswitch default --restore - 恢复 init 保存的配置"
            echo "   ccswitch status           - 显示当前配置"
            echo "   ccswitch models           - 显示实时模型目录"
            echo "   ccswitch version          - 检查是否为最新版本"
            echo "   ccswitch update           - 更新 ccswitch"
            echo "   Claude Opus/Sonnet 使用 [1m] 选择项；其他模型会清理误带的 [1m]"
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
            echo "   ccswitch init             保存当前环境变量为默认端点配置（可选）"
            echo "                             ccswitch codex 在快照缺失时会自动从 settings.json 生成"
            echo ""
            echo "切换端点:"
            echo "   ccswitch codex [model]    切换到 codex 端点 (Opus/Sonnet/Haiku 三档各自独立)"
            echo "   ccswitch default          恢复默认网关并配置 Claude Code /model 槽位"
            echo "   ccswitch default [model]  指定当前模型，固定槽位保持不变"
            echo "   ccswitch single <model>   恢复默认网关，所有槽位统一为该模型"
            echo "   ccswitch default --restore 恢复 init 保存的各模型独立配置"
            echo "   ccswitch status           显示当前配置"
            echo "   ccswitch models           显示实时模型目录"
            echo "   ccswitch version          显示本地版本并检查更新"
            echo "   ccswitch update           更新 ccswitch（保留端点配置）"
            echo "   ccswitch help             显示此帮助"
            echo ""
            echo "Claude Opus/Sonnet 使用 [1m] 选择项；其他模型会清理误带的 [1m]，例如："
            echo "   ccswitch default claude-sonnet-5     → 当前模型 claude-sonnet-5[1m]"
            echo "   ccswitch default claude-opus-4.6     → claude-opus-4-6[1m]"
            echo "   ccswitch default qwen3.7-max        → qwen3.7-max"
            echo "   ccswitch default GLM-5.2            → glm-5.2"
            echo "   ccswitch single GLM-5.2            → 当前模型和全部槽位都是 glm-5.2"
            echo "   ccswitch default --restore         → 从快照恢复 (opus/haiku/sonnet 各自独立)"
            echo ""
            echo "MO 端点配置（在 shell 配置文件中添加）:"
            echo "   首次运行 ccswitch codex 会交互提示输入 Base URL 和 API Key，"
            echo "   先只在当前 shell 生效，再询问是否写入 shell 配置永久保存。"
            echo "   也可以预先设置:"
            echo "   export CODEX_ANTHROPIC_BASE_URL=\"https://your-gateway\""
            echo "   export CODEX_ANTHROPIC_API_KEY=\"your-api-key\""
            echo ""
            echo "codex 端点的模型槽位（网关侧按 Claude 系列映射到上游模型）:"
            echo "   Opus   → claude-opus-5"
            echo "   Sonnet → claude-sonnet-5"
            echo "   Haiku  → claude-haiku-4-5"
            echo "   不写 [1m]：上游是 GPT 模型，1M 标记会让 Claude Code 迟迟不压缩上下文"
            ;;

        *)
            echo "❌ 未知子命令: $target"
            echo "   可用: init, codex, default, single, status, models, version, update, help"
            return 1
            ;;
    esac
}
