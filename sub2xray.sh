#!/bin/bash
# 订阅链接转 Xray 配置 + 一键部署脚本（纯 shell，无 python 依赖）
# 用法:
#   ./sub2xray.sh <订阅URL>            # 安装环境 + 生成配置 + 启动服务
#   ./sub2xray.sh <vless://...>        # 直接使用单条 VLESS 节点
#   ./sub2xray.sh <订阅URL> --dry-run   # 仅输出配置，不安装不应用
#   ./sub2xray.sh --diagnose           # 输出 Xray/Homebrew 服务诊断信息
#   ./sub2xray.sh --diagnose --verbose # 输出完整诊断信息

set -euo pipefail

# ============ 参数解析 ============
SUB_URL=""
DRY_RUN=false
DIAGNOSE=false
DIAGNOSE_RUN_CHECK=false
DIAGNOSE_VERBOSE=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --diagnose) DIAGNOSE=true ;;
        --run-check) DIAGNOSE_RUN_CHECK=true ;;
        --verbose) DIAGNOSE_VERBOSE=true ;;
        -*) echo "未知选项: $arg"; exit 1 ;;
        *) SUB_URL="$arg" ;;
    esac
done

# ============ 工具函数 ============
urldecode() {
    local encoded="$1"
    encoded="${encoded//+/ }"
    printf '%b' "${encoded//%/\\x}"
}

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_err()   { echo "[ERROR] $*" >&2; }

usage() {
    echo "用法: $0 <订阅URL|vless://...> [--dry-run]"
    echo "      $0 --diagnose [--run-check] [--verbose]"
    echo ""
    echo "示例:"
    echo "  $0 https://u.youlin.online/sub/xxxxx            # 一键部署"
    echo "  $0 'vless://uuid@host:443?security=reality&...' # 直接使用单条节点"
    echo "  $0 https://u.youlin.online/sub/xxxxx --dry-run   # 仅查看配置"
    echo "  $0 --diagnose                                   # 输出诊断信息"
}

run_diag_shell() {
    local title="$1"
    local cmd="$2"
    echo ""
    echo "===== $title ====="
    bash -lc "$cmd" 2>&1 || echo "[exit $?]"
}

run_diag_shell_timeout() {
    local title="$1"
    local seconds="$2"
    local cmd="$3"
    local output_file pid elapsed rc

    echo ""
    echo "===== $title ====="
    output_file="$(mktemp -t xray-diag.XXXXXX)"
    bash -lc "$cmd" >"$output_file" 2>&1 &
    pid=$!
    elapsed=0
    while kill -0 "$pid" 2>/dev/null && [ "$elapsed" -lt "$seconds" ]; do
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        echo "[timeout ${seconds}s，以下为已收集输出]"
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    else
        wait "$pid"
        rc=$?
        if [ "$rc" -ne 0 ]; then
            echo "[exit $rc]"
        fi
    fi

    if [ -s "$output_file" ]; then
        sed -n '1,220p' "$output_file"
    else
        echo "无输出。"
    fi
    rm -f "$output_file"
}

run_probe_timeout() {
    local seconds="$1"
    shift
    local output_file pid elapsed rc

    output_file="$(mktemp -t xray-probe.XXXXXX)"
    "$@" >"$output_file" 2>&1 &
    pid=$!
    elapsed=0
    while kill -0 "$pid" 2>/dev/null && [ "$elapsed" -lt "$seconds" ]; do
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        echo "[timeout ${seconds}s]"
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    else
        wait "$pid"
        rc=$?
        if [ "$rc" -ne 0 ]; then
            echo "[exit $rc]"
        fi
    fi

    if [ -s "$output_file" ]; then
        sed -n '1,120p' "$output_file"
    else
        echo "无输出。"
    fi
    rm -f "$output_file"
}

