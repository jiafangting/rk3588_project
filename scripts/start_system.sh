#!/bin/bash

# 工业巡检系统一键启动脚本。
#
# 启动顺序：
#   1. C 主进程
#   2. Python 视觉模块
#   3. Python 语音模块
#
# 重要参数：
#   DIR            : 脚本所在目录，自动识别项目根目录
#   LOG_DIR        : 三个模块日志目录
#   PID_FILE       : 保存进程 PID，供 stop_system.sh 和 health_check.sh 使用
#   C_MAIN_CMD     : C 主进程启动命令
#   VISION_CMD     : Python 视觉模块启动命令
#   VOICE_CMD      : Python 语音模块启动命令

set -u

DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$DIR/.." && pwd)
LOG_DIR="$ROOT/logs"
PID_FILE="/tmp/inspection_pids.txt"
C_MAIN_LOG="$LOG_DIR/c_main.log"
VISION_LOG="$LOG_DIR/vision.log"
VOICE_LOG="$LOG_DIR/voice.log"

# 项目入口路径。如果未来再调整目录结构，只需改这几行。
C_MAIN_CMD="$ROOT/rk3588/inspection"
VISION_CMD="python3 $ROOT/vision/app/vision_main.py"
VOICE_CMD="python3 $ROOT/voice/voice_loop.py"

C_MAIN_PID=""
VISION_PID=""
VOICE_PID=""

mkdir -p "$LOG_DIR"

cleanup() {
    echo "正在关闭所有模块..."
    if [ -n "${C_MAIN_PID}" ]; then kill "$C_MAIN_PID" 2>/dev/null; fi
    if [ -n "${VISION_PID}" ]; then kill "$VISION_PID" 2>/dev/null; fi
    if [ -n "${VOICE_PID}" ]; then kill "$VOICE_PID" 2>/dev/null; fi
    rm -f "$PID_FILE"
    exit 0
}

trap cleanup SIGINT SIGTERM

# -------------------------
# 第一步：启动 C 主进程
# -------------------------
echo "[START] 启动 C 主进程..."
"$C_MAIN_CMD" > "$C_MAIN_LOG" 2>&1 &
C_MAIN_PID=$!
sleep 2
if ! kill -0 "$C_MAIN_PID" 2>/dev/null; then
    echo "[ERROR] C 主进程启动失败"
    exit 1
fi

# -------------------------
# 第二步：启动视觉模块
# -------------------------
echo "[START] 启动视觉模块..."
$VISION_CMD > "$VISION_LOG" 2>&1 &
VISION_PID=$!
sleep 3
if ! kill -0 "$VISION_PID" 2>/dev/null; then
    echo "[ERROR] 视觉模块启动失败"
    cleanup
fi

# -------------------------
# 第三步：启动语音模块
# -------------------------
echo "[START] 启动语音模块..."
$VOICE_CMD > "$VOICE_LOG" 2>&1 &
VOICE_PID=$!
sleep 2
if ! kill -0 "$VOICE_PID" 2>/dev/null; then
    echo "[ERROR] 语音模块启动失败"
    cleanup
fi

# 保存 PID，方便停止和健康检查。
cat > "$PID_FILE" <<EOF
C_MAIN_PID=$C_MAIN_PID
VISION_PID=$VISION_PID
VOICE_PID=$VOICE_PID
EOF

cat <<EOF
=============================
工业巡检系统启动完成
C主进程  PID: $C_MAIN_PID
视觉模块 PID: $VISION_PID
语音模块 PID: $VOICE_PID
=============================
EOF

echo "日志目录：$LOG_DIR"
echo "PID 文件：$PID_FILE"
echo "可执行权限示例：chmod +x scripts/*.sh deploy/install_service.sh"

# 保持脚本前台运行，便于 Ctrl+C 统一关闭。
while true; do
    if ! kill -0 "$C_MAIN_PID" 2>/dev/null; then
        echo "[WARN] C 主进程已退出"
        cleanup
    fi
    if ! kill -0 "$VISION_PID" 2>/dev/null; then
        echo "[WARN] 视觉模块已退出"
        cleanup
    fi
    if ! kill -0 "$VOICE_PID" 2>/dev/null; then
        echo "[WARN] 语音模块已退出"
        cleanup
    fi
    sleep 5
done
