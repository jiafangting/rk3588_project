"""阈值滑块配置组件。

设置页使用这个组件写入 `rk3588/config.json`。
滑块比输入框更适合新手调参：不会输错格式，也能直观看到当前范围。
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget

from data.ui_state import DEFAULT_THRESHOLD, UIState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_APP_DIR = PROJECT_ROOT / "vision" / "app"
if str(VISION_APP_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_APP_DIR))

from socket_config import get_vision_socket_path


CONFIG_PATH = PROJECT_ROOT / "rk3588" / "config.json"
VISION_SOCKET_PATH = get_vision_socket_path()
VISION_TCP_HOST = "127.0.0.1"
VISION_TCP_PORT = 8765
CONTROL_SOCKET_PATH = os.environ.get("INSPECTION_CONTROL_SOCKET_PATH", "/tmp/inspection_control.sock")


class SliderRow(QWidget):
    """一行滑块配置。"""

    def __init__(self, title, key, minimum, maximum, unit, parent=None):
        super().__init__(parent)
        self.key = key
        self.unit = unit
        self.title = QLabel(title)
        self.keyLabel = QLabel(key)
        self.valueLabel = QLabel("--")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.valueChanged.connect(self.update_value_label)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.title)
        left.addWidget(self.keyLabel)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 12, 18, 12)
        row.addLayout(left, 1)
        row.addWidget(self.slider, 3)
        row.addWidget(self.valueLabel)

        self.title.setStyleSheet("color:#c8d8f0; font-size:16px; font-weight:bold;")
        self.keyLabel.setStyleSheet("color:#5a80a0; font-size:12px; font-family:Consolas, Courier New;")
        self.valueLabel.setMinimumWidth(72)
        self.valueLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.valueLabel.setStyleSheet("color:#4fc3f7; font-size:17px; font-weight:bold;")
        self.slider.setStyleSheet(
            """
            QSlider::groove:horizontal {
                height:4px;
                background:#0f1e30;
                border-radius:2px;
            }
            QSlider::handle:horizontal {
                width:18px;
                height:18px;
                margin:-8px 0;
                border-radius:9px;
                background:#4fc3f7;
            }
            """
        )

    def update_value_label(self):
        self.valueLabel.setText(f"{self.slider.value():g}{self.unit}")

    def value(self):
        return float(self.slider.value())

    def set_value(self, value):
        self.slider.setValue(int(float(value)))
        self.update_value_label()


class ThresholdWidget(QWidget):
    """阈值配置面板。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state
        self.rows = {
            "temp_max": SliderRow("环境温度上限", "temp_max", 0, 100, "°C"),
            "humidity_min": SliderRow("环境湿度下限", "humidity_min", 0, 100, "%"),
            "humidity_max": SliderRow("环境湿度上限", "humidity_max", 0, 100, "%"),
            "voltage_min": SliderRow("电压下限", "voltage_min", 180, 240, "V"),
            "voltage_max": SliderRow("电压上限", "voltage_max", 220, 260, "V"),
            "current_max": SliderRow("电流上限", "current_max", 1, 30, "A"),
            "temp_device_max": SliderRow("设备温度上限", "temp_device_max", 20, 120, "°C"),
        }
        self.smokeCheck = QCheckBox("启用烟雾报警")
        self.smokeCheck.setStyleSheet("color:#c8d8f0; font-size:15px; padding:12px 18px;")

        title = QLabel("• 传感器阈值")
        title.setStyleSheet("color:#8fcaff; font-size:18px; font-weight:bold; padding:12px 18px;")

        self.saveButton = QPushButton("保存配置")
        self.resetButton = QPushButton("恢复默认")
        self.saveButton.clicked.connect(self.saveConfig)
        self.resetButton.clicked.connect(self.resetDefault)
        for button in (self.saveButton, self.resetButton):
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                """
                QPushButton {
                    background:#10243a;
                    color:#4fc3f7;
                    border:1px solid #1e2d4a;
                    border-radius:8px;
                    padding:10px 18px;
                    font-weight:bold;
                }
                QPushButton:hover {
                    border-color:#4fc3f7;
                }
                """
            )

        buttonRow = QHBoxLayout()
        buttonRow.setContentsMargins(18, 14, 18, 18)
        buttonRow.addWidget(self.resetButton)
        buttonRow.addStretch(1)
        buttonRow.addWidget(self.saveButton)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(title)
        for row in self.rows.values():
            layout.addWidget(row)
        layout.addWidget(self.smokeCheck)
        layout.addStretch(1)
        layout.addLayout(buttonRow)

        self.setStyleSheet("background:#0d1220; border:1px solid #1e2d4a; border-radius:8px;")
        self.loadFromConfig()

    def loadFromConfig(self):
        """从 config.json 读取阈值。"""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = dict(DEFAULT_THRESHOLD)

        for key, row in self.rows.items():
            row.set_value(data.get(key, DEFAULT_THRESHOLD.get(key, 0)))
        self.smokeCheck.setChecked(bool(data.get("smoke_alarm", 1)))

    def collect_data(self):
        """把滑块值整理成配置字典。"""
        data = {key: row.value() for key, row in self.rows.items()}
        data["smoke_alarm"] = 1 if self.smokeCheck.isChecked() else 0
        return data

    def saveConfig(self):
        """保存阈值配置。"""
        data = self.collect_data()
        if data["humidity_min"] > data["humidity_max"]:
            QMessageBox.warning(self, "输入错误", "湿度下限不能大于湿度上限")
            return
        if data["voltage_min"] > data["voltage_max"]:
            QMessageBox.warning(self, "输入错误", "电压下限不能大于电压上限")
            return

        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.uiState.threshold = data
        self._sendReloadConfig()
        QMessageBox.information(self, "保存成功", "配置已保存，主控或仿真后端会重新读取")

    def resetDefault(self):
        """恢复默认阈值。"""
        for key, row in self.rows.items():
            row.set_value(DEFAULT_THRESHOLD[key])
        self.smokeCheck.setChecked(bool(DEFAULT_THRESHOLD["smoke_alarm"]))
        self.saveConfig()

    def _sendReloadConfig(self):
        """通知 C 主控优先重载配置；没有主控时回退通知仿真后端。"""
        payload = b'{"cmd":"reload_config"}\n'
        if self._sendUnixCommand(CONTROL_SOCKET_PATH, payload):
            return

        # 软件仿真仍复用视觉 socket，所以 C 主控不在线时保留这个回退。
        self._sendVisionReloadFallback(payload)

    def _sendUnixCommand(self, socket_path, payload):
        if not hasattr(socket, "AF_UNIX"):
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                sock.connect(socket_path)
                sock.sendall(payload)
                try:
                    response = sock.recv(1024)
                except Exception:
                    response = b""
            return b'"ack":true' in response or b'"ack": true' in response
        except Exception:
            return False

    def _sendVisionReloadFallback(self, payload):
        try:
            if hasattr(socket, "AF_UNIX"):
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                        sock.settimeout(1.0)
                        sock.connect(VISION_SOCKET_PATH)
                        sock.sendall(payload)
                        return
                except Exception:
                    pass
            with socket.create_connection((VISION_TCP_HOST, VISION_TCP_PORT), timeout=1.0) as sock:
                sock.sendall(payload)
        except Exception:
            pass