diagnose_shell_paths() {
    echo ""
    echo "===== 登录 Shell 与 PATH 视角 ====="
    echo "SHELL=${SHELL:-}"
    echo "current PATH=$PATH"

    echo "--- /etc/shells"
    sed -n "1,120p" /etc/shells 2>/dev/null || true

    echo "--- zsh login shell"
    if command -v zsh >/dev/null 2>&1; then
        run_probe_timeout 5 zsh -lc 'echo "PATH=$PATH"; command -v brew || true; command -v xray || true'
    else
        echo "zsh not found"
    fi

    echo "--- fish shell"
    if command -v fish >/dev/null 2>&1; then
        run_probe_timeout 5 fish -c 'echo "PATH=$PATH"; command -v brew; command -v xray'
    else
        echo "fish not found"
    fi

    echo "--- shell init files"
    for path in "$HOME/.zprofile" "$HOME/.zshrc" "$HOME/.config/fish/config.fish"; do
        echo "--- $path"
        if [ -f "$path" ]; then
            grep -nE "homebrew|brew shellenv|/opt/homebrew|/usr/local/bin|xray" "$path" 2>/dev/null || echo "no matching lines"
        else
            echo "not found"
        fi
    done
}

find_brew_bin() {
    if command -v brew &>/dev/null; then
        command -v brew
        return 0
    fi

    for path in \
        /opt/homebrew/bin/brew \
        /usr/local/bin/brew; do
        if [ -x "$path" ]; then
            echo "$path"
            return 0
        fi
    done
}

setup_homebrew_env() {
    local brew_bin
    brew_bin="$(find_brew_bin)"
    if [ -n "$brew_bin" ]; then
        eval "$("$brew_bin" shellenv)"
        return 0
    fi
    return 1
}

find_xray_config() {
    local prefix
    setup_homebrew_env >/dev/null 2>&1 || true
    if command -v brew &>/dev/null; then
        prefix="$(brew --prefix 2>/dev/null || true)"
        if [ -n "$prefix" ] && [ -f "$prefix/etc/xray/config.json" ]; then
            echo "$prefix/etc/xray/config.json"
            return 0
        fi
    fi

    for path in \
        /opt/homebrew/etc/xray/config.json \
        /usr/local/etc/xray/config.json; do
        if [ -f "$path" ]; then
            echo "$path"
            return 0
        fi
    done
}

find_xray_bin() {
    setup_homebrew_env >/dev/null 2>&1 || true
    if command -v xray &>/dev/null; then
        command -v xray
        return 0
    fi

    for path in \
        /opt/homebrew/bin/xray \
        /usr/local/bin/xray \
        /opt/homebrew/opt/xray/bin/xray \
        /usr/local/opt/xray/bin/xray; do
        if [ -x "$path" ]; then
            echo "$path"
            return 0
        fi
    done
}

foreground_run_check() {
    local xray_bin="$1"
    local config="$2"
    local output_file pid status

    echo ""
    echo "===== Xray 前台启动探测（4 秒后自动停止）====="
    if [ -z "$xray_bin" ] || [ -z "$config" ]; then
        echo "缺少 xray 或 config.json，跳过前台启动探测"
        return 0
    fi

    output_file="$(mktemp -t xray-run-check.XXXXXX)"
    "$xray_bin" run --config "$config" >"$output_file" 2>&1 &
    pid=$!
    sleep 4

    if kill -0 "$pid" 2>/dev/null; then
        echo "Xray 已持续运行 4 秒，说明前台启动没有立即崩溃。"
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    else
        wait "$pid"
        status=$?
        echo "Xray 前台启动后退出，退出码: $status"
    fi

    if [ -s "$output_file" ]; then
        echo ""
        echo "--- 前台启动输出 ---"
        sed -n '1,160p' "$output_file"
    else
        echo "前台启动没有输出。"
    fi
    rm -f "$output_file"
}

print_status_line() {
    local label="$1"
    local status="$2"
    local detail="${3:-}"

    if [ -n "$detail" ]; then
        printf '%-18s %s  %s\n' "$label:" "$status" "$detail"
    else
        printf '%-18s %s\n' "$label:" "$status"
    fi
}

