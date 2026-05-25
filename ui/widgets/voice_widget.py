"""语音助手对话面板。

这个组件不负责录音，也不负责语音识别。
它只做一件事：读取 voice_loop.py 写出的共享 JSON 文件，
把最近的用户输入和“小杜”回复显示成对话气泡。
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VOICE_EXCHANGE_PATH = PROJECT_ROOT / ".tmp" / "voice_last_exchange.json"


class VoiceWidget(QWidget):
    """语音助手对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.messages = []
        self.seen_keys = set()

        self.title = QLabel("• 语音助手 · 小杜")
        self.title.setStyleSheet("color:#8fcaff; font-size:18px; font-weight:bold; padding:10px 14px;")

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setStyleSheet(
            """
            QTextBrowser {
                background:#0d1220;
                border:0;
                color:#c8d8f0;
                font-size:15px;
                padding:10px;
            }
            QScrollBar:vertical {
                background:#0d1220;
                width:8px;
            }
            QScrollBar::handle:vertical {
                background:#1e2d4a;
                border-radius:4px;
            }
            """
        )

        self.micButton = QPushButton("麦")
        self.micButton.setFixedSize(34, 34)
        self.micButton.setStyleSheet(
            """
            QPushButton {
                border:1px solid #4fc3f7;
                border-radius:17px;
                color:#4fc3f7;
                background:#10243a;
                font-weight:bold;
            }
            """
        )
        self.tipLabel = QLabel("\"小杜你好\" 唤醒 · 停止/退出 结束对话")
        self.tipLabel.setStyleSheet("color:#5a80a0; font-size:14px;")

        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 8, 14, 12)
        bottom.addWidget(self.micButton)
        bottom.addWidget(self.tipLabel)
        bottom.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title)
        layout.addWidget(self.browser, 1)
        layout.addLayout(bottom)

        self.setStyleSheet(
            """
            VoiceWidget {
                background:#0d1220;
                border:1px solid #1e2d4a;
                border-radius:8px;
            }
            """
        )

        self.add_message("bot", "语音模块启动后，我会在这里显示对话。")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read_shared_exchange)
        self.timer.start(500)

    def add_message(self, role: str, text: str):
        """追加一条对话消息。

        role 只认两种：
        - user：用户输入，右侧蓝色气泡；
        - bot：小杜回复，左侧深色气泡。
        """
        role = "user" if role == "user" else "bot"
        text = str(text or "").strip()
        if not text:
            return
        self.messages.append({"role": role, "text": text})
        self.render_messages()

    def clear(self):
        """清空对话记录。"""
        self.messages.clear()
        self.seen_keys.clear()
        self.render_messages()

    def read_shared_exchange(self):
        """读取 voice_loop.py 写出的最近一轮对话。"""
        if not VOICE_EXCHANGE_PATH.exists():
            return

        try:
            with open(VOICE_EXCHANGE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        if data.get("event") == "clear":
            self.clear()
            return

        messages = data.get("messages")
        if not isinstance(messages, list):
            messages = [data]

        for message in messages:
            role = str(message.get("role", "")).strip()
            text = str(message.get("text", "")).strip()
            timestamp = str(message.get("timestamp", "")).strip()
            key = (timestamp, role, text)
            if not timestamp or key in self.seen_keys:
                continue
            self.seen_keys.add(key)
            self.add_message(role, text)

    def render_messages(self):
        """把内存里的消息列表渲染成 HTML 气泡。"""
        html_parts = [
            "<div style='font-family:Microsoft YaHei, SimHei, sans-serif; font-size:15px;'>",
        ]
        for message in self.messages[-30:]:
            role = message["role"]
            text = html.escape(message["text"])
            if role == "user":
                html_parts.append(
                    "<div style='text-align:right; margin:8px 0;'>"
                    "<span style='display:inline-block; max-width:72%; padding:9px 12px; "
                    "border-radius:12px; background:#123c6a; border:1px solid #1d68a8; color:#c8d8f0;'>"
                    f"{text}</span></div>"
                )
            else:
                html_parts.append(
                    "<div style='text-align:left; margin:8px 0;'>"
                    "<span style='display:inline-block; max-width:76%; padding:9px 12px; "
                    "border-radius:12px; background:#101d2c; border:1px solid #1e2d4a; color:#c8d8f0;'>"
                    f"<b style='color:#1de498;'>小杜</b><br>{text}</span></div>"
                )
        html_parts.append("</div>")
        self.browser.setHtml("".join(html_parts))
        self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().maximum())
