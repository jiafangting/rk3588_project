"""Python 视觉模块的 Socket 通信服务。

这个文件是视觉模块对外“发布状态”和“接收命令”的通信层。
它不做目标检测本身，也不做 UI 排版，而是专门负责：

1. 把视觉模块当前状态缓存起来；
2. 让外部进程通过 `get_status` 查询状态；
3. 接收 `trigger_inspection`、`reload_config`、`shutdown` 等命令；
4. 在 Unix Domain Socket 不可用时自动降级到 TCP。

【你学习这个文件时最该先懂的三件事】
1. 它不是识别算法，它只是“通信门口”；
2. 它对外只认 JSON，一行一条消息，末尾带 `\n`；
3. 它返回的是“缓存状态”，不是每次都重新跑视觉推理。

通信方式：
- 客户端发送一行 JSON 文本，末尾带 `\n`；
- 服务端按行读取请求；
- 解析出 `cmd` 字段后决定动作；
- 回复也是一行 JSON 文本；
- 外部程序只要会发 JSON，就能接入这套协议。

为什么要这样设计：
- 外部查询状态时，不应该重新跑一次视觉推理；
- 所以服务端把最新结果缓存到 `latest_result`；
- UI、语音、C 主控只需要读取缓存，不会拖慢主流程。

【和外部模块怎么配合】
- `vision_pipeline.py` 每帧调用 `update_status()` / `send_result()` 把最新状态写进来；
- UI 或语音模块发 `{"cmd":"get_status"}` 来查询当前状态；
- 发 `{"cmd":"trigger_inspection"}` 可以触发一次巡检保存；
- 发 `{"cmd":"reload_config"}` 可以通知重载配置；
- 发 `{"cmd":"shutdown"}` 可以优雅关闭服务。

【你最该重点看的位置】
- `VisionSocketServer.__init__()`：看默认路径、TCP 备用端口、缓存结构；
- `start()` / `_start_tcp()`：看服务怎么启动；
- `get_latest_status()` / `update_status()` / `send_result()`：看状态怎么缓存和广播；
- `_handle_client()` / `_process_command_text()`：看请求怎么解析和分发；
- `shutdown()`：看退出时怎么收尾。
"""

from datetime import datetime
import json
from pathlib import Path
import signal
import socket
import threading

from socket_config import get_vision_socket_path


DEFAULT_SOCKET_PATH = get_vision_socket_path()
DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 8765
MAX_BUFFER_SIZE = 64 * 1024


