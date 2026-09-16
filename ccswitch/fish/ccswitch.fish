function ccswitch --description "Switch Claude Code between its default API endpoint and an alternate one (e.g. an internal proxy)"
    set -l backend (dirname (status --current-filename))/ccswitch_backend.py
    set -l target (test -n "$argv[1]"; and echo "$argv[1]"; or echo "status")
    set -l settings "$HOME/.claude/settings.json"
    set -l defaults "$HOME/.claude/ccswitch-defaults.json"
    set -l profile "$HOME/.claude/ccswitch-profile"

    if test "$target" = update
        _ccswitch_update
        return $status
    end

    if not test -f "$backend"
        echo "❌ 找不到后端脚本: $backend"
        echo "   ccswitch.fish 和 ccswitch_backend.py 必须放在同一个目录下"
        return 1
    end

    if not contains -- "$target" models version -v --version help -h --help; and not test -f "$settings"
        echo "❌ $settings 不存在，请先启动一次 Claude Code 让它生成配置文件"
        return 1
    end

    switch "$target"
        case init
            python3 "$backend" init
            or begin
                echo "❌ 保存默认配置失败"
                return 1
            end
            echo "✅ 已保存默认端点配置到 $defaults"
            echo "   后续 ccswitch default 将从此文件恢复"

        case codex
            if test -z "$CODEX_ANTHROPIC_BASE_URL" -o -z "$CODEX_ANTHROPIC_API_KEY"
                if test -f ~/.config/fish/config.fish
                    source ~/.config/fish/config.fish
                end
            end

            set -l need_persist 0
            if test -z "$CODEX_ANTHROPIC_BASE_URL" -o -z "$CODEX_ANTHROPIC_API_KEY"
                if not isatty stdin
                    echo "❌ 未设置 CODEX_ANTHROPIC_BASE_URL 或 CODEX_ANTHROPIC_API_KEY"
                    echo "   当前不是交互式终端，无法提示输入。请先手动设置:"
                    echo "   set -gx CODEX_ANTHROPIC_BASE_URL \"https://your-gateway\""
                    echo "   set -gx CODEX_ANTHROPIC_API_KEY \"your-api-key\""
                    return 1
                end
                echo "🔧 codex 端点尚未配置，现在录入（默认只在当前 shell 生效）"
                if test -z "$CODEX_ANTHROPIC_BASE_URL"
                    read -P "   Base URL: " -l entered_url
                    set entered_url (string trim -- "$entered_url")
                    if test -z "$entered_url"
                        echo "❌ Base URL 不能为空"
                        return 1
                    end
                    set -gx CODEX_ANTHROPIC_BASE_URL "$entered_url"
                end
                if test -z "$CODEX_ANTHROPIC_API_KEY"
                    read -s -P "   API Key（不回显）: " -l entered_key
                    echo ""
                    set entered_key (string trim -- "$entered_key")
                    if test -z "$entered_key"
                        echo "❌ API Key 不能为空"
                        return 1
                    end
                    set -gx CODEX_ANTHROPIC_API_KEY "$entered_key"
                end
                set need_persist 1
            end

            # 不做 [1m] 规范化：codex 上游是 GPT 模型，1M 标记会让 Claude Code 迟迟不压缩上下文
            set -l model ""
            if test -n "$argv[2]"
                set model (string replace -ra '\[1[mM]\]$' '' -- "$argv[2]")
            end

            set -l output
            begin
                set -lx CODEX_BASE_URL "$CODEX_ANTHROPIC_BASE_URL"
                set -lx CODEX_API_KEY "$CODEX_ANTHROPIC_API_KEY"
                set -lx MODEL "$model"
                set output (python3 "$backend" codex)
            end
            or begin
                echo "❌ 修改 settings.json 失败"
                return 1
            end

            set -l exported_keys ANTHROPIC_BASE_URL ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL
            for line in $output
                set -l kv (string split -m1 '=' "$line")
                if contains -- "$kv[1]" $exported_keys
                    set -gx $kv[1] $kv[2]
                end
            end
            set -gx ANTHROPIC_API_KEY "$CODEX_ANTHROPIC_API_KEY"
            for v in ANTHROPIC_CUSTOM_MODEL_OPTION ANTHROPIC_CUSTOM_MODEL_OPTION_NAME ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION
                set -e $v
            end
            set -e ANTHROPIC_AUTH_TOKEN
            printf 'codex\n' > "$profile"

            echo "✅ 已切换到 codex 端点 (settings.json 已更新)"
            echo "   BASE_URL:   $ANTHROPIC_BASE_URL"
            echo "   MODEL:      $ANTHROPIC_MODEL"
            echo "   OPUS 槽位:  $ANTHROPIC_DEFAULT_OPUS_MODEL"
            echo "   SONNET 槽位:$ANTHROPIC_DEFAULT_SONNET_MODEL"
            echo "   HAIKU 槽位: $ANTHROPIC_DEFAULT_HAIKU_MODEL"
            echo "   三档保持独立，由网关侧映射到各自的上游模型；不写 [1m]"

            if test $need_persist -eq 1
                echo ""
                read -P "   写入 ~/.config/fish/config.fish 永久保存？[y/N] " -l save_answer
                if string match -qi 'y*' -- "$save_answer"
                    _ccswitch_persist_codex
                else
                    echo "   已跳过：这份端点配置只在当前 shell 有效"
                end
            end

            echo ""
            echo "⚠️  已启动的 Claude Code 进程需要重启；当前 shell 后续运行 claude 已生效"

        case single only
            if not test -f "$defaults"
                echo "❌ 默认配置文件不存在: $defaults"
                echo "   请先运行 ccswitch init 保存默认端点配置"
                return 1
            end
            if not test -n "$argv[2]"
                echo "❌ 请指定模型 ID，例如: ccswitch single claude-opus-5"
                return 1
            end

            set -l selected_model
            begin
                set -lx MODEL "$argv[2]"
                set selected_model (python3 "$backend" resolve-model)
            end
            set -l resolve_status $status
            if test $resolve_status -ne 0
                return $resolve_status
            end

            set -l output
            begin
                set -lx DEFAULT_SLOT_MODE 1
                set -lx UNIFY_SELECTED_MODEL 1
                set -lx SELECTED_MODEL "$selected_model"
                set output (python3 "$backend" default)
            end
            or begin
                echo "❌ 修改 settings.json 失败"
                return 1
            end

            set -l exported_keys ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL ANTHROPIC_CUSTOM_MODEL_OPTION ANTHROPIC_CUSTOM_MODEL_OPTION_NAME ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION
            for line in $output
                set -l kv (string split -m1 '=' "$line")
                if contains -- "$kv[1]" $exported_keys
                    set -gx $kv[1] $kv[2]
                end
            end
            set -e ANTHROPIC_API_KEY
            printf 'default\n' > "$profile"

            echo "✅ 已切换回默认端点，并将所有模型槽位统一为 $ANTHROPIC_MODEL"
            echo "   BASE_URL:      $ANTHROPIC_BASE_URL"
            echo "   MODEL:         $ANTHROPIC_MODEL"
            echo ""
            echo "⚠️  已启动的 Claude Code 进程需要重启；当前 shell 后续运行 claude 已生效"

        case default local
            if not test -f "$defaults"
                echo "❌ 默认配置文件不存在: $defaults"
                echo "   请先运行 ccswitch init 保存默认端点配置"
                return 1
            end

            set -l selected_model ""
            set -l slot_mode 0
            set -l restore_snapshot 0
            if test "$argv[2]" = --restore
                set restore_snapshot 1
            else
                set slot_mode 1
                if test -n "$argv[2]"
                    begin
                        set -lx MODEL "$argv[2]"
                        set selected_model (python3 "$backend" resolve-model)
                    end
                    set -l resolve_status $status
                    if test $resolve_status -ne 0
                        return $resolve_status
                    end
                end
            end

            set -l output
            begin
                set -lx DEFAULT_SLOT_MODE "$slot_mode"
                set -lx SELECTED_MODEL "$selected_model"
                set output (python3 "$backend" default)
            end
            or begin
                echo "❌ 修改 settings.json 失败"
                return 1
            end

            set -l exported_keys ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL ANTHROPIC_CUSTOM_MODEL_OPTION ANTHROPIC_CUSTOM_MODEL_OPTION_NAME ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION
            for line in $output
                set -l kv (string split -m1 '=' "$line")
                if contains -- "$kv[1]" $exported_keys
                    set -gx $kv[1] $kv[2]
                end
            end
            set -e ANTHROPIC_API_KEY
            printf 'default\n' > "$profile"

            echo "✅ 已切换回默认端点 (settings.json 已更新)"
            echo "   BASE_URL:      $ANTHROPIC_BASE_URL"
            echo "   MODEL:         $ANTHROPIC_MODEL"
            if test $restore_snapshot -eq 1
                echo "   SMALL_FAST:    $ANTHROPIC_SMALL_FAST_MODEL"
                echo "   SONNET:        $ANTHROPIC_DEFAULT_SONNET_MODEL"
                echo "   HAIKU:         $ANTHROPIC_DEFAULT_HAIKU_MODEL"
            end
            echo ""
            echo "⚠️  已启动的 Claude Code 进程需要重启；当前 shell 后续运行 claude 已生效"

        case status
            echo "📡 Claude Code settings.json 当前 env 配置:"
            set -l active_profile "default"
            if test -r "$profile"
                read active_profile < "$profile"
            end
            echo "   PROFILE:    $active_profile"

            python3 "$backend" status
            or begin
                echo "❌ 读取 settings.json 失败"
                return 1
            end

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

        case models
            python3 "$backend" models

        case version -v --version
            _ccswitch_version

        case help -h --help
            echo "ccswitch — Claude Code API 端点切换工具 (fish 版)"
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
            echo "codex 端点配置:"
            echo "   首次运行 ccswitch codex 会交互提示输入 Base URL 和 API Key，"
            echo "   先只在当前 shell 生效，再询问是否写入 config.fish 永久保存。"
            echo "   也可以预先设置:"
            echo "   set -gx CODEX_ANTHROPIC_BASE_URL \"https://your-gateway\""
            echo "   set -gx CODEX_ANTHROPIC_API_KEY \"your-api-key\""
            echo ""
            echo "codex 端点的模型槽位（网关侧按 Claude 系列映射到上游模型）:"
            echo "   Opus   → claude-opus-5"
            echo "   Sonnet → claude-sonnet-5"
            echo "   Haiku  → claude-haiku-4-5"
            echo "   不写 [1m]：上游是 GPT 模型，1M 标记会让 Claude Code 迟迟不压缩上下文"

        case '*'
            echo "❌ 未知子命令: $target"
            echo "   可用: init, codex, default, single, status, models, version, update, help"
            return 1
    end
