#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch"

MO_URL=""
MO_KEY=""
FORCE_SHELL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)
            [[ $# -ge 2 ]] || { echo "❌ --url 需要一个参数" >&2; exit 1; }
            MO_URL="$2"; shift 2 ;;
        --key)
            [[ $# -ge 2 ]] || { echo "❌ --key 需要一个参数" >&2; exit 1; }
            MO_KEY="$2"; shift 2 ;;
        --shell)
            [[ $# -ge 2 ]] || { echo "❌ --shell 需要一个参数" >&2; exit 1; }
            case "$2" in
                fish|bash|zsh) FORCE_SHELL="$2" ;;
                *) echo "❌ --shell 仅支持 fish、bash 或 zsh" >&2; exit 1 ;;
            esac
            shift 2
            ;;
        -h|--help)
            echo "usage: install.sh [--shell <fish|bash|zsh>] [--url <endpoint-url>] [--key <api-key>]"
            echo ""
            echo "安装 ccswitch 到当前 shell（自动检测 fish / bash / zsh）"
            echo ""
            echo "选项："
            echo "  --shell  指定要安装到的当前 shell"
            echo "  --url  备用端点地址"
            echo "  --key  备用端点密钥"
            echo ""
            echo "不传参数也可以安装，安装过程中会交互式提示输入"
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

# --- 辅助函数 ---

download() {
    local url="$1" dest="$2" temp_dest="${2}.tmp.$$"
    echo "  ↳ 正在下载 $(basename "$dest") ..."
    if command -v curl >/dev/null 2>&1; then
        if ! curl --fail --show-error --silent --location \
            --connect-timeout 5 --max-time 20 --retry 1 --retry-delay 1 \
            "$url" -o "$temp_dest"; then
            rm -f "$temp_dest"
            echo "❌ 下载失败: $url" >&2
            return 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -q --timeout=20 --tries=2 -O "$temp_dest" "$url"; then
            rm -f "$temp_dest"
            echo "❌ 下载失败: $url" >&2
            return 1
        fi
    else
        echo "❌ 需要 curl 或 wget" >&2
        return 1
    fi
    mv "$temp_dest" "$dest"
}

sed_inplace() {
    if sed --version 2>/dev/null | grep -q 'GNU'; then
        sed -i "$@"
    else
        sed -i '' "$@"
    fi
}

# --- 检测 shell ---

detect_shell() {
    local pid process_name shell_name depth

    if [[ -n "$FORCE_SHELL" ]]; then
        USER_SHELL="$FORCE_SHELL"
        SHELL_DETECTION_SOURCE="--shell 参数"
        return
    fi

    # `$SHELL` 是账户的默认登录 shell，不会随当前交互 shell 改变。
    # 安装器本身由 bash 执行，因此要从它的父进程开始向上查找。
    pid="${PPID:-}"
    for ((depth = 0; depth < 8 && pid > 1; depth++)); do
        process_name="$(ps -p "$pid" -o comm= 2>/dev/null | tr -d '[:space:]')"
        shell_name="${process_name##*/}"
        shell_name="${shell_name#-}"
        case "$shell_name" in
            fish|bash|zsh)
                USER_SHELL="$shell_name"
                SHELL_DETECTION_SOURCE="当前进程树"
                return
                ;;
        esac
        pid="$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d '[:space:]')"
        [[ "$pid" =~ ^[0-9]+$ ]] || break
    done

    echo "❌ 无法从当前进程树识别 fish、bash 或 zsh；请使用 --shell 明确指定" >&2
    return 1
}

USER_SHELL=""
SHELL_DETECTION_SOURCE=""
detect_shell
echo "检测到当前 shell: ${USER_SHELL}（来源: ${SHELL_DETECTION_SOURCE}）"

# --- 安装文件 ---

case "$USER_SHELL" in
    fish)
        DEST="${HOME}/.config/fish/functions"
        mkdir -p "$DEST"
        echo "正在安装 ccswitch 到 $DEST ..."
        download "${REPO_RAW}/fish/ccswitch.fish" "${DEST}/ccswitch.fish"
        echo "  ✓ ccswitch.fish"
        download "${REPO_RAW}/fish/_ccswitch_normalize_model.fish" "${DEST}/_ccswitch_normalize_model.fish"
        echo "  ✓ _ccswitch_normalize_model.fish"
        download "${REPO_RAW}/lib/ccswitch_backend.py" "${DEST}/ccswitch_backend.py"
        echo "  ✓ ccswitch_backend.py"
        ;;
    bash|zsh)
        DEST="${HOME}/.local/share/ccswitch"
        mkdir -p "$DEST"
        echo "正在安装 ccswitch 到 $DEST ..."
        download "${REPO_RAW}/bash/ccswitch.bash" "${DEST}/ccswitch.bash"
        echo "  ✓ ccswitch.bash"
        download "${REPO_RAW}/lib/ccswitch_backend.py" "${DEST}/ccswitch_backend.py"
        echo "  ✓ ccswitch_backend.py"

        # 确定 rc 文件
        if [[ "$USER_SHELL" == "zsh" ]]; then
            RC_FILE="${HOME}/.zshrc"
        else
            RC_FILE="${HOME}/.bashrc"
        fi

        SOURCE_LINE="source \"${DEST}/ccswitch.bash\""
        BACKEND_LINE="export CCSWITCH_BACKEND=\"${DEST}/ccswitch_backend.py\""

        if ! grep -qF "ccswitch.bash" "$RC_FILE" 2>/dev/null; then
            printf '\n# ccswitch — Claude Code endpoint switcher\n' >> "$RC_FILE"
            printf '%s\n' "$BACKEND_LINE" >> "$RC_FILE"
            printf '%s\n' "$SOURCE_LINE" >> "$RC_FILE"
            echo "  ✓ 已在 $RC_FILE 中添加 source 行"
        else
            echo "  ✓ $RC_FILE 中已存在 source 行，跳过"
        fi
        ;;