def _now_text():
    """返回当前时间字符串。

    返回值：
    - 格式化后的时间字符串，形如 `YYYY-MM-DD HH:MM:SS`

    作用：
    - 统一 Socket 响应里的时间格式；
    - 方便 UI、日志和语音模块直接显示。
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _socket_log(message):
    """打印 Socket 层日志。

    参数：
    - `message`：要输出的日志内容

    作用：
    - 让你在终端里快速看到 socket 是否启动、连接是否成功、命令是否失败。
    """
    print(f"[SOCKET] {message}")


class VisionSocketServer:
    """后台视觉 socket 服务。

    这个服务是整个项目里“大家都来问视觉状态”的统一出口：
    - UI 来问当前状态；
    - 语音模块来问当前状态或触发巡检；
    - C 主控未来也会用同样协议接入。

    默认监听路径来自 ``socket_config``，并且可以被环境变量
    ``VISION_SOCKET_PATH`` 覆盖。

    重要参数：
    - ``sock_path``：Unix Socket 路径；
    - ``tcp_host`` / ``tcp_port``：Windows 或不支持 AF_UNIX 时的 TCP 备用通道；
    - ``command_callback``：收到命令后交给上层处理的回调函数。
    """

    def __init__(self, sock_path=DEFAULT_SOCKET_PATH, command_callback=None, tcp_host=DEFAULT_TCP_HOST, tcp_port=DEFAULT_TCP_PORT):
        """初始化 Socket 服务对象。

        参数：
        - `sock_path`：Unix Socket 路径，默认从 `socket_config` 读取
        - `command_callback`：处理非 `get_status` 命令的回调
        - `tcp_host`：TCP 回退主机地址，默认 127.0.0.1
        - `tcp_port`：TCP 回退端口，默认 8765

        内部状态：
        - `latest_result`：最近一次视觉结果缓存
        - `clients`：当前连接的客户端列表
        - `running`：服务运行标志
        """
        self.sock_path = Path(sock_path)
        self.command_callback = command_callback
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.sock = None
        self.server_thread = None
        self.running = threading.Event()
        self.shutdown_requested = threading.Event()
        self.lock = threading.Lock()
        self.clients = []
        self.latest_result = {
            "status": "UNKNOWN",
            "person_count": 0,
            "reason": "Vision module is starting",
            "alarm_type": "",
            "alarm_reason": "",
            "zone_hit": False,
            "zone_name": "",
            "timestamp": _now_text(),
        }
        self._previous_signal_handlers = {}

    def start(self):
        """启动 Socket 服务。

        返回值：
        - `True`：成功启动
        - `False`：启动失败

        流程：
        1. 如果服务已经运行，直接返回；
        2. 优先尝试 Unix Domain Socket；
        3. 如果平台不支持 AF_UNIX，就转 TCP；
        4. 创建监听 socket；
        5. 启动后台服务线程；
        6. 等待客户端连接。
        """
        if self.running.is_set():
            return True
        try:
            if not hasattr(socket, "AF_UNIX"):
                _socket_log("AF_UNIX is not supported on this platform; using TCP fallback")
                return self._start_tcp()

            self.sock_path.parent.mkdir(parents=True, exist_ok=True)
            if self.sock_path.exists():
                self.sock_path.unlink()

            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(0.5)
            self.sock.bind(str(self.sock_path))
            self.sock.listen(4)
            self.running.set()
            self.server_thread = threading.Thread(target=self._serve, name="VisionSocketServer", daemon=True)
            self.server_thread.start()
            _socket_log(f"Listening on {self.sock_path}")
            return True
        except Exception as exc:
            _socket_log(f"Failed to start socket server: {exc}")
            self.shutdown()
            return False

    def _start_tcp(self):
        """在不支持 AF_UNIX 的环境下启动 TCP 回退服务。

        说明：
        - Windows 上常常会走这个分支；
        - 这样 UI 和语音模块即使在仿真环境也能访问视觉状态；
        - 协议仍然是 JSON 一行一条，不变。
        """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.settimeout(0.5)
            self.sock.bind((self.tcp_host, self.tcp_port))
            self.sock.listen(4)

            self.running.set()
            self.server_thread = threading.Thread(
                target=self._serve,
                name="VisionTcpSocketServer",
                daemon=True,
            )
            self.server_thread.start()
            _socket_log(f"Listening on tcp://{self.tcp_host}:{self.tcp_port}")
            return True
        except Exception as exc:
            _socket_log(f"Failed to start TCP socket server: {exc}")
            self.shutdown()
            return False

    def install_signal_handlers(self):
        """安装信号处理函数。

        作用：
        - 让 Ctrl+C、SIGTERM 等退出信号可以优雅关闭 socket 服务。
        """
        try:
            signals = [signal.SIGINT]
            if hasattr(signal, "SIGTERM"):
                signals.append(signal.SIGTERM)
            for sig in signals:
                self._previous_signal_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle_signal)
        except Exception as exc:
            _socket_log(f"Signal cleanup handlers not installed: {exc}")

    def update_status(self, result_dict):
        """更新最新状态缓存。

        参数：
        - `result_dict`：视觉主循环算出来的最新结果

        返回值：
        - 规范化后的结果字典

        作用：
        - 把最新视觉状态存到 `latest_result`；
        - 之后外部查询 `get_status` 时就直接返回它。
        """
        normalized = self._normalize_result(result_dict)
        with self.lock:
            self.latest_result = normalized
        return normalized

    def send_result(self, result_dict):
        """把最新状态主动推送给已连接客户端。

        说明：
        - `update_status()` 只更新缓存；
        - `send_result()` 在更新缓存后，还会把结果广播给当前连接的客户端；
        - 这样外部程序既可以“问”，也可以“等推送”。
        """
        normalized = self.update_status(result_dict)
        payload = self._encode_message(normalized)
        with self.lock:
            clients = list(self.clients)
        for conn in clients:
            try:
                conn.sendall(payload)
            except Exception:
                self._remove_client(conn)
                self._close_client(conn)
        return bool(clients)

    def get_latest_status(self):
        """获取当前缓存的最新状态。

        返回值：
        - 一个新的字典副本，包含最新视觉状态

        外部查询流程：
        - 客户端发 `{"cmd":"get_status"}`；
        - 服务端直接调用这个函数；
        - 返回缓存，不重新跑视觉推理。
        """
        with self.lock:
            return dict(self.latest_result)

    def shutdown(self):
        """关闭 Socket 服务。

        流程：
        1. 设置停止标志；
        2. 关闭监听 socket；
        3. 关闭所有客户端连接；
        4. 等待服务线程退出；
        5. 删除 Unix Socket 文件。

        作用：
        - 确保程序退出时不会留下脏 socket 文件或半开连接。
        """
        self.shutdown_requested.set()
        self.running.clear()
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        with self.lock:
            clients = list(self.clients)
            self.clients.clear()
        for conn in clients:
            self._close_client(conn)

        if self.server_thread is not None and self.server_thread.is_alive() and threading.current_thread() is not self.server_thread:
            self.server_thread.join(timeout=1)

        try:
            if self.sock_path.exists():
                self.sock_path.unlink()
        except Exception as exc:
            _socket_log(f"Failed to remove socket file: {exc}")

    def _serve(self):
        """服务端主循环。

        这是 Socket 服务真正“等客户端连接”的地方。
        它会一直 accept 新连接，然后为每个客户端启动一个处理线程。
        """
        while self.running.is_set():
            try:
                conn, _addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self.lock:
                self.clients.append(conn)
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
        _socket_log("Server thread exited")

    def _handle_client(self, conn):
        """处理单个客户端连接。

        通信流程：
        1. 客户端连上来；
        2. 服务端不断读取字节流；
        3. 字节流按 `\n` 分隔成一条条 JSON 命令；
        4. 每条命令交给 `_drain_command_buffer()` / `_process_command_text()`。
        """
        buffer = ""
        try:
            conn.settimeout(0.5)
            while self.running.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buffer += data.decode("utf-8", errors="replace")
                buffer = self._drain_command_buffer(conn, buffer)
        finally:
            self._remove_client(conn)
            self._close_client(conn)

    def _drain_command_buffer(self, conn, buffer):
        """把字节缓冲区里的完整 JSON 命令逐条取出来。

        为什么要有这个函数：
        - socket 接收的是字节流，不保证一次 recv 就是一条完整命令；
        - 所以要自己按换行符拆包。
        """
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if line:
                self._process_command_text(conn, line)

        stripped = buffer.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                pass
            else:
                self._process_command_text(conn, stripped)
                return ""

        if len(buffer) > MAX_BUFFER_SIZE:
            self._send_ack(conn, False, "invalid", "Command buffer too large")
            return ""
        return buffer

    def _process_command_text(self, conn, text):
        """解析一条 JSON 命令并执行。

        支持的命令：
        - `trigger_inspection`：触发一次巡检保存；
        - `get_status`：获取当前视觉状态；
        - `reload_config`：通知视觉主流程重新加载配置；
        - `shutdown`：关闭服务。

        返回值：
        - 无直接返回，通过 socket 给客户端发 JSON 响应。
        """
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            self._send_ack(conn, False, "invalid", f"Invalid JSON: {exc}")
            return

        if not isinstance(payload, dict):
            self._send_ack(conn, False, "invalid", "Command must be a JSON object")
            return

        cmd = payload.get("cmd")
        if cmd == "trigger_inspection":
            result = self._notify_command(cmd, payload)
            if isinstance(result, dict):
                if "status" in result:
                    self.update_status(result)
                self._send_to_conn(conn, result)
            else:
                latest_status = self.get_latest_status()
                latest_status.update(
                    {
                        "ack": True,
                        "cmd": cmd,
                        "message": "Inspection trigger accepted",
                        "timestamp": _now_text(),
                    }
                )
                self._send_to_conn(conn, latest_status)
            return
        if cmd == "get_status":
            self._send_to_conn(conn, self.get_latest_status())
            return
        if cmd == "reload_config":
            # UI 保存阈值配置后会发送这个命令。
            # 这里的原理是“先通知、后处理”：socket 层只负责把命令转发给上层，
            # 真正去重新读取 config.json 的动作，通常由仿真器或视觉主循环完成。
            # 这样做可以把通信层和业务层分开，结构更清楚。
            result = self._notify_command(cmd, payload)
            if isinstance(result, dict):
                self._send_to_conn(conn, result)
            else:
                self._send_ack(conn, True, cmd, "Reload config accepted")
            return
        if cmd == "shutdown":
            self._notify_command(cmd, payload)
            self._send_ack(conn, True, cmd, "Shutdown accepted")
            self.shutdown()
            return
        self._send_ack(conn, False, str(cmd), "Unknown command")

    def _notify_command(self, cmd, payload):
        """把命令转发给上层业务回调。

        说明：
        - Socket 层只负责通信，不负责具体业务动作；
        - 真正的业务由 `command_callback` 在视觉主循环或仿真器里处理；
        - 这样通信层和业务层解耦，后期更容易维护。
        """
        if self.command_callback is None:
            return None
        try:
            return self.command_callback(cmd, payload)
        except Exception as exc:
            _socket_log(f"Command callback failed: {exc}")
            return {
                "ack": False,
                "cmd": cmd,
                "status": "UNKNOWN",
                "person_count": 0,
                "reason": f"Command callback failed: {exc}",
                "timestamp": _now_text(),
            }

    def _send_ack(self, conn, ok, cmd, message):
        """给客户端发送标准确认消息。

        参数：
        - `ok`：是否成功
        - `cmd`：对应命令名
        - `message`：说明文本
        """
        self._send_to_conn(conn, {"ack": bool(ok), "cmd": cmd, "message": message, "timestamp": _now_text()})

    def _send_to_conn(self, conn, payload):
        """把 JSON 响应发送给当前连接的客户端。

        返回值：
        - `True`：发送成功
        - `False`：发送失败
        """
        try:
            conn.sendall(self._encode_message(payload))
            return True
        except Exception:
            return False

    def _encode_message(self, payload):
        """把 Python 字典编码成一行 JSON 字节串。

        规则：
        - 中文不转义，便于调试；
        - 末尾追加 `\n`，方便客户端按行读取。
        """
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    def _normalize_result(self, result_dict):
        """把外部传入的结果补齐成统一结构。

        为什么要做这一步：
        - 不同来源传来的结果字段不一定完整；
        - 统一补默认值后，UI、语音和 C 主控就更容易处理。
        """
        result = dict(result_dict or {})
        result.setdefault("status", "UNKNOWN")
        result.setdefault("person_count", 0)
        result.setdefault("reason", "")
        result.setdefault("alarm_type", "")
        result.setdefault("alarm_reason", "")
        result.setdefault("zone_hit", False)
        result.setdefault("zone_name", "")
        result.setdefault("timestamp", _now_text())
        if result.get("status") == "ALARM" and not result.get("alarm_reason"):
            result["alarm_reason"] = result.get("reason") or "视觉检测到报警"
        if result.get("status") != "ALARM":
            result["alarm_type"] = ""
            result["alarm_reason"] = ""
        return result

    def _remove_client(self, conn):
        """从客户端列表里移除断开的连接。"""
        with self.lock:
            if conn in self.clients:
                self.clients.remove(conn)

    def _close_client(self, conn):
        """关闭客户端连接，忽略关闭异常。"""
        try:
            conn.close()
        except Exception:
            pass

    def _handle_signal(self, signum, frame):
        """信号响应函数，用于优雅退出。"""
        _socket_log(f"Received signal {signum}, shutting down")
        self._notify_command("shutdown", {"cmd": "shutdown", "signal": signum})
        self.shutdown()
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(0)
