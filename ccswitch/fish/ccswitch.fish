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

        case mo
            if test -z "$MO_ANTHROPIC_BASE_URL" -o -z "$MO_ANTHROPIC_API_KEY"
                if test -f ~/.config/fish/config.fish
                    source ~/.config/fish/config.fish
                end
            end
            if test -z "$MO_ANTHROPIC_BASE_URL" -o -z "$MO_ANTHROPIC_API_KEY"
                echo "❌ 未设置 MO_ANTHROPIC_BASE_URL 或 MO_ANTHROPIC_API_KEY"
                echo ""
                echo "请在 ~/.config/fish/config.fish 中添加，例如:"
                echo "   set -gx MO_ANTHROPIC_BASE_URL \"https://your-endpoint.example.com/api/anthropic\""
                echo "   set -gx MO_ANTHROPIC_API_KEY \"your-api-key\""
                return 1
            end

            set -l model (_ccswitch_normalize_model (test -n "$argv[2]"; and echo "$argv[2]"; or echo "claude-opus-4-6"))

            begin
                set -lx MO_BASE_URL "$MO_ANTHROPIC_BASE_URL"
                set -lx MO_API_KEY "$MO_ANTHROPIC_API_KEY"
                set -lx MODEL "$model"
                python3 "$backend" mo
            end
            or begin
                echo "❌ 修改 settings.json 失败"
                return 1
            end

            set -gx ANTHROPIC_BASE_URL "$MO_ANTHROPIC_BASE_URL"
            set -gx ANTHROPIC_API_KEY "$MO_ANTHROPIC_API_KEY"
            for v in ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL
                set -gx $v "$model"
            end
            for v in ANTHROPIC_CUSTOM_MODEL_OPTION ANTHROPIC_CUSTOM_MODEL_OPTION_NAME ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION
                set -e $v
            end
            set -e ANTHROPIC_AUTH_TOKEN
            printf 'mo\n' > "$profile"

            echo "✅ 已切换到 MO 端点 (settings.json 已更新)"
            echo "   BASE_URL: $MO_ANTHROPIC_BASE_URL"
            echo "   MODEL:    $model"
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
            echo "   ccswitch init             - 保存当前环境为默认端点配置（首次必须执行）"
            echo "   ccswitch mo [model]       - 切换到 MO 端点"
            echo "   ccswitch default          - 恢复默认网关并配置 /model 槽位"
            echo "   ccswitch default [model]  - 指定当前模型并配置 /model 槽位"
            echo "   ccswitch default --restore - 恢复 init 保存的配置"
            echo "   ccswitch status           - 显示当前配置"
            echo "   ccswitch models           - 显示实时模型目录"
            echo "   ccswitch version          - 检查是否为最新版本"
            echo "   ccswitch update           - 更新 ccswitch"
            echo "   不再自动追加 [1m]，会清理历史 [1m] 后缀"

        case models
            python3 "$backend" models

        case version -v --version
            _ccswitch_version

        case help -h --help
            echo "ccswitch — Claude Code API 端点切换工具 (fish 版)"
            echo ""
            echo "首次使用:"
            echo "   ccswitch init             保存当前环境变量为默认端点配置"
            echo ""
            echo "切换端点:"
            echo "   ccswitch mo [model]       切换到 MO 端点 (所有模型统一为该值)"
            echo "   ccswitch default          恢复默认网关并配置 Claude Code /model 槽位"
            echo "   ccswitch default [model]  指定当前模型，固定槽位保持不变"
            echo "   ccswitch default --restore 恢复 init 保存的各模型独立配置"
            echo "   ccswitch status           显示当前配置"
            echo "   ccswitch models           显示实时模型目录"
            echo "   ccswitch version          显示本地版本并检查更新"
            echo "   ccswitch update           更新 ccswitch（保留端点配置）"
            echo "   ccswitch help             显示此帮助"
            echo ""
            echo "不会自动追加 [1m]；会自动清理历史 [1m] 后缀，例如："
            echo "   ccswitch default claude-sonnet-5   → 当前模型 claude-sonnet-5"
            echo "   ccswitch default claude-opus-4-6[1m] → claude-opus-4-6"
            echo "   ccswitch default qwen3.7-max        → qwen3.7-max"
            echo "   ccswitch default GLM-5.2            → glm-5.2"
            echo "   ccswitch default --restore         → 从快照恢复 (opus/haiku/sonnet 各自独立)"
            echo ""
            echo "MO 端点配置（在 ~/.config/fish/config.fish 中添加）:"
            echo "   set -gx MO_ANTHROPIC_BASE_URL \"https://...\""
            echo "   set -gx MO_ANTHROPIC_API_KEY \"...\""

        case '*'
            echo "❌ 未知子命令: $target"
            echo "   可用: init, mo, default, status, models, version, update, help"
            return 1
    end
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