diagnose_xray_brief() {
    set +e

    setup_homebrew_env >/dev/null 2>&1 || true

    local config xray_bin uid brew_bin brew_prefix xray_version loaded_status service_pid service_state
    local xray_test_output port_output launch_output user_domain

    config="$(find_xray_config)"
    xray_bin="$(find_xray_bin)"
    uid="$(id -u)"
    user_domain="gui/$uid/homebrew.mxcl.xray"
    brew_bin="$(find_brew_bin)"
    brew_prefix=""
    if [ -n "$brew_bin" ]; then
        brew_prefix="$("$brew_bin" --prefix 2>/dev/null || true)"
    fi
    if [ -n "$xray_bin" ]; then
        xray_version="$("$xray_bin" version 2>/dev/null | head -1 || true)"
    else
        xray_version=""
    fi
    launch_output="$(launchctl print "$user_domain" 2>&1)"

    echo "========================================="
    echo "  Xray 服务诊断摘要"
    echo "========================================="
    echo "时间: $(date)"
    echo "用户: $(whoami) (uid=$uid)"
    echo "Shell: ${SHELL:-unknown}"
    echo ""

    if [ -n "$brew_bin" ]; then
        print_status_line "Homebrew" "OK" "$brew_bin (${brew_prefix:-unknown prefix})"
    else
        print_status_line "Homebrew" "MISSING" "PATH 中没有 brew，常见路径也未找到"
    fi

    if [ -n "$xray_bin" ]; then
        print_status_line "Xray" "OK" "$xray_bin ${xray_version:+- $xray_version}"
    else
        print_status_line "Xray" "MISSING" "未找到 xray 命令"
    fi

    if [ -n "$config" ]; then
        print_status_line "配置文件" "OK" "$config"
    else
        print_status_line "配置文件" "MISSING" "未找到 config.json"
    fi

    echo ""
    echo "===== 配置验证 ====="
    if [ -n "$xray_bin" ] && [ -n "$config" ]; then
        xray_test_output="$("$xray_bin" run -test -c "$config" 2>&1)"
        if [ $? -eq 0 ]; then
            echo "OK: Configuration OK"
        else
            echo "FAILED:"
            echo "$xray_test_output" | sed -n '1,80p'
        fi
    else
        echo "SKIP: 缺少 xray 或 config.json"
    fi

    echo ""
    echo "===== 服务状态 ====="
    if echo "$launch_output" | grep -q "Could not find service"; then
        print_status_line "Loaded" "false" "$user_domain"
        print_status_line "Running" "false"
        print_status_line "PID" "none"
    else
        loaded_status="true"
        service_state="$(echo "$launch_output" | awk -F'= ' '/state =/ {print $2; exit}')"
        service_pid="$(echo "$launch_output" | awk -F'= ' '/pid =/ {print $2; exit}')"
        print_status_line "Loaded" "$loaded_status" "$user_domain"
        print_status_line "Running" "${service_state:-unknown}"
        print_status_line "PID" "${service_pid:-unknown}"
    fi

    echo ""
    echo "===== 端口占用 ====="
    for port in 28880 28881; do
        port_output="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1 " pid=" $2 " user=" $3}')"
        if [ -n "$port_output" ]; then
            print_status_line "$port" "LISTEN" "$port_output"
        else
            print_status_line "$port" "NOT_LISTEN"
        fi
    done

    echo ""
    echo "===== launchctl 摘要 ====="
    if echo "$launch_output" | grep -q "Could not find service"; then
        echo "未找到用户服务: $user_domain"
    else
        echo "$launch_output" | grep -E 'state =|path =|program =|last exit code|pid =|runs =' | grep -v 'state = active' | sed -n '1,40p'
    fi

    echo ""
    echo "日志: 默认摘要跳过较慢的系统日志扫描；需要日志请加 --verbose。"

    if [ "$DIAGNOSE_RUN_CHECK" = true ]; then
        foreground_run_check "$xray_bin" "$config"
    else
        echo ""
        echo "可选深入检查:"
        echo "  $0 --diagnose --run-check     # 前台试跑 4 秒"
        echo "  $0 --diagnose --verbose       # 输出完整诊断"
    fi

    echo ""
    echo "========================================="
    echo "  诊断摘要完成"
    echo "========================================="
}

