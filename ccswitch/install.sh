#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch"
REPO_CDN="https://cdn.jsdelivr.net/gh/puchunwei/Shells@master/ccswitch"
REPO_ARCHIVE="https://codeload.github.com/puchunwei/Shells/tar.gz/refs/heads/master"

MO_URL=""
MO_KEY=""
FORCE_SHELL=""
TEMP_DIR=""
SOURCE_DIR=""
TTY_STATE=""

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

cleanup() {
    if [[ -n "$TTY_STATE" ]]; then
        stty "$TTY_STATE" </dev/tty 2>/dev/null || true
        TTY_STATE=""
    fi
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        rm -rf -- "$TEMP_DIR"
    fi
}

trap cleanup EXIT

fetch_url() {
    local url="$1" dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl --fail --show-error --silent --location \
            --connect-timeout 5 --max-time 15 "$url" -o "$dest"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --timeout=15 --tries=1 -O "$dest" "$url"
    else
        echo "❌ 需要 curl 或 wget" >&2
        return 1
    fi
}

prepare_source() {
    local archive
    TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ccswitch-install.XXXXXX")"
    archive="${TEMP_DIR}/Shells.tar.gz"

    echo "正在下载安装包 ..."
    if fetch_url "$REPO_ARCHIVE" "$archive" \
        && tar -xzf "$archive" -C "$TEMP_DIR" \
        && [[ -d "${TEMP_DIR}/Shells-master/ccswitch" ]]; then
        SOURCE_DIR="${TEMP_DIR}/Shells-master/ccswitch"
        echo "  ✓ 安装包下载完成"
        return
    fi

    rm -f "$archive"
    SOURCE_DIR=""
    echo "  ⚠ 整包下载失败，改用文件 CDN" >&2
}

download() {
    local relative="$1" dest="$2" temp_dest="${2}.tmp.$$" base source_name

    if [[ -n "$SOURCE_DIR" && -f "${SOURCE_DIR}/${relative}" ]]; then
        cp "${SOURCE_DIR}/${relative}" "$temp_dest"
        mv "$temp_dest" "$dest"
        return
    fi

    for base in "$REPO_CDN" "$REPO_RAW"; do
        if [[ "$base" == "$REPO_CDN" ]]; then source_name="jsDelivr"; else source_name="GitHub raw"; fi
        echo "  ↳ 正在通过 ${source_name} 下载 $(basename "$dest") ..."
        rm -f "$temp_dest"
        if fetch_url "${base}/${relative}" "$temp_dest"; then
            mv "$temp_dest" "$dest"
            return
        fi
    done

    rm -f "$temp_dest"
    echo "❌ 下载失败: $relative" >&2
    return 1
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
prepare_source

# --- 安装文件 ---

case "$USER_SHELL" in
    fish)
        DEST="${HOME}/.config/fish/functions"
        mkdir -p "$DEST"
        echo "正在安装 ccswitch 到 $DEST ..."
        download "fish/ccswitch.fish" "${DEST}/ccswitch.fish"
        echo "  ✓ ccswitch.fish"
        download "fish/_ccswitch_normalize_model.fish" "${DEST}/_ccswitch_normalize_model.fish"
        echo "  ✓ _ccswitch_normalize_model.fish"
        download "lib/ccswitch_backend.py" "${DEST}/ccswitch_backend.py"
        echo "  ✓ ccswitch_backend.py"
        ;;
    bash|zsh)
        DEST="${HOME}/.local/share/ccswitch"
        mkdir -p "$DEST"
        echo "正在安装 ccswitch 到 $DEST ..."
        download "bash/ccswitch.bash" "${DEST}/ccswitch.bash"
        echo "  ✓ ccswitch.bash"
        download "lib/ccswitch_backend.py" "${DEST}/ccswitch_backend.py"
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
    if exec 9<>/dev/tty 2>/dev/null; then
        echo ""
        echo "是否现在配置备用端点？（直接回车跳过）" >&9
        if [[ -z "$MO_URL" ]]; then
            printf "  端点地址 (MO_ANTHROPIC_BASE_URL): " >&9
            if ! IFS= read -r -u 9 MO_URL; then MO_URL=""; fi
        fi
        if [[ -n "$MO_URL" && -z "$MO_KEY" ]]; then
            printf "  API Key  (MO_ANTHROPIC_API_KEY):  " >&9
            TTY_STATE="$(stty -g <&9 2>/dev/null || true)"
            if [[ -n "$TTY_STATE" ]]; then stty -echo <&9; fi
            if ! IFS= read -r -u 9 MO_KEY; then MO_KEY=""; fi
            if [[ -n "$TTY_STATE" ]]; then stty "$TTY_STATE" <&9; fi
            TTY_STATE=""
            printf '\n' >&9
        fi
        exec 9>&-
    else
        echo "未检测到交互式终端，跳过备用端点配置；可使用 --url 和 --key 传入" >&2
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
