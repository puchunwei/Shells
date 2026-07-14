#!/bin/bash
# 代理 Wrapper 安装脚本
# 为 claude / codex 命令安装代理检查 wrapper，自动识别 bash/zsh/fish
#
# 用法:
#   ./install-proxy-wrapper.sh                  # 自动检测 shell 并安装
#   ./install-proxy-wrapper.sh --shell fish      # 指定 shell
#   ./install-proxy-wrapper.sh --dry-run         # 仅输出，不安装
#   ./install-proxy-wrapper.sh --uninstall       # 卸载 wrapper

set -euo pipefail

# ============ 配置 ============
PROXY_HOST="127.0.0.1"
PROXY_HTTP_PORT="28881"
PROXY_SOCKS_PORT="28880"
NO_PROXY_PATTERN=".alibaba-inc.com,.alicdn.com,.antfin.com,.dingtalk.com,localhost,127.0.0.1"
SETTINGS_JSON="$HOME/.claude/settings.json"
CODEX_BUNDLE_ID="com.openai.codex"

# 标记，用于 bash/zsh 中定位 wrapper 代码块
MARKER_BEGIN="# >>> proxy-wrapper:__CMD__ >>>"
MARKER_END="# <<< proxy-wrapper:__CMD__ <<<"

# ============ 参数解析 ============
DRY_RUN=false
UNINSTALL=false
DIAGNOSE=false
FORCE_SHELL=""

for arg in "$@"; do
    case "$arg" in
        --dry-run)    DRY_RUN=true ;;
        --uninstall)  UNINSTALL=true ;;
        --diagnose)   DIAGNOSE=true ;;
        --shell)      :;; # 下一个参数处理
        bash|zsh|fish)
            FORCE_SHELL="$arg" ;;
        -*)           echo "未知选项: $arg"; exit 1 ;;
    esac
done

# 修正 --shell 参数解析
for ((i=1; i<=$#; i++)); do
    if [ "${!i}" = "--shell" ]; then
        j=$((i+1))
        FORCE_SHELL="${!j}"
    fi
done

# ============ Shell 检测 ============
PARENT_SHELL_PATH=$(ps -p "$PPID" -o comm= 2>/dev/null | tr -d '[:space:]')
PARENT_SHELL=$(basename "$PARENT_SHELL_PATH")
LOGIN_SHELL=$(basename "${SHELL:-}")
SHELL_DETECTION_SOURCE=""

detect_shell() {
    if [ -n "$FORCE_SHELL" ]; then
        SHELL_DETECTION_SOURCE="--shell 参数"
        echo "$FORCE_SHELL"
        return
    fi

    # `$SHELL` 是登录 shell；用户手动运行 zsh/fish 时它不会改变。
    # 安装器由 bash 启动时，父进程才是当前实际使用的 shell。
    case "$PARENT_SHELL" in
        fish|zsh|bash)
            SHELL_DETECTION_SOURCE="父进程"
            echo "$PARENT_SHELL"
            return
            ;;
    esac

    case "$LOGIN_SHELL" in
        fish) echo "fish" ;;
        zsh)  echo "zsh" ;;
        bash) echo "bash" ;;
        *)
            echo "未知 shell: $user_shell，默认使用 bash" >&2
            echo "bash"
            ;;
    esac
}

if [ -n "$FORCE_SHELL" ]; then
    DETECTED_SHELL="$FORCE_SHELL"
    SHELL_DETECTION_SOURCE="--shell 参数"
elif [[ "$PARENT_SHELL" =~ ^(fish|zsh|bash)$ ]]; then
    DETECTED_SHELL="$PARENT_SHELL"
    SHELL_DETECTION_SOURCE="父进程"
else
    DETECTED_SHELL=$(detect_shell)
    SHELL_DETECTION_SOURCE="登录 shell"
fi

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_err()   { echo "[ERROR] $*" >&2; }

target_config_file() {
    case "$DETECTED_SHELL" in
        fish) echo "$HOME/.config/fish/functions" ;;
        zsh)  echo "$HOME/.zshrc" ;;
        bash) echo "$HOME/.bashrc" ;;
    esac
}