diagnose_xray() {
    set +e

    setup_homebrew_env >/dev/null 2>&1 || true

    local config xray_bin uid brew_bin brew_prefix
    config="$(find_xray_config)"
    xray_bin="$(find_xray_bin)"
    uid="$(id -u)"
    brew_bin="$(find_brew_bin)"
    brew_prefix=""
    if [ -n "$brew_bin" ]; then
        brew_prefix="$("$brew_bin" --prefix 2>/dev/null || true)"
    fi

    echo "========================================="
    echo "  Xray / Homebrew 服务诊断"
    echo "========================================="
    echo "时间: $(date)"
    echo "用户: $(whoami) (uid=$uid)"
    echo "Shell: ${SHELL:-unknown}"
    echo "Bash: ${BASH_VERSION:-unknown}"
    echo "PATH: $PATH"
    echo "brew: ${brew_bin:-not found}"
    echo "brew prefix: ${brew_prefix:-not found}"
    echo "xray: ${xray_bin:-not found}"
    echo ""
    echo "提示: 诊断不会主动打印完整 config.json，避免泄露节点信息。"

    run_diag_shell "系统信息" 'sw_vers 2>/dev/null; uname -a; printf "arch: "; arch'
    diagnose_shell_paths
    run_diag_shell_timeout "Homebrew 基本信息" 8 '
if ! command -v brew >/dev/null 2>&1; then
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$p" ]; then eval "$("$p" shellenv)"; break; fi
  done
fi
command -v brew
brew --version
brew --prefix
brew services --help | sed -n "1,80p"
'
    run_diag_shell_timeout "Homebrew doctor 摘要" 8 '
if ! command -v brew >/dev/null 2>&1; then
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$p" ]; then eval "$("$p" shellenv)"; break; fi
  done
fi
brew doctor 2>&1 | sed -n "1,80p"
'
    run_diag_shell_timeout "Xray 安装信息" 8 '
if ! command -v brew >/dev/null 2>&1; then
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$p" ]; then eval "$("$p" shellenv)"; break; fi
  done
fi
command -v xray
xray version | sed -n "1,8p"
brew list --versions xray 2>/dev/null
'

    echo ""
    echo "===== Xray 配置文件 ====="
    if [ -n "$config" ]; then
        echo "config: $config"
        ls -l "$config"
        shasum -a 256 "$config" 2>/dev/null || true
    else
        echo "未找到常见位置的 Xray 配置文件。"
    fi

    echo ""
    echo "===== Xray 配置验证 ====="
    if [ -n "$xray_bin" ] && [ -n "$config" ]; then
        "$xray_bin" run -test -c "$config" 2>&1
        echo "[exit $?]"
    else
        echo "缺少 xray 或 config.json，无法验证配置。"
    fi

    run_diag_shell_timeout "Homebrew 服务状态" 8 '
if ! command -v brew >/dev/null 2>&1; then
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$p" ]; then eval "$("$p" shellenv)"; break; fi
  done
fi
brew services info xray
echo
brew services list | sed -n "1p;/xray/p"
'
    run_diag_shell "LaunchAgent 文件" 'for p in "$HOME/Library/LaunchAgents/homebrew.mxcl.xray.plist" "/Library/LaunchDaemons/homebrew.mxcl.xray.plist"; do echo "--- $p"; if [ -f "$p" ]; then ls -l "$p"; sed -n "1,160p" "$p"; else echo "not found"; fi; done'
    run_diag_shell "launchctl 用户服务状态" "launchctl print gui/$uid/homebrew.mxcl.xray 2>&1 | tail -120"
    run_diag_shell "launchctl 系统服务状态" 'launchctl print system/homebrew.mxcl.xray 2>&1 | tail -120'
    run_diag_shell "Xray 进程" 'pgrep -af xray || true'
    run_diag_shell "代理端口占用" 'lsof -nP -iTCP:28880 -sTCP:LISTEN; echo; lsof -nP -iTCP:28881 -sTCP:LISTEN'
    run_diag_shell_timeout "最近 20 分钟系统日志" 8 'log show --last 20m --style compact --predicate '"'"'process == "xray" OR eventMessage CONTAINS[c] "homebrew.mxcl.xray" OR eventMessage CONTAINS[c] "xray"'"'"' 2>&1 | tail -160'

    if [ "$DIAGNOSE_RUN_CHECK" = true ]; then
        foreground_run_check "$xray_bin" "$config"
    else
        echo ""
        echo "===== 可选前台启动探测 ====="
        echo "如需验证 Xray 是否能真正绑定端口并持续运行，请执行:"
        echo "  $0 --diagnose --run-check"
    fi

    echo ""
    echo "========================================="
    echo "  诊断完成"
    echo "========================================="
}

