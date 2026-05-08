"""Unix Domain Socket interface for the Python vision module."""

from datetime import datetime
import json
from pathlib import Path
import signal
import socket
import threading


DEFAULT_SOCKET_PATH = "/tmp/vision_inspection.sock"
DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 8765
MAX_BUFFER_SIZE = 64 * 1024


def _now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _socket_log(message):
    print(f"[SOCKET] {message}")


class VisionSocketServer:
    """Background socket server used by the C main controller."""

    def __init__(self, sock_path=DEFAULT_SOCKET_PATH, command_callback=None, tcp_host=DEFAULT_TCP_HOST, tcp_port=DEFAULT_TCP_PORT):
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
            "timestamp": _now_text(),
        }
        self._previous_signal_handlers = {}

    def start(self):
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
        normalized = self._normalize_result(result_dict)
        with self.lock:
            self.latest_result = normalized
        return normalized

    def send_result(self, result_dict):
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
        with self.lock:
            return dict(self.latest_result)

    def shutdown(self):
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
            self._notify_command(cmd, payload)
            self._send_ack(conn, True, cmd, "Inspection trigger accepted")
            return
        if cmd == "get_status":
            self._send_to_conn(conn, self.get_latest_status())
            return
        if cmd == "shutdown":
            self._notify_command(cmd, payload)
            self._send_ack(conn, True, cmd, "Shutdown accepted")
            self.shutdown()
            return
        self._send_ack(conn, False, str(cmd), "Unknown command")

    def _notify_command(self, cmd, payload):
        if self.command_callback is None:
            return
        try:
            self.command_callback(cmd, payload)
        except Exception as exc:
            _socket_log(f"Command callback failed: {exc}")

    def _send_ack(self, conn, ok, cmd, message):
        self._send_to_conn(conn, {"ack": bool(ok), "cmd": cmd, "message": message, "timestamp": _now_text()})

    def _send_to_conn(self, conn, payload):
        try:
            conn.sendall(self._encode_message(payload))
            return True
        except Exception:
            return False

    def _encode_message(self, payload):
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    def _normalize_result(self, result_dict):
        result = dict(result_dict or {})
        result.setdefault("status", "UNKNOWN")
        result.setdefault("person_count", 0)
        result.setdefault("reason", "")
        result.setdefault("timestamp", _now_text())
        return result

    def _remove_client(self, conn):
        with self.lock:
            if conn in self.clients:
                self.clients.remove(conn)

    def _close_client(self, conn):
        try:
            conn.close()
        except Exception:
            pass

    def _handle_signal(self, signum, frame):
        _socket_log(f"Received signal {signum}, shutting down")
        self._notify_command("shutdown", {"cmd": "shutdown", "signal": signum})
        self.shutdown()
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(0)