print_diagnostics() {
    local path_entry candidate version search_path seen_candidates=":"

    echo "Shell 诊断信息:"
    echo "  当前父进程: ${PARENT_SHELL_PATH:-<unknown>}"
    echo "  登录 shell: ${SHELL:-<unset>}"
    echo "  目标 shell: $DETECTED_SHELL (来源: $SHELL_DETECTION_SOURCE)"
    echo "  写入位置: $(target_config_file)"
    echo ""
    echo "Codex CLI 候选项:"

    search_path="${PATH}:"
    while [ -n "$search_path" ]; do
        path_entry=${search_path%%:*}
        search_path=${search_path#*:}
        [ -n "$path_entry" ] || path_entry="."
        candidate="$path_entry/codex"
        [ -x "$candidate" ] || continue
        case "$seen_candidates" in *":$candidate:"*) continue ;; esac
        seen_candidates="${seen_candidates}${candidate}:"
        if version=$("$candidate" --version 2>/dev/null); then
            echo "  [可用] $candidate ($version)"
        else
            echo "  [不可用] $candidate"
        fi
    done

    for candidate in "$HOME/.npm-global/bin/codex" "$HOME/Applications/ChatGPT.app/Contents/Resources/codex" /Applications/ChatGPT.app/Contents/Resources/codex /Applications/Codex.app/Contents/Resources/codex; do
        [ -x "$candidate" ] || continue
        case "$seen_candidates" in *":$candidate:"*) continue ;; esac
        seen_candidates="${seen_candidates}${candidate}:"
        if version=$("$candidate" --version 2>/dev/null); then
            echo "  [可用] $candidate ($version)"
        else
            echo "  [不可用] $candidate"
        fi
    done
}

