"""Mock 视觉 Socket 服务。

不启动摄像头、不加载 YOLO，也能测试语音模块控制视觉的流程。

运行：
    D:\\anaconda3\\envs\\rk3588-ai\\python.exe vision\\test\\mock_vision_socket_server.py

然后另开终端运行：
    D:\\anaconda3\\envs\\rk3588-ai\\python.exe voice\\voice_loop.py --text

输入：
    wake
    vision
    inspect
    stop
"""

from datetime import datetime
import json
from pathlib import Path
import socket
import sys
import threading
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "vision" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from vision_socket import DEFAULT_SOCKET_PATH


DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 8765


class MockVisionSocketServer:
    """极简视觉模块模拟器。"""

    def __init__(self, socket_path=DEFAULT_SOCKET_PATH, tcp_host=DEFAULT_TCP_HOST, tcp_port=DEFAULT_TCP_PORT):
        self.socket_path = Path(socket_path)
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.running = True
        self.inspection_count = 0
        self.latest_result = self._make_result("NORMAL", 1, "模拟视觉状态正常")

    def serve_forever(self):
        if not hasattr(socket, "AF_UNIX"):
            self._serve_tcp_forever()
            return

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            server.listen(4)
            server.settimeout(0.5)
            print(f"[MOCK_VISION] listening on {self.socket_path}")

            while self.running:
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

        self._cleanup_socket()

    def _serve_tcp_forever(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.tcp_host, self.tcp_port))
            server.listen(4)
            server.settimeout(0.5)
            print(f"[MOCK_VISION] listening on tcp://{self.tcp_host}:{self.tcp_port}")

            while self.running:
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn):
        with conn:
            buffer = ""
            while self.running:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._process_command(conn, line)

    def _process_command(self, conn, line):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self._send(conn, {"ack": False, "message": "invalid json"})
            return

        cmd = payload.get("cmd")
        print(f"[MOCK_VISION] recv cmd: {cmd}")

        if cmd == "get_status":
            self._send(conn, self.latest_result)
            return

        if cmd == "trigger_inspection":
            self.inspection_count += 1
            if self.inspection_count % 2 == 0:
                self.latest_result = self._make_result("ALARM", 1, "模拟检测到人员进入右侧禁区")
            else:
                self.latest_result = self._make_result("NORMAL", 1, "模拟巡检正常，检测到 1 名人员")

            self._send(conn, {"ack": True, "cmd": cmd, "message": "mock inspection accepted"})
            time.sleep(0.2)
            self._send(conn, self.latest_result)
            return

        if cmd == "shutdown":
            self._send(conn, {"ack": True, "cmd": cmd, "message": "mock shutdown accepted"})
            self.running = False
            return

        self._send(conn, {"ack": False, "cmd": cmd, "message": "unknown command"})

    def _make_result(self, status, person_count, reason):
        return {
            "status": status,
            "person_count": person_count,
            "reason": reason,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _send(self, conn, payload):
        message = json.dumps(payload, ensure_ascii=False) + "\n"
        conn.sendall(message.encode("utf-8"))

    def _cleanup_socket(self):
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except Exception:
            pass


def main():
    server = MockVisionSocketServer()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[MOCK_VISION] stopping")
    finally:
        server.running = False
        server._cleanup_socket()


if __name__ == "__main__":
    main()
