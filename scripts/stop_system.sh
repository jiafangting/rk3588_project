#!/bin/bash

# 工业巡检系统停止脚本。
# 读取 /tmp/inspection_pids.txt，关闭所有模块。

set -u

DIR=$(cd "$(dirname "$0")" && pwd)
PID_FILE="/tmp/inspection_pids.txt"

if [ ! -f "$PID_FILE" ]; then
    echo "[ERROR] 找不到 PID 文件：$PID_FILE"
    exit 1
fi

# shellcheck disable=SC1090
source "$PID_FILE"

echo "正在关闭所有模块..."
kill "$C_MAIN_PID" "$VISION_PID" "$VOICE_PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "系统已停止"