# ============ Fish wrapper 生成 ============
gen_fish_claude() {
    cat <<'FISH_EOF'
# claude 命令前设置代理 + 检查网络
function claude --wraps claude
    echo "=== 网络检查 ==="

    set -lx HTTPS_PROXY "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx HTTP_PROXY "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx https_proxy "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx http_proxy "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx NO_PROXY "__NO_PROXY__"
    set -lx no_proxy "__NO_PROXY__"
    set -lx LANG "en_US.UTF-8"
    set -lx LC_ALL "en_US.UTF-8"
    set -lx TZ "America/Los_Angeles"

    # 环境配置信息
    echo "✅ 代理和环境已配置:"
    echo "  HTTP_PROXY:  $HTTP_PROXY"
    echo "  HTTPS_PROXY: $HTTPS_PROXY"
    echo "  NO_PROXY:    $NO_PROXY"
    echo "  时区: $TZ ("(date +%z)")"
    echo "  Locale: $LANG"
    echo ""

    # 读取 settings.json 中的 proxy 配置
    echo "Claude settings.json 代理配置:"
    if test -f __SETTINGS_JSON__
        cat __SETTINGS_JSON__ | grep -E '"(HTTPS?_PROXY|https?_proxy)"' | sed 's/.*: "\(.*\)".*/\1/' | sed 's/^/  /'
    else
        echo "  (settings.json 不存在)"
    end
    echo ""

    # 通过 claude.ai 域名获取出口 IP
    echo -n "请求 claude.ai 获取出口 IP... "
    set -l EXIT_IP (curl -s --max-time 10 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://claude.ai/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2)

    if test -n "$EXIT_IP"
        echo ""
        echo "出口 IP: $EXIT_IP"

        if test "$EXIT_IP" != "__EXPECTED_IP__"
            echo ""
            echo "⚠️  警告: 出口 IP 不是预期的 __EXPECTED_IP__!"
            echo "当前 IP ($EXIT_IP) 与预期不符，请检查代理配置!"
            echo ""
            read -P "是否仍要继续? [y/N] " force_continue
            if test "$force_continue" != "y" -a "$force_continue" != "Y"
                echo "已取消"
                return 1
            end
        end
    else
        echo "获取失败"
    end
    echo ""

    # 检查 claude.ai 连通性
    echo -n "检查 claude.ai 连通性... "
    if curl -s --max-time 8 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://claude.ai > /dev/null 2>&1
        echo "✓ 可访问"
    else
        echo "✗ 无法访问"
    end
    echo ""

    read -P "确认启动 claude? [Y/n] " confirm
    if test -z "$confirm" -o "$confirm" = "y" -o "$confirm" = "Y"
        command claude $argv
    else
        echo "已取消"
        return 1
    end
end
FISH_EOF
}

gen_fish_codex() {
    cat <<'FISH_EOF'
# codex 命令前设置代理
function __proxy_wrapper_resolve_codex
    # PATH 中可能同时存在损坏的旧版 npm 安装，逐个验证后再使用。
    for path_entry in $PATH
        set -l candidate "$path_entry/codex"
        if test -x "$candidate"; and "$candidate" --version >/dev/null 2>&1
            echo "$candidate"
            return 0
        end
    end

    for candidate in "$HOME/.npm-global/bin/codex" "$HOME/Applications/ChatGPT.app/Contents/Resources/codex" /Applications/ChatGPT.app/Contents/Resources/codex /Applications/Codex.app/Contents/Resources/codex
        if test -x "$candidate"; and "$candidate" --version >/dev/null 2>&1
            echo "$candidate"
            return 0
        end
    end

    return 1
end

function codex --wraps codex
    echo "=== Codex 代理启动 ==="

    set -lx HTTPS_PROXY "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx HTTP_PROXY "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx https_proxy "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx http_proxy "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx NO_PROXY "__NO_PROXY__"
    set -lx no_proxy "__NO_PROXY__"
    set -lx LANG "en_US.UTF-8"
    set -lx LC_ALL "en_US.UTF-8"
    set -lx TZ "America/Los_Angeles"

    # 环境配置信息
    echo "✅ 代理和环境已配置:"
    echo "  HTTP_PROXY:  $HTTP_PROXY"
    echo "  HTTPS_PROXY: $HTTPS_PROXY"
    echo "  NO_PROXY:    $NO_PROXY"
    echo "  时区: $TZ ("(date +%z)")"
    echo "  Locale: $LANG"
    echo ""

    set -l CODEX_COMMAND (__proxy_wrapper_resolve_codex)
    if test $status -ne 0 -o -z "$CODEX_COMMAND"
        echo "✗ 未找到可用的 Codex CLI。请重新安装 @openai/codex 或更新 ChatGPT 桌面应用。"
        return 127
    end
    echo "  Codex CLI: $CODEX_COMMAND"
    echo ""

    echo -n "获取出口 IP... "
    set -l EXIT_IP (curl -s --max-time 10 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://api.openai.com/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2)

    if test -n "$EXIT_IP"
        echo "$EXIT_IP"
    else
        echo "获取失败"
        read -P "是否仍要继续? [y/N] " force_continue
        if test "$force_continue" != "y" -a "$force_continue" != "Y"
            echo "已取消"
            return 1
        end
    end

    echo -n "检查 api.openai.com 连通性... "
    if curl -s --max-time 8 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://api.openai.com > /dev/null 2>&1
        echo "✓ 可访问"
    else
        echo "✗ 无法访问"
        read -P "是否仍要继续? [y/N] " force_continue
        if test "$force_continue" != "y" -a "$force_continue" != "Y"
            echo "已取消"
            return 1
        end
    end

    echo "代理: http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    echo ""

    read -P "确认启动 codex? [Y/n] " confirm
    if test -z "$confirm" -o "$confirm" = "y" -o "$confirm" = "Y"
        "$CODEX_COMMAND" $argv
    else
        echo "已取消"
        return 1
    end
end
FISH_EOF
}

gen_fish_opencodex() {
    cat <<'FISH_EOF'
# opencodex 命令前设置代理并打开 Codex 桌面应用
function opencodex
    echo "=== Codex 桌面应用代理启动 ==="

    set -lx HTTPS_PROXY "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx HTTP_PROXY "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx https_proxy "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx http_proxy "http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    set -lx ALL_PROXY "socks5://__PROXY_HOST__:__PROXY_SOCKS_PORT__"
    set -lx all_proxy "socks5://__PROXY_HOST__:__PROXY_SOCKS_PORT__"
    set -lx NO_PROXY "__NO_PROXY__"
    set -lx no_proxy "__NO_PROXY__"

    echo "✅ 代理已配置:"
    echo "  HTTP_PROXY:  $HTTP_PROXY"
    echo "  HTTPS_PROXY: $HTTPS_PROXY"
    echo "  ALL_PROXY:   $ALL_PROXY"
    echo ""

    echo -n "获取出口 IP... "
    set -l EXIT_IP (curl -s --max-time 10 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://api.openai.com/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2)

    if test -n "$EXIT_IP"
        echo "$EXIT_IP"
    else
        echo "获取失败"
        read -P "是否仍要继续? [y/N] " force_continue
        if test "$force_continue" != "y" -a "$force_continue" != "Y"
            echo "已取消"
            return 1
        end
    end
    echo ""

    read -P "确认打开 Codex 桌面应用? [Y/n] " confirm
    if test -z "$confirm" -o "$confirm" = "y" -o "$confirm" = "Y"
        open -b __CODEX_BUNDLE_ID__
    else
        echo "已取消"
        return 1
    end
end
FISH_EOF
}

# ============ Bash/Zsh wrapper 生成 ============
gen_bash_claude() {
    cat <<'BASH_EOF'
# claude 命令前设置代理 + 检查网络
# 同名 alias 会让 zsh/bash 无法定义此函数，或绕过代理检查。
unalias claude 2>/dev/null || true
eval "$(cat <<'PROXY_WRAPPER_CLAUDE_EOF'
claude() {
    echo "=== 网络检查 ==="

    export HTTPS_PROXY="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export HTTP_PROXY="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export https_proxy="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export http_proxy="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export NO_PROXY="__NO_PROXY__"
    export no_proxy="__NO_PROXY__"
    export LANG="en_US.UTF-8"
    export LC_ALL="en_US.UTF-8"
    export TZ="America/Los_Angeles"

    # 环境配置信息
    echo "✅ 代理和环境已配置:"
    echo "  HTTP_PROXY:  $HTTP_PROXY"
    echo "  HTTPS_PROXY: $HTTPS_PROXY"
    echo "  NO_PROXY:    $NO_PROXY"
    echo "  时区: $TZ ($(date +%z))"
    echo "  Locale: $LANG"
    echo ""

    # 读取 settings.json 中的 proxy 配置
    echo "Claude settings.json 代理配置:"
    if [ -f "__SETTINGS_JSON__" ]; then
        grep -E '"(HTTPS?_PROXY|https?_proxy)"' "__SETTINGS_JSON__" | sed 's/.*: "\(.*\)".*/\1/' | sed 's/^/  /'
    else
        echo "  (settings.json 不存在)"
    fi
    echo ""

    # 通过 claude.ai 域名获取出口 IP
    echo -n "请求 claude.ai 获取出口 IP... "
    local EXIT_IP
    EXIT_IP=$(curl -s --max-time 10 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://claude.ai/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2)

    if [ -n "$EXIT_IP" ]; then
        echo ""
        echo "出口 IP: $EXIT_IP"

        if [ "$EXIT_IP" != "__EXPECTED_IP__" ]; then
            echo ""
            echo "⚠️  警告: 出口 IP 不是预期的 __EXPECTED_IP__!"
            echo "当前 IP ($EXIT_IP) 与预期不符，请检查代理配置!"
            echo ""
            printf '是否仍要继续? [y/N] '
            read force_continue
            if [ "$force_continue" != "y" ] && [ "$force_continue" != "Y" ]; then
                echo "已取消"
                return 1
            fi
        fi
    else
        echo "获取失败"
    fi
    echo ""

    # 检查 claude.ai 连通性
    echo -n "检查 claude.ai 连通性... "
    if curl -s --max-time 8 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://claude.ai > /dev/null 2>&1; then
        echo "✓ 可访问"
    else
        echo "✗ 无法访问"
    fi
    echo ""

    printf '确认启动 claude? [Y/n] '
    read confirm
    if [ -z "$confirm" ] || [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        command claude "$@"
    else
        echo "已取消"
        return 1
    fi
}
PROXY_WRAPPER_CLAUDE_EOF
)"
BASH_EOF
}

gen_bash_codex() {
    cat <<'BASH_EOF'
# codex 命令前设置代理
unalias codex 2>/dev/null || true
eval "$(cat <<'PROXY_WRAPPER_CODEX_EOF'
_proxy_wrapper_resolve_codex() {
    # PATH 中可能同时存在损坏的旧版 npm 安装，逐个验证后再使用。
    local path_entry candidate search_path
    search_path="${PATH}:"

    while [ -n "$search_path" ]; do
        path_entry=${search_path%%:*}
        search_path=${search_path#*:}
        [ -n "$path_entry" ] || path_entry="."
        candidate="$path_entry/codex"
        if [ -x "$candidate" ] && "$candidate" --version >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    for candidate in "$HOME/.npm-global/bin/codex" "$HOME/Applications/ChatGPT.app/Contents/Resources/codex" /Applications/ChatGPT.app/Contents/Resources/codex /Applications/Codex.app/Contents/Resources/codex; do
        if [ -x "$candidate" ] && "$candidate" --version >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

codex() {
    echo "=== Codex 代理启动 ==="

    export HTTPS_PROXY="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export HTTP_PROXY="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export https_proxy="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export http_proxy="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export NO_PROXY="__NO_PROXY__"
    export no_proxy="__NO_PROXY__"
    export LANG="en_US.UTF-8"
    export LC_ALL="en_US.UTF-8"
    export TZ="America/Los_Angeles"

    # 环境配置信息
    echo "✅ 代理和环境已配置:"
    echo "  HTTP_PROXY:  $HTTP_PROXY"
    echo "  HTTPS_PROXY: $HTTPS_PROXY"
    echo "  NO_PROXY:    $NO_PROXY"
    echo "  时区: $TZ ($(date +%z))"
    echo "  Locale: $LANG"
    echo ""

    local CODEX_COMMAND
    if ! CODEX_COMMAND=$(_proxy_wrapper_resolve_codex); then
        echo "✗ 未找到可用的 Codex CLI。请重新安装 @openai/codex 或更新 ChatGPT 桌面应用。"
        return 127
    fi
    echo "  Codex CLI: $CODEX_COMMAND"
    echo ""

    echo -n "获取出口 IP... "
    local EXIT_IP
    EXIT_IP=$(curl -s --max-time 10 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://api.openai.com/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2)

    if [ -n "$EXIT_IP" ]; then
        echo "$EXIT_IP"
    else
        echo "获取失败"
        printf '是否仍要继续? [y/N] '
        read force_continue
        if [ "$force_continue" != "y" ] && [ "$force_continue" != "Y" ]; then
            echo "已取消"
            return 1
        fi
    fi

    echo -n "检查 api.openai.com 连通性... "
    if curl -s --max-time 8 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://api.openai.com > /dev/null 2>&1; then
        echo "✓ 可访问"
    else
        echo "✗ 无法访问"
        printf '是否仍要继续? [y/N] '
        read force_continue
        if [ "$force_continue" != "y" ] && [ "$force_continue" != "Y" ]; then
            echo "已取消"
            return 1
        fi
    fi

    echo "代理: http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    echo ""

    printf '确认启动 codex? [Y/n] '
    read confirm
    if [ -z "$confirm" ] || [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        "$CODEX_COMMAND" "$@"
    else
        echo "已取消"
        return 1
    fi
}
PROXY_WRAPPER_CODEX_EOF
)"
BASH_EOF
}

gen_bash_opencodex() {
    cat <<'BASH_EOF'
# opencodex 命令前设置代理并打开 Codex 桌面应用
unalias opencodex 2>/dev/null || true
eval "$(cat <<'PROXY_WRAPPER_OPENCODEX_EOF'
opencodex() {
    echo "=== Codex 桌面应用代理启动 ==="

    export HTTPS_PROXY="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export HTTP_PROXY="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export https_proxy="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export http_proxy="http://__PROXY_HOST__:__PROXY_HTTP_PORT__"
    export ALL_PROXY="socks5://__PROXY_HOST__:__PROXY_SOCKS_PORT__"
    export all_proxy="socks5://__PROXY_HOST__:__PROXY_SOCKS_PORT__"
    export NO_PROXY="__NO_PROXY__"
    export no_proxy="__NO_PROXY__"

    echo "✅ 代理已配置:"
    echo "  HTTP_PROXY:  $HTTP_PROXY"
    echo "  HTTPS_PROXY: $HTTPS_PROXY"
    echo "  ALL_PROXY:   $ALL_PROXY"
    echo ""

    echo -n "获取出口 IP... "
    local EXIT_IP
    EXIT_IP=$(curl -s --max-time 10 --proxy http://__PROXY_HOST__:__PROXY_HTTP_PORT__ https://api.openai.com/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2)

    if [ -n "$EXIT_IP" ]; then
        echo "$EXIT_IP"
    else
        echo "获取失败"
        printf '是否仍要继续? [y/N] '
        read force_continue
        if [ "$force_continue" != "y" ] && [ "$force_continue" != "Y" ]; then
            echo "已取消"
            return 1
        fi
    fi
    echo ""

    printf '确认打开 Codex 桌面应用? [Y/n] '
    read confirm
    if [ -z "$confirm" ] || [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        open -b __CODEX_BUNDLE_ID__
    else
        echo "已取消"
        return 1
    fi
}
PROXY_WRAPPER_OPENCODEX_EOF
)"
BASH_EOF
}

# ============ 模板变量替换 ============
apply_vars() {
    sed \
        -e "s|__PROXY_HOST__|$PROXY_HOST|g" \
        -e "s|__PROXY_HTTP_PORT__|$PROXY_HTTP_PORT|g" \
        -e "s|__PROXY_SOCKS_PORT__|$PROXY_SOCKS_PORT|g" \
        -e "s|__EXPECTED_IP__|$EXPECTED_IP|g" \
        -e "s|__NO_PROXY__|$NO_PROXY_PATTERN|g" \
        -e "s|__SETTINGS_JSON__|$SETTINGS_JSON|g" \
        -e "s|__CODEX_BUNDLE_ID__|$CODEX_BUNDLE_ID|g"
}

# ============ 安装逻辑 ============

install_fish() {
    local func_dir="$HOME/.config/fish/functions"

    local claude_content codex_content opencodex_content
    claude_content=$(gen_fish_claude | apply_vars)
    codex_content=$(gen_fish_codex | apply_vars)
    opencodex_content=$(gen_fish_opencodex | apply_vars)

    if [ "$DRY_RUN" = true ]; then
        echo "===== ${func_dir}/claude.fish ====="
        echo "$claude_content"
        echo ""
        echo "===== ${func_dir}/codex.fish ====="
        echo "$codex_content"
        echo ""
        echo "===== ${func_dir}/opencodex.fish ====="
        echo "$opencodex_content"
        return
    fi

    mkdir -p "$func_dir"

    for cmd in claude codex opencodex; do
        local target="$func_dir/${cmd}.fish"
        if [ -f "$target" ]; then
            log_info "$target 已存在，备份为 ${target}.bak"
            cp "$target" "${target}.bak"
        fi
    done

    echo "$claude_content"    > "$func_dir/claude.fish"
    echo "$codex_content"     > "$func_dir/codex.fish"
    echo "$opencodex_content" > "$func_dir/opencodex.fish"

    log_ok "已安装 $func_dir/claude.fish"
    log_ok "已安装 $func_dir/codex.fish"
    log_ok "已安装 $func_dir/opencodex.fish"
}

install_bash_zsh() {
    local shell_type="$1"
    local rc_file

    if [ "$shell_type" = "zsh" ]; then
        rc_file="$HOME/.zshrc"
    else
        rc_file="$HOME/.bashrc"
    fi

    local claude_content codex_content opencodex_content
    claude_content=$(gen_bash_claude | apply_vars)
    codex_content=$(gen_bash_codex | apply_vars)
    opencodex_content=$(gen_bash_opencodex | apply_vars)

    if [ "$DRY_RUN" = true ]; then
        echo "===== 将追加到 $rc_file ====="
        echo ""
        echo "${MARKER_BEGIN/__CMD__/claude}"
        echo "$claude_content"
        echo "${MARKER_END/__CMD__/claude}"
        echo ""
        echo "${MARKER_BEGIN/__CMD__/codex}"
        echo "$codex_content"
        echo "${MARKER_END/__CMD__/codex}"
        echo ""
        echo "${MARKER_BEGIN/__CMD__/opencodex}"
        echo "$opencodex_content"
        echo "${MARKER_END/__CMD__/opencodex}"
        return
    fi

    # 确保 rc 文件存在
    touch "$rc_file"

    for cmd in claude codex opencodex; do
        local begin="${MARKER_BEGIN/__CMD__/$cmd}"
        local end="${MARKER_END/__CMD__/$cmd}"

        # 若已存在旧的 wrapper，先移除
        if grep -qF "$begin" "$rc_file"; then
            log_info "移除 $rc_file 中已有的 $cmd wrapper"
            sed -i.bak "/$begin/,/$end/d" "$rc_file"
        fi
    done

    # 追加新 wrapper
    {
        echo ""
        echo "${MARKER_BEGIN/__CMD__/claude}"
        echo "$claude_content"
        echo "${MARKER_END/__CMD__/claude}"
        echo ""
        echo "${MARKER_BEGIN/__CMD__/codex}"
        echo "$codex_content"
        echo "${MARKER_END/__CMD__/codex}"
        echo ""
        echo "${MARKER_BEGIN/__CMD__/opencodex}"
        echo "$opencodex_content"
        echo "${MARKER_END/__CMD__/opencodex}"
    } >> "$rc_file"

    log_ok "已写入 $rc_file"
    log_info "执行 source $rc_file 或重新打开终端生效"
}

# ============ 卸载逻辑 ============
uninstall_wrappers() {
    log_info "卸载 wrapper..."

    # Fish
    for cmd in claude codex opencodex; do
        local fish_func="$HOME/.config/fish/functions/${cmd}.fish"
        if [ -f "$fish_func" ]; then
            rm "$fish_func"
            log_ok "已删除 $fish_func"
        fi
    done

    # Bash / Zsh
    for rc_file in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$rc_file" ] || continue
        for cmd in claude codex opencodex; do
            local begin="${MARKER_BEGIN/__CMD__/$cmd}"
            local end="${MARKER_END/__CMD__/$cmd}"
            if grep -qF "$begin" "$rc_file"; then
                sed -i.bak "/$begin/,/$end/d" "$rc_file"
                log_ok "已从 $rc_file 移除 $cmd wrapper"
            fi
        done
    done

    log_ok "卸载完成"
}

# ============ Chrome 插件安装 ============
CHROME_EXTENSIONS=(
    "https://chromewebstore.google.com/detail/webrtc-leak-prevent/eiadekoaikejlgdbkbdfeijglgfdalml"
    "https://chromewebstore.google.com/detail/proxy-switchyomega-3-zero/pfnededegaaopdmhkdmcofjmoldfiped"
)

install_chrome_extensions() {
    # 检测 Chrome 是否安装
    local chrome_app=""
    if [ -d "/Applications/Google Chrome.app" ]; then
        chrome_app="/Applications/Google Chrome.app"
    elif [ -d "$HOME/Applications/Google Chrome.app" ]; then
        chrome_app="$HOME/Applications/Google Chrome.app"
    fi

    if [ -z "$chrome_app" ]; then
        log_info "未检测到 Google Chrome，跳过插件安装"
        return
    fi

    echo ""
    echo "========================================="
    echo "  Chrome 代理插件推荐安装"
    echo "========================================="
    echo ""
    echo "  1. WebRTC Leak Prevent - 防止 WebRTC 泄漏真实 IP"
    echo "  2. Proxy SwitchyOmega 3 - 浏览器代理管理"
    echo ""
    read -p "是否打开 Chrome 安装以上插件? [Y/n] " install_ext < /dev/null 2>/dev/null || install_ext="y"

    # curl|bash 模式下无法 read，默认打开
    if [ -z "$install_ext" ] || [ "$install_ext" = "y" ] || [ "$install_ext" = "Y" ]; then
        for url in "${CHROME_EXTENSIONS[@]}"; do
            open -a "Google Chrome" "$url"
            log_ok "已打开: $(echo "$url" | sed 's|.*/detail/||; s|/.*||')"
        done
        echo ""
        log_info "请在 Chrome 中点击「添加至 Chrome」完成安装"
        echo ""
        echo "========================================="
        echo "  SwitchyOmega 配置指引"
        echo "========================================="
        echo ""
        echo "  插件安装完成后，请手动配置代理:"
        echo ""
        echo "  步骤一: 新建 proxy 情景模式"
        echo "  1. 点击 Chrome 右上角 SwitchyOmega 图标 → 选项"
        echo "  2. 左侧点击「新建情景模式」→ 名称填 proxy → 类型选「代理服务器」"
        echo "  3. 配置代理协议:"
        echo "     - 代理协议: SOCKS5"
        echo "     - 代理服务器: $PROXY_HOST"
        echo "     - 代理端口: $PROXY_SOCKS_PORT"
        echo "  4. 点击左侧「应用选项」保存"
        echo ""
        echo "  步骤二: 配置 auto switch 自动切换（推荐）"
        echo "  避免代理影响日常访问，仅特定网站走代理"
        echo "  1. 左侧点击「auto switch」情景模式"
        echo "  2. 添加需要走代理的规则，例如:"
        echo "     - 条件类型: 域名通配符"
        echo "     - 条件值: *.google.com     → 情景模式选 proxy"
        echo "     - 条件值: *.claude.ai      → 情景模式选 proxy"
        echo "     - 条件值: *.openai.com     → 情景模式选 proxy"
        echo "     - 条件值: *.github.com     → 情景模式选 proxy"
        echo "  3.「默认情景模式」保持「直接连接」"
        echo "  4. 点击左侧「应用选项」保存"
        echo "  5. 点击 Chrome 右上角 SwitchyOmega 图标 → 选择 auto switch"
        echo ""
        echo "========================================="
        echo "  WebRTC Leak Prevent 配置指引"
        echo "========================================="
        echo ""
        echo "  1. 点击 Chrome 右上角 WebRTC Leak Prevent 图标"
        echo "  2. 选择「Disable non-proxied UDP (force proxy)」"
        echo "     该模式强制所有 UDP 流量走代理，防止 WebRTC 泄漏真实 IP"
        echo ""
        echo "========================================="
    else
        echo "已跳过插件安装"
    fi
}

# ============ 主流程 ============
echo "========================================="
echo "  代理 Wrapper 安装工具"
echo "========================================="
echo ""
echo "  代理地址: http://$PROXY_HOST:$PROXY_HTTP_PORT (HTTP)"
echo "            socks5://$PROXY_HOST:$PROXY_SOCKS_PORT (SOCKS5)"
echo "  检测 Shell: $DETECTED_SHELL (来源: $SHELL_DETECTION_SOURCE)"
echo ""

if [ "$DIAGNOSE" = true ]; then
    print_diagnostics
    exit 0
fi

# ============ 检测出口 IP ============
log_info "通过代理检测出口 IP..."
EXPECTED_IP=$(curl -s --max-time 10 --proxy "http://${PROXY_HOST}:${PROXY_HTTP_PORT}" https://claude.ai/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2) || EXPECTED_IP=""
if [ -n "$EXPECTED_IP" ]; then
    log_ok "出口 IP: $EXPECTED_IP"
else
    log_err "无法检测出口 IP，请确认 Xray 代理服务已启动 (端口 $PROXY_HTTP_PORT)"
    exit 1
fi

if [ "$UNINSTALL" = true ]; then
    uninstall_wrappers
    exit 0
fi

case "$DETECTED_SHELL" in
    fish) install_fish ;;
    zsh)  install_bash_zsh zsh ;;
    bash) install_bash_zsh bash ;;
    *)    log_err "不支持的 shell: $DETECTED_SHELL"; exit 1 ;;
esac

if [ "$DRY_RUN" = false ]; then
    echo ""
    echo "========================================="
    echo "  安装完成！"
    echo "========================================="
    echo ""
    echo "  出口 IP: $EXPECTED_IP"
    echo ""
    echo "  已安装的 wrapper:"
    echo "    - claude:     启动前设置代理环境变量 + 检查连通性 + 出口 IP"
    echo "    - codex:      启动前设置代理环境变量 + 检查连通性 + 出口 IP"
    echo "    - opencodex:  设置代理 + 检查出口 IP + 打开 Codex 桌面应用"
    echo ""
    echo "  卸载: $0 --uninstall"
    echo "========================================="

    # ============ Chrome 插件安装 ============
    install_chrome_extensions
fi
