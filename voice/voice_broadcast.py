"""通用语音播报模块。

这个文件给视觉模块、语音助手、测试脚本共用。

特点：
    1. 后台队列播报，不阻塞主流程；
    2. 优先使用 pyttsx3；
    3. pyttsx3 / sapi5 失败时，自动使用 PowerShell System.Speech 兜底。
"""

import queue
import subprocess
import threading
from pathlib import Path
import json
import socket

import pyttsx3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TTS_ACTIVE_FLAG = PROJECT_ROOT / ".tmp" / "tts_active.flag"
DEFAULT_TTS_HOST = "127.0.0.1"
DEFAULT_TTS_PORT = 8766


def is_tts_active():
    """Return whether any system TTS is currently speaking.

    The flag is intentionally file based so independent processes can see it.
    The voice recorder checks this flag before and during recording to avoid
    recording the speaker output and feeding it back into ASR.
    """
    return TTS_ACTIVE_FLAG.exists()


def _set_tts_active(active):
    TTS_ACTIVE_FLAG.parent.mkdir(parents=True, exist_ok=True)
    if active:
        TTS_ACTIVE_FLAG.write_text("active", encoding="utf-8")
        return
    try:
        TTS_ACTIVE_FLAG.unlink(missing_ok=True)
    except Exception:
        pass


def request_tts(text, host=DEFAULT_TTS_HOST, port=DEFAULT_TTS_PORT, timeout=1.0):
    """Ask the voice process to speak text.

    Visual code calls this before falling back to local pyttsx3. When the voice
    process is running, all TTS goes through one VoiceBroadcaster queue, so the
    voice loop can wait for it before opening the microphone.
    """
    if not text:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            payload = json.dumps({"cmd": "speak", "text": str(text)}, ensure_ascii=False) + "\n"
            sock.sendall(payload.encode("utf-8"))
            sock.settimeout(timeout)
            data = sock.recv(1024)
        if not data:
            return False
        result = json.loads(data.decode("utf-8", errors="replace").strip())
        return bool(result.get("ok"))
    except Exception:
        return False


class TTSRequestServer:
    """Small TCP server that lets other processes request voice playback."""

    def __init__(self, broadcaster, host=DEFAULT_TTS_HOST, port=DEFAULT_TTS_PORT):
        self.broadcaster = broadcaster
        self.host = host
        self.port = port
        self._sock = None
        self._thread = None
        self._running = threading.Event()

    def start(self):
        if self._running.is_set():
            return True
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self.host, self.port))
            self._sock.listen(4)
            self._sock.settimeout(0.5)
            self._running.set()
            self._thread = threading.Thread(target=self._serve, name="TTSRequestServer", daemon=True)
            self._thread.start()
            print(f"[TTS-BUS] listening on tcp://{self.host}:{self.port}")
            return True
        except Exception as exc:
            print(f"[TTS-BUS] start failed: {exc}")
            self.stop()
            return False

    def stop(self):
        self._running.clear()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _serve(self):
        while self._running.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn):
        with conn:
            try:
                data = conn.recv(4096)
                payload = json.loads(data.decode("utf-8", errors="replace").strip())
                if payload.get("cmd") != "speak":
                    self._send(conn, False, "unknown command")
                    return
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._send(conn, False, "empty text")
                    return
                self.broadcaster.speak(text)
                self._send(conn, True, "queued")
            except Exception as exc:
                self._send(conn, False, str(exc))

    def _send(self, conn, ok, message):
        raw = json.dumps({"ok": bool(ok), "message": message}, ensure_ascii=False).encode("utf-8")
        conn.sendall(raw)


class VoiceBroadcaster:
    """后台语音播报器。"""

    def __init__(self, rate=180, volume=1.0):
        self.rate = rate
        self.volume = volume
        self._queue = queue.Queue()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, name="VoiceBroadcaster", daemon=True)
        self._thread.start()

    def speak(self, text):
        if text:
            self._queue.put(str(text))

    def stop(self):
        """等待已排队播报全部完成，再关闭线程。"""
        self._queue.put(None)
        self._queue.join()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def wait_until_done(self):
        """等待已排队播报全部完成，但不关闭线程。主循环在开麦前调用，避免喇叭声被麦克风录回去。"""
        self._queue.join()

    def _worker(self):
        while True:
            text = self._queue.get()
            try:
                if text is None:
                    break
                self._speak_once(text)
            finally:
                self._queue.task_done()

    def _speak_once(self, text):
        engine = None
        try:
            _set_tts_active(True)
            print(f"[VOICE] {text}")
            engine = pyttsx3.init("sapi5")
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            print(f"[VOICE] pyttsx3 播报失败，改用 PowerShell：{exc}")
            self._speak_with_powershell(text)
        finally:
            try:
                if engine is not None:
                    engine.stop()
            except Exception:
                pass
            _set_tts_active(False)

    def _speak_with_powershell(self, text):
        safe_text = str(text).replace("'", "''")
        ps_script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = 0; "
            "$s.Volume = 100; "
            f"$s.Speak('{safe_text}'); "
            "$s.Dispose()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=False)


def speak_once(text, rate=180, volume=1.0):
    """同步播报一句话，适合测试脚本使用。"""
    broadcaster = VoiceBroadcaster(rate=rate, volume=volume)
    broadcaster.start()
    broadcaster.speak(text)
    broadcaster.stop()
