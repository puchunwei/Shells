#!/bin/bash
# 订阅链接转 Xray 配置 + 一键部署脚本（纯 shell，无 python 依赖）
# 用法:
#   ./sub2xray.sh <订阅URL>            # 安装环境 + 生成配置 + 启动服务
#   ./sub2xray.sh <订阅URL> --dry-run   # 仅输出配置，不安装不应用

set -euo pipefail

# ============ 参数解析 ============
SUB_URL=""
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        -*) echo "未知选项: $arg"; exit 1 ;;
        *) SUB_URL="$arg" ;;
    esac
done

if [ -z "$SUB_URL" ]; then
    echo "用法: $0 <订阅URL> [--dry-run]"
    echo ""
    echo "示例:"
    echo "  $0 https://u.youlin.online/sub/xxxxx           # 一键部署"
    echo "  $0 https://u.youlin.online/sub/xxxxx --dry-run  # 仅查看配置"
    exit 1
fi

# ============ 工具函数 ============
urldecode() {
    local encoded="$1"
    encoded="${encoded//+/ }"
    printf '%b' "${encoded//%/\\x}"
}

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_err()   { echo "[ERROR] $*" >&2; }

# ============ 环境准备 ============
ensure_homebrew() {
    if command -v brew &>/dev/null; then
        log_ok "Homebrew 已安装"
        return
    fi
    log_info "正在安装 Homebrew..."
    if ! /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" < /dev/null; then
        log_err "Homebrew 安装失败，请手动安装: https://brew.sh"
        exit 1
    fi
    # Apple Silicon 路径
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -f /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    if ! command -v brew &>/dev/null; then
        log_err "Homebrew 安装后未找到 brew 命令，请手动配置 PATH"
        exit 1
    fi
    log_ok "Homebrew 安装完成"
}

ensure_xray() {
    if command -v xray &>/dev/null; then
        log_ok "Xray 已安装 ($(xray version | head -1))"
        return
    fi
    log_info "正在通过 Homebrew 安装 Xray..."
    if ! brew install xray < /dev/null; then
        log_err "Xray 安装失败，请手动执行: brew install xray"
        exit 1
    fi
    if ! command -v xray &>/dev/null; then
        log_err "Xray 安装后未找到 xray 命令，请检查 PATH 或手动执行: brew install xray"
        exit 1
    fi
    log_ok "Xray 安装完成 ($(xray version | head -1))"
}

# ============ 订阅解析 ============
log_info "获取订阅内容..."
RAW=$(curl -sf "$SUB_URL") || { log_err "无法获取订阅链接"; exit 1; }
DECODED=$(echo "$RAW" | base64 -d 2>/dev/null) || { log_err "base64 解码失败"; exit 1; }

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
if xray run -test -c "$XRAY_CONFIG" &>/dev/null; then
    log_ok "配置验证通过"
else
    log_err "配置验证失败，正在还原旧配置..."
    if [ -f "${XRAY_CONFIG}.bak" ]; then
        cp "${XRAY_CONFIG}.bak" "$XRAY_CONFIG"
    fi
    exit 1
fi

# 启动/重启服务
log_info "正在启动 Xray 服务..."
BREW_OUTPUT=$(brew services restart xray 2>&1) || {
    log_err "Xray 服务启动失败:"
    echo "  $BREW_OUTPUT"
    exit 1
}
sleep 2
if brew services info xray 2>/dev/null | grep -q "Running: true"; then
    log_ok "Xray 服务已启动"
else
    log_err "Xray 服务未正常运行，请检查日志:"
    echo "  brew services log xray"
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
