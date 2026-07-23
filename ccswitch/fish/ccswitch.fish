function ccswitch --description "Switch Claude Code between its default API endpoint and an alternate one (e.g. an internal proxy)"
    set -l backend (dirname (status --current-filename))/ccswitch_backend.py
    set -l target (test -n "$argv[1]"; and echo "$argv[1]"; or echo "status")
    set -l settings "$HOME/.claude/settings.json"
    set -l defaults "$HOME/.claude/ccswitch-defaults.json"
    set -l profile "$HOME/.claude/ccswitch-profile"

    if not test -f "$backend"
        echo "❌ 找不到后端脚本: $backend"
        echo "   ccswitch.fish 和 ccswitch_backend.py 必须放在同一个目录下"
        return 1
    end

    if not test -f "$settings"
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

            set -l unified_model ""
            if test -n "$argv[2]"
                set unified_model (_ccswitch_normalize_model "$argv[2]")
            end

            set -l output
            begin
                set -lx UNIFIED_MODEL "$unified_model"
                set output (python3 "$backend" default)
            end
            or begin
                echo "❌ 修改 settings.json 失败"
                return 1
            end

            for line in $output
                set -l kv (string split -m1 '=' "$line")
                set -gx $kv[1] $kv[2]
            end
            set -e ANTHROPIC_API_KEY
            printf 'default\n' > "$profile"

            echo "✅ 已切换回默认端点 (settings.json 已更新)"
            echo "   BASE_URL:      $ANTHROPIC_BASE_URL"
            echo "   MODEL:         $ANTHROPIC_MODEL"
            if test -z "$unified_model"
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
            echo "   ccswitch default [model]  - 切换回默认端点"
            echo "   ccswitch status           - 显示当前配置"
            echo "   模型名自动补 [1m]，直接输 claude-sonnet-5 即可"

        case help -h --help
            echo "ccswitch — Claude Code API 端点切换工具 (fish 版)"
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
            echo "MO 端点配置（在 ~/.config/fish/config.fish 中添加）:"
            echo "   set -gx MO_ANTHROPIC_BASE_URL \"https://...\""
            echo "   set -gx MO_ANTHROPIC_API_KEY \"...\""

        case '*'
            echo "❌ 未知子命令: $target"
            echo "   可用: init, mo, default, status, help"
            return 1
    end
end