end

function _ccswitch_persist_codex --description "Persist the codex endpoint variables into config.fish"
    set -l cfg "$HOME/.config/fish/config.fish"
    mkdir -p (dirname "$cfg")
    or begin
        echo "   ❌ 无法创建 "(dirname "$cfg")
        return 1
    end
    if test -f "$cfg"; and grep -q 'CODEX_ANTHROPIC_BASE_URL' "$cfg"
        echo "   ⚠ config.fish 里已有 CODEX_ANTHROPIC_BASE_URL，未重复写入"
        echo "     如需更新请手动编辑 $cfg"
        return 0
    end
    printf '\n# ccswitch codex endpoint\nset -gx CODEX_ANTHROPIC_BASE_URL %s\nset -gx CODEX_ANTHROPIC_API_KEY %s\n' \
        (string escape -- "$CODEX_ANTHROPIC_BASE_URL") \
        (string escape -- "$CODEX_ANTHROPIC_API_KEY") >> "$cfg"
    or begin
        echo "   ❌ 写入 $cfg 失败"
        return 1
    end
    echo "   ✅ 已写入 $cfg"
end

function _ccswitch_version --description "Show the installed ccswitch version and check GitHub"
    set -l backend (dirname (status --current-filename))/ccswitch_backend.py
    set -l current (python3 "$backend" version)
    or return 1
    echo "ccswitch 版本："
    echo "   当前版本: $current"
    set -l latest (curl --fail --silent --location --connect-timeout 3 --max-time 5 \
        "https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/VERSION" 2>/dev/null)
    if test $status -eq 0; and string match -qr '^[0-9]+\.[0-9]+\.[0-9]+$' -- "$latest"
        echo "   最新版本: $latest"
        if test "$current" = "$latest"
            echo "   状态:     ✓ 已是最新版本"
        else
            echo "   状态:     ↑ 有新版本，请运行 ccswitch update"
        end
    else
        echo "   最新版本: 无法获取（请检查网络）"
    end
end

function _ccswitch_update --description "Update ccswitch without changing endpoint configuration"
    set -l temp_root /tmp
    if set -q TMPDIR; and test -n "$TMPDIR"
        set temp_root "$TMPDIR"
    end
    set -l installer (mktemp "$temp_root/ccswitch-update.XXXXXX")
    or return 1
    if not curl --fail --show-error --silent --location \
        --connect-timeout 5 --max-time 30 \
        "https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh" \
        -o "$installer"
        rm -f -- "$installer"
        echo "❌ ccswitch 更新脚本下载失败"
        return 1
    end
    if not bash "$installer" --shell fish --update
        rm -f -- "$installer"
        return 1
    end
    rm -f -- "$installer"
    source "$HOME/.config/fish/functions/_ccswitch_normalize_model.fish"
    source "$HOME/.config/fish/functions/ccswitch.fish"
end
