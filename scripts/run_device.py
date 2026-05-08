"""设备统一启动入口。

目标运行模式：
    1. 设备启动后，视觉模块自动启动并持续检测；
    2. 语音模块自动启动，默认处于待机状态，等待唤醒词；
    3. 视觉正常时不报警；
    4. 视觉异常或报警时自动语音播报；
    5. Ctrl+C 时同时关闭两个子进程。

运行：
    D:\\anaconda3\\envs\\rk3588-ai\\python.exe scripts/run_device.py

调试时如果不能说话，可以加：
    D:\\anaconda3\\envs\\rk3588-ai\\python.exe scripts/run_device.py --voice-text
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def start_process(name, args):
    print(f"[DEVICE] starting {name}: {' '.join(str(item) for item in args)}")
    return subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def terminate_process(name, proc):
    if proc is None:
        return
    if proc.poll() is not None:
        return

    print(f"[DEVICE] stopping {name}")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(f"[DEVICE] killing {name}")
        proc.kill()


def main():
    parser = argparse.ArgumentParser(description="启动视觉连续检测和语音待机监听")
    parser.add_argument("--voice-text", action="store_true", help="语音模块使用文本模拟模式")
    parser.add_argument("--no-vision", action="store_true", help="不启动视觉模块，只启动语音模块")
    parser.add_argument("--no-voice", action="store_true", help="不启动语音模块，只启动视觉模块")
    args = parser.parse_args()

    python_exe = sys.executable
    vision_proc = None
    voice_proc = None

    try:
        if not args.no_vision:
            vision_proc = start_process("vision", [python_exe, "scripts/run_vision.py"])
            # 给视觉模块一点启动时间，避免语音立刻查询时 Socket 还没起来。
            time.sleep(2)

        if not args.no_voice:
            voice_args = [python_exe, "voice/voice_loop.py"]
            if args.voice_text:
                voice_args.append("--text")
            voice_proc = start_process("voice", voice_args)

        while True:
            if vision_proc is not None and vision_proc.poll() is not None:
                print(f"[DEVICE] vision exited with code {vision_proc.returncode}")
                break
            if voice_proc is not None and voice_proc.poll() is not None:
                print(f"[DEVICE] voice exited with code {voice_proc.returncode}")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("[DEVICE] Ctrl+C received")
    finally:
        terminate_process("voice", voice_proc)
        terminate_process("vision", vision_proc)
        print("[DEVICE] stopped")


if __name__ == "__main__":
    main()