esac

# --- 配置备用端点（参数传入 > 交互输入 > 跳过） ---

if [[ -z "$MO_URL" || -z "$MO_KEY" ]]; then
    if [[ -t 0 ]]; then
        echo ""
        echo "是否现在配置备用端点？（直接回车跳过）"
        read -rp "  端点地址 (MO_ANTHROPIC_BASE_URL): " MO_URL
        if [[ -n "$MO_URL" ]]; then
            read -rp "  API Key  (MO_ANTHROPIC_API_KEY):  " MO_KEY
        fi
    fi
fi

if [[ -n "$MO_URL" && -n "$MO_KEY" ]]; then
    case "$USER_SHELL" in
        fish)
            CONFIG_FILE="${HOME}/.config/fish/config.fish"
            mkdir -p "$(dirname "$CONFIG_FILE")"
            touch "$CONFIG_FILE"
            if grep -qE 'MO_ANTHROPIC_BASE_URL|MO_ANTHROPIC_API_KEY' "$CONFIG_FILE" 2>/dev/null; then
                sed_inplace '/^set -gx MO_ANTHROPIC_BASE_URL /d' "$CONFIG_FILE"
                sed_inplace '/^set -gx MO_ANTHROPIC_API_KEY /d' "$CONFIG_FILE"
                sed_inplace '/^# ccswitch MO endpoint$/d' "$CONFIG_FILE"
            fi
            # fish double-quoted strings: escape \ and "
            fish_url="${MO_URL//\\/\\\\}"; fish_url="${fish_url//\"/\\\"}"
            fish_key="${MO_KEY//\\/\\\\}"; fish_key="${fish_key//\"/\\\"}"
            printf '\n# ccswitch MO endpoint\n' >> "$CONFIG_FILE"
            printf 'set -gx MO_ANTHROPIC_BASE_URL "%s"\n' "$fish_url" >> "$CONFIG_FILE"
            printf 'set -gx MO_ANTHROPIC_API_KEY "%s"\n' "$fish_key" >> "$CONFIG_FILE"
            ;;
        bash|zsh)
            if [[ "$USER_SHELL" == "zsh" ]]; then
                CONFIG_FILE="${HOME}/.zshrc"
            else
                CONFIG_FILE="${HOME}/.bashrc"
            fi
            if grep -qE 'MO_ANTHROPIC_BASE_URL|MO_ANTHROPIC_API_KEY' "$CONFIG_FILE" 2>/dev/null; then
                sed_inplace '/^export MO_ANTHROPIC_BASE_URL=/d' "$CONFIG_FILE"
                sed_inplace '/^export MO_ANTHROPIC_API_KEY=/d' "$CONFIG_FILE"
                sed_inplace '/^# ccswitch MO endpoint$/d' "$CONFIG_FILE"
            fi
            # bash/zsh: use single quotes, escape embedded single quotes
            sq_url="${MO_URL//\'/\'\\\'\'}"
            sq_key="${MO_KEY//\'/\'\\\'\'}"
            printf '\n# ccswitch MO endpoint\n' >> "$CONFIG_FILE"
            printf "export MO_ANTHROPIC_BASE_URL='%s'\n" "$sq_url" >> "$CONFIG_FILE"
            printf "export MO_ANTHROPIC_API_KEY='%s'\n" "$sq_key" >> "$CONFIG_FILE"
            ;;
    esac
    echo ""
    echo "  ✓ 已将 MO 端点配置写入 $CONFIG_FILE"
fi

# --- 完成 ---

echo ""
echo "✅ 安装完成！"
echo ""

if [[ -z "$MO_URL" || -z "$MO_KEY" ]]; then
    case "$USER_SHELL" in
        fish)
            echo "下一步：在 ~/.config/fish/config.fish 中加上备用端点配置："
            echo '  set -gx MO_ANTHROPIC_BASE_URL "https://your-endpoint/api/anthropic"'
            echo '  set -gx MO_ANTHROPIC_API_KEY "your-api-key"'
            ;;
        *)
            echo "下一步：在你的 shell 配置文件中加上备用端点配置："
            echo '  export MO_ANTHROPIC_BASE_URL="https://your-endpoint/api/anthropic"'
            echo '  export MO_ANTHROPIC_API_KEY="your-api-key"'
            ;;
    esac
    echo ""
fi

echo "新开一个终端，运行："
echo ""
echo "  ccswitch init      # 保存当前默认配置（只需运行一次）"
echo "  ccswitch status    # 查看当前状态"
echo "  ccswitch mo        # 切到备用端点"
echo "  ccswitch default   # 切回默认端点"
