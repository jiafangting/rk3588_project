"""语音模块访问视觉模块的客户端。

语音模块通过这个文件控制视觉模块：
    - 查询当前视觉状态；
    - 触发一次巡检保存；
    - 把视觉结果整理成适合语音播报的中文句子。
"""

from __future__ import annotations

import json
from pathlib import Path
import socket
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VISION_APP_DIR = PROJECT_ROOT / "vision" / "app"
if str(VISION_APP_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_APP_DIR))

from socket_config import get_vision_socket_path


DEFAULT_VISION_SOCKET_PATH = get_vision_socket_path()
DEFAULT_VISION_TCP_HOST = "127.0.0.1"
DEFAULT_VISION_TCP_PORT = 8765

# 语音模块和视觉模块通常是两个独立进程。
# Unix Socket 路径必须和视觉服务端完全一致，否则语音侧会误判为
# “视觉模块未启动”。这里不再写死 /tmp 路径，而是复用 socket_config：
# 默认 /tmp/vision_inspection.sock，部署时用 VISION_SOCKET_PATH 覆盖。


class VisionSocketClient:
    """Unix Domain Socket 客户端。

    Python 视觉模块和 C 主控使用同一套 JSON 协议：

        {"cmd": "get_status"}
        {"cmd": "trigger_inspection"}
        {"cmd": "shutdown"}
    """

    def __init__(self, socket_path=DEFAULT_VISION_SOCKET_PATH, timeout=8.0, tcp_host=DEFAULT_VISION_TCP_HOST, tcp_port=DEFAULT_VISION_TCP_PORT):
        self.socket_path = socket_path
        self.timeout = timeout
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port

    def get_status(self):
        return self._send_command({"cmd": "get_status"})

    def trigger_inspection(self):
        return self._send_command({"cmd": "trigger_inspection"})

    def _send_command(self, payload):
        if not hasattr(socket, "AF_UNIX"):
            return self._send_tcp_command(payload)

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
            message = json.dumps(payload, ensure_ascii=False) + "\n"
            sock.sendall(message.encode("utf-8"))
            return self._read_until_status(sock)

    def _send_tcp_command(self, payload):
        with socket.create_connection((self.tcp_host, self.tcp_port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            message = json.dumps(payload, ensure_ascii=False) + "\n"
            sock.sendall(message.encode("utf-8"))
            return self._read_until_status(sock)

    def _read_until_status(self, sock):
        buffer = ""
        while True:
            data = sock.recv(4096)
            if not data:
                raise RuntimeError("视觉模块连接已关闭")

            buffer += data.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                result = json.loads(line)
                if "status" in result:
                    return result


def format_vision_result(prefix, result):
    """把视觉 JSON 结果整理成中文播报文本。"""
    status = result.get("status", "UNKNOWN")
    person_count = result.get("person_count", 0)
    reason = result.get("reason", "")

    if status == "NORMAL":
        status_text = "正常"
    elif status == "ABNORMAL":
        status_text = "异常"
    elif status == "ALARM":
        status_text = "报警"
    else:
        status_text = f"未知状态 {status}"

    return f"{prefix}。状态{status_text}。检测人数 {person_count}。{reason}。"