if [ "$DIAGNOSE" = true ]; then
    if [ "$DIAGNOSE_VERBOSE" = true ]; then
        diagnose_xray
    else
        diagnose_xray_brief
    fi
    exit 0
fi

if [ -z "$SUB_URL" ]; then
    usage
    exit 1
fi

# ============ 环境准备 ============
ensure_homebrew() {
    if setup_homebrew_env; then
        log_ok "Homebrew 已安装 ($(command -v brew))"
        return
    fi
    log_info "正在安装 Homebrew..."
    if ! /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" < /dev/null; then
        log_err "Homebrew 安装失败，请手动安装: https://brew.sh"
        echo ""
        log_info "开始输出诊断信息..."
        diagnose_xray
        exit 1
    fi
    if ! setup_homebrew_env; then
        log_err "Homebrew 安装后未找到 brew 命令，请手动配置 PATH"
        echo ""
        log_info "开始输出诊断信息..."
        diagnose_xray
        exit 1
    fi
    log_ok "Homebrew 安装完成"
}

ensure_xray() {
    setup_homebrew_env >/dev/null 2>&1 || true
    if command -v xray &>/dev/null; then
        log_ok "Xray 已安装 ($(xray version | head -1))"
        return
    fi
    log_info "正在通过 Homebrew 安装 Xray..."
    if ! brew install xray < /dev/null; then
        log_err "Xray 安装失败，请手动执行: brew install xray"
        echo ""
        log_info "开始输出诊断信息..."
        diagnose_xray
        exit 1
    fi
    setup_homebrew_env >/dev/null 2>&1 || true
    if ! command -v xray &>/dev/null; then
        log_err "Xray 安装后未找到 xray 命令，请检查 PATH 或手动执行: brew install xray"
        echo ""
        log_info "开始输出诊断信息..."
        diagnose_xray
        exit 1
    fi
    log_ok "Xray 安装完成 ($(xray version | head -1))"
}

