"""视觉服务共用的 socket 配置。

这个项目里有好几个独立进程都要和 Python 视觉模块通信：

- ``vision/app/vision_socket.py`` 负责真正创建 socket 服务端；
- ``voice/vision_control.py`` 会给这个服务端发送语音控制命令；
- ``ui`` 会查询同一个服务端，拿实时状态和发送重新加载配置通知；
- ``rk3588/thread_vision.c`` 里的 C 主控也使用同一路径。

默认路径统一放在这里，避免每个文件各写一个路径。
部署时优先设置环境变量 ``VISION_SOCKET_PATH``，不要到处改源码。
本仓库里的 Python 调用方都会通过 ``get_vision_socket_path()`` 读取这个配置。
"""

from __future__ import annotations

import os
from pathlib import Path


VISION_SOCKET_ENV = "VISION_SOCKET_PATH"
DEFAULT_LINUX_VISION_SOCKET_PATH = "/tmp/vision_inspection.sock"


def _default_socket_path() -> str:
    """返回当前平台更合适的默认 socket 路径。

    在 RK3588 Linux 上，`/tmp/vision_inspection.sock` 很适合放运行时 Unix socket。

    在 Windows 上，`/tmp/...` 会被解释成当前盘符下的路径，例如 `E:\\tmp\\...`。
    这个目录不一定存在，也不容易发现。
    所以 Windows 开发阶段改用项目里的 `.tmp` 目录，让仿真器、UI、语音模块
    不用硬件也能直接跑起来。
    """

    if os.name == "nt":
        project_root = Path(__file__).resolve().parents[2]
        return str(project_root / ".tmp" / "vision_inspection.sock")
    return DEFAULT_LINUX_VISION_SOCKET_PATH


DEFAULT_VISION_SOCKET_PATH = _default_socket_path()


def get_vision_socket_path() -> str:
    """返回所有 Python 模块共用的视觉 socket 路径。

    这里故意优先读取环境变量，而不是把部署路径写死在多个文件里。
    如果环境变量是空字符串，就当作没配置，避免客户端去连接一个空路径。
    """

    configured_path = os.environ.get(VISION_SOCKET_ENV, "").strip()
    if configured_path:
        return configured_path
    return DEFAULT_VISION_SOCKET_PATH
