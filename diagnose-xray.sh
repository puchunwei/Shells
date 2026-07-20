#!/bin/bash
# Xray/Homebrew 服务诊断入口。
# 本地执行时复用同目录的 sub2xray.sh --diagnose；远程执行时拉取最新脚本。

set -euo pipefail

RAW_SUB2XRAY_URL="https://raw.githubusercontent.com/puchunwei/Shells/refs/heads/master/sub2xray.sh"
SOURCE_PATH=""

set +u
SOURCE_PATH="${BASH_SOURCE[0]}"
set -u

if [ -n "$SOURCE_PATH" ] && [ -f "$SOURCE_PATH" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$SOURCE_PATH")" 2>/dev/null && pwd || true)"
    LOCAL_SUB2XRAY="${SCRIPT_DIR}/sub2xray.sh"

    if [ -x "$LOCAL_SUB2XRAY" ]; then
        exec "$LOCAL_SUB2XRAY" --diagnose "$@"
    fi

    if [ -f "$LOCAL_SUB2XRAY" ]; then
        exec bash "$LOCAL_SUB2XRAY" --diagnose "$@"
    fi
fi

curl -Ls "$RAW_SUB2XRAY_URL" | bash -s -- --diagnose "$@"