# ============ 订阅解析 ============
if [[ "$SUB_URL" == vless://* ]]; then
    log_info "检测到单条 VLESS 节点，跳过订阅下载和 base64 解码..."
    DECODED="$SUB_URL"
else
    log_info "获取订阅内容..."
    RAW=$(curl -sf "$SUB_URL") || { log_err "无法获取订阅链接"; exit 1; }
    DECODED=$(echo "$RAW" | base64 -d 2>/dev/null) || { log_err "base64 解码失败"; exit 1; }
fi

# 提取 vless:// 节点
NODES=()
while IFS= read -r line; do
    [ -z "$line" ] && continue
    [[ "$line" == vless://* ]] && NODES+=("$line")
done <<< "$DECODED"

if [ ${#NODES[@]} -eq 0 ]; then
    log_err "未找到 vless:// 节点"
    exit 1
fi

log_ok "找到 ${#NODES[@]} 个节点"

# 解析第一个节点
VLESS="${NODES[0]}"

# 提取节点名称（# 后面的部分）
NODE_NAME=""
if [[ "$VLESS" == *"#"* ]]; then
    NODE_NAME=$(urldecode "${VLESS##*#}")
    VLESS="${VLESS%%#*}"
fi

# 提取 uuid@address:port 和参数
BODY="${VLESS#vless://}"
USER_HOST="${BODY%%\?*}"
PARAMS="${BODY#*\?}"

UUID="${USER_HOST%%@*}"
HOST_PORT="${USER_HOST#*@}"
ADDRESS="${HOST_PORT%:*}"
PORT="${HOST_PORT##*:}"

# 解析查询参数
parse_param() {
    local key="$1"
    local val=""
    local IFS='&'
    for pair in $PARAMS; do
        if [ "${pair%%=*}" = "$key" ]; then
            val="${pair#*=}"
            break
        fi
    done
    if [ -n "$val" ]; then
        urldecode "$val"
    fi
}

ENCRYPTION=$(parse_param "encryption")
SECURITY=$(parse_param "security")
TYPE=$(parse_param "type")
SNI=$(parse_param "sni")
FP=$(parse_param "fp")
PBK=$(parse_param "pbk")
SID=$(parse_param "sid")
SPX=$(parse_param "spx")
FLOW=$(parse_param "flow")

# 默认值
ENCRYPTION="${ENCRYPTION:-none}"
TYPE="${TYPE:-tcp}"
FP="${FP:-chrome}"

echo ""
echo "节点信息:"
echo "  名称:  $NODE_NAME"
echo "  地址:  $ADDRESS"
echo "  端口:  $PORT"
echo "  UUID:  ${UUID:0:8}..."
echo "  传输:  $TYPE"
echo "  安全:  $SECURITY"
echo "  SNI:   $SNI"
echo ""

# ============ 生成配置 ============

# 构建 users 部分
if [ -n "$FLOW" ]; then
    USERS_JSON="{ \"id\": \"$UUID\", \"encryption\": \"$ENCRYPTION\", \"flow\": \"$FLOW\" }"
else
    USERS_JSON="{ \"id\": \"$UUID\", \"encryption\": \"$ENCRYPTION\" }"
fi

# 构建 streamSettings 部分
build_stream_json() {
    if [ "$SECURITY" = "reality" ]; then
        cat <<STREAM
    "streamSettings": {
      "network": "$TYPE",
      "security": "reality",
      "realitySettings": {
        "serverName": "$SNI",
        "publicKey": "$PBK",
        "shortId": "$SID",
        "spiderX": "$SPX",
        "fingerprint": "$FP"
      }
    }
STREAM
    elif [ "$SECURITY" = "tls" ]; then
        cat <<STREAM
    "streamSettings": {
      "network": "$TYPE",
      "security": "tls",
      "tlsSettings": {
        "serverName": "$SNI",
        "fingerprint": "$FP"
      }
    }
STREAM
    else
        cat <<STREAM
    "streamSettings": {
      "network": "$TYPE",
      "security": "none"
    }
STREAM
    fi
}

STREAM_JSON=$(build_stream_json)

# 完整配置
CONFIG=$(cat <<EOF
{
  "log": {
    "loglevel": "warning"
  },
  "dns": {
    "servers": [
      "8.8.8.8",
      "1.1.1.1"
    ],
    "tag": "dns_inbound"
  },
  "inbounds": [
    {
      "tag": "socks-in",
      "protocol": "socks",
      "listen": "127.0.0.1",
      "port": 28880,
      "settings": {
        "auth": "noauth",
        "udp": true
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    },
    {
      "tag": "http-in",
      "protocol": "http",
      "listen": "127.0.0.1",
      "port": 28881,
      "settings": {
        "allowTransparent": false
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    {
      "tag": "proxy",
      "protocol": "vless",
      "settings": {
        "vnext": [
          {
            "address": "$ADDRESS",
            "port": $PORT,
            "users": [
              $USERS_JSON
            ]
          }
        ]
      },
$STREAM_JSON
    },
    {
      "tag": "direct",
      "protocol": "freedom"
    },
    {
      "tag": "blocked",
      "protocol": "blackhole"
    }
  ],
  "routing": {
    "domainStrategy": "AsIs",
    "rules": [
      {
        "type": "field",
        "domain": ["geosite:category-ads-all"],
        "outboundTag": "blocked"
      },
      {
        "type": "field",
        "ip": ["geoip:private"],
        "outboundTag": "direct"
      },
      {
        "type": "field",
        "port": "0-65535",
        "outboundTag": "proxy"
      }
    ]
  }
}
EOF
)

# ============ dry-run 模式 ============
if [ "$DRY_RUN" = true ]; then
    echo "===== Xray 配置（dry-run）====="
    echo "$CONFIG"
    echo ""
    echo "本地代理端口:"
    echo "  SOCKS5: 127.0.0.1:28880"
    echo "  HTTP:   127.0.0.1:28881"
    exit 0
fi

# ============ 安装环境 ============
ensure_homebrew
ensure_xray

# ============ 应用配置 ============
BREW_PREFIX="$(brew --prefix)"
XRAY_CONFIG="${BREW_PREFIX}/etc/xray/config.json"

# 确保配置目录存在（权限不足时使用 sudo）
XRAY_DIR="$(dirname "$XRAY_CONFIG")"
if ! mkdir -p "$XRAY_DIR" 2>/dev/null; then
    log_info "需要管理员权限写入配置目录..."
    sudo mkdir -p "$XRAY_DIR"
    sudo chown -R "$(whoami)" "$XRAY_DIR"
fi

# 备份现有配置
if [ -f "$XRAY_CONFIG" ]; then
    cp "$XRAY_CONFIG" "${XRAY_CONFIG}.bak"
    log_info "已备份旧配置到 ${XRAY_CONFIG}.bak"
fi

# 写入新配置
echo "$CONFIG" > "$XRAY_CONFIG"
log_ok "配置已写入 $XRAY_CONFIG"

# 验证配置
XRAY_TEST_OUTPUT=$(xray run -test -c "$XRAY_CONFIG" 2>&1) || {
    log_err "配置验证失败，Xray 输出:"
    echo "$XRAY_TEST_OUTPUT"
    log_err "正在还原旧配置..."
    if [ -f "${XRAY_CONFIG}.bak" ]; then
        cp "${XRAY_CONFIG}.bak" "$XRAY_CONFIG"
    fi
    echo ""
    log_info "开始输出诊断信息..."
    diagnose_xray
    exit 1
}
if [ -n "$XRAY_TEST_OUTPUT" ]; then
    echo "$XRAY_TEST_OUTPUT"
fi
log_ok "配置验证通过"

# 启动/重启服务
log_info "正在启动 Xray 服务..."
BREW_OUTPUT=$(brew services restart xray 2>&1) || {
    log_err "Xray 服务启动失败:"
    echo "  $BREW_OUTPUT"
    echo ""
    log_info "开始输出诊断信息..."
    diagnose_xray
    exit 1
}
SERVICE_RUNNING=false
for _ in 1 2 3 4 5; do
    sleep 1
    if brew services info xray 2>/dev/null | grep -q "Running: true"; then
        SERVICE_RUNNING=true
        break
    fi
done

if [ "$SERVICE_RUNNING" = true ]; then
    log_ok "Xray 服务已启动"
else
    log_err "Xray 服务未正常运行，开始输出诊断信息..."
    echo "提示: Homebrew services 通常没有 log 子命令，因此这里改为收集 launchctl、端口占用和系统日志。"
    diagnose_xray
    exit 1
fi

echo ""
echo "========================================="
echo "  部署完成！"
echo "========================================="
echo ""
echo "  本地代理端口:"
echo "    SOCKS5:  127.0.0.1:28880"
echo "    HTTP:    127.0.0.1:28881"
echo ""
echo "  节点: $NODE_NAME"
echo "  配置: $XRAY_CONFIG"
echo ""
echo "  测试: curl -x socks5://127.0.0.1:28880 https://www.google.com"
echo "========================================="
