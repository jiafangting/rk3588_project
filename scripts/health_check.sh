#!/bin/bash

# 工业巡检系统健康检查脚本。
#
# 检查内容：
#   1. C 主进程是否存活
#   2. 视觉模块是否存活
#   3. 语音模块是否存活
#   4. 统一视觉 socket 是否可用

set -u

PID_FILE="/tmp/inspection_pids.txt"
# 视觉 socket 路径统一规则：
# - 默认值和 Python 视觉服务端、语音模块、UI、C 主控一致；
# - 部署时需要换路径，只设置 VISION_SOCKET_PATH 环境变量即可；
# - 不要在脚本里另写一个 /tmp/xxx.sock，避免健康检查和真实服务检查不同文件。
VISION_SOCK="${VISION_SOCKET_PATH:-/tmp/vision_inspection.sock}"
RET=0

get_pid() {
    local name="$1"
    if [ -f "$PID_FILE" ]; then
        # shellcheck disable=SC1090
        source "$PID_FILE"
        eval echo "\$$name"
    else
        echo ""
    fi
}

check_pid() {
    local label="$1"
    local pid="$2"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "$label:  ✓ 运行中 (PID: $pid)"
    else
        echo "$label:  ✗ 已停止"
        RET=1
    fi
}

C_MAIN_PID=$(get_pid C_MAIN_PID)
VISION_PID=$(get_pid VISION_PID)
VOICE_PID=$(get_pid VOICE_PID)

echo "============================="
echo "系统健康检查"
check_pid "C主进程" "$C_MAIN_PID"
check_pid "视觉模块" "$VISION_PID"
check_pid "语音模块" "$VOICE_PID"

if [ -S "$VISION_SOCK" ] || [ -e "$VISION_SOCK" ]; then
    echo "Vision Socket: ✓ 可用"
else
    echo "Vision Socket: ✗ 不可用"
    RET=1
fi

echo "============================="
exit "$RET"
