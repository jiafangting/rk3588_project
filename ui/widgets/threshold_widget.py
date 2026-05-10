"""threshold_widget.py

阈值配置组件。

作用：
1. 显示和编辑系统阈值；
2. 读取 rk3588/config.json；
3. 保存后通知主程序热更新；
4. 支持恢复默认值。

硬件依赖：
- rk3588/config.json
- RK3588 主进程的 reload_config socket 指令

作者：Cursor
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data.ui_state import DEFAULT_THRESHOLD, UIState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_APP_DIR = PROJECT_ROOT / "vision" / "app"
if str(VISION_APP_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_APP_DIR))

from socket_config import get_vision_socket_path


CONFIG_PATH = PROJECT_ROOT / "rk3588" / "config.json"
VISION_SOCKET_PATH = get_vision_socket_path()


class ThresholdWidget(QWidget):
    """阈值配置面板。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state

        self.tempMaxEdit = QLineEdit()
        self.humidityMinEdit = QLineEdit()
        self.humidityMaxEdit = QLineEdit()
        self.currentMaxEdit = QLineEdit()
        self.tempDeviceMaxEdit = QLineEdit()
        self.smokeCheck = QCheckBox("启用")

        form = QFormLayout()
        form.addRow("温度上限 (°C)", self.tempMaxEdit)
        form.addRow("湿度下限 (%)", self.humidityMinEdit)
        form.addRow("湿度上限 (%)", self.humidityMaxEdit)
        form.addRow("电流上限 (A)", self.currentMaxEdit)
        form.addRow("设备温度上限 (°C)", self.tempDeviceMaxEdit)
        form.addRow("烟雾报警", self.smokeCheck)

        self.saveButton = QPushButton("保存配置")
        self.resetButton = QPushButton("恢复默认")
        self.saveButton.clicked.connect(self.saveConfig)
        self.resetButton.clicked.connect(self.resetDefault)

        btnRow = QHBoxLayout()
        btnRow.addWidget(self.saveButton)
        btnRow.addWidget(self.resetButton)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(btnRow)
        self.setLayout(layout)
        self.setStyleSheet("background-color: #16213e; border-radius: 8px; color: white;")

        self.loadFromConfig()

    def loadFromConfig(self):
        """启动时从 config.json 读取阈值。"""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = dict(DEFAULT_THRESHOLD)

        self.tempMaxEdit.setText(str(data.get("temp_max", 60.0)))
        self.humidityMinEdit.setText(str(data.get("humidity_min", 20.0)))
        self.humidityMaxEdit.setText(str(data.get("humidity_max", 80.0)))
        self.currentMaxEdit.setText(str(data.get("current_max", 10.0)))
        self.tempDeviceMaxEdit.setText(str(data.get("temp_device_max", 80.0)))
        self.smokeCheck.setChecked(bool(data.get("smoke_alarm", 1)))

    def saveConfig(self):
        """保存阈值配置。"""
        try:
            data = {
                "temp_max": float(self.tempMaxEdit.text()),
                "humidity_min": float(self.humidityMinEdit.text()),
                "humidity_max": float(self.humidityMaxEdit.text()),
                "current_max": float(self.currentMaxEdit.text()),
                "temp_device_max": float(self.tempDeviceMaxEdit.text()),
                "smoke_alarm": 1 if self.smokeCheck.isChecked() else 0,
            }
        except Exception:
            QMessageBox.warning(self, "输入错误", "请检查输入值是否为合法数字")
            return

        if data["humidity_min"] > data["humidity_max"]:
            QMessageBox.warning(self, "输入错误", "湿度下限不能大于湿度上限")
            return

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.uiState.threshold = data
        self._sendReloadConfig()
        QMessageBox.information(self, "保存成功", "配置已保存，重启主程序后生效")

    def resetDefault(self):
        """恢复默认值并保存。"""
        self.tempMaxEdit.setText(str(DEFAULT_THRESHOLD["temp_max"]))
        self.humidityMinEdit.setText(str(DEFAULT_THRESHOLD["humidity_min"]))
        self.humidityMaxEdit.setText(str(DEFAULT_THRESHOLD["humidity_max"]))
        self.currentMaxEdit.setText(str(DEFAULT_THRESHOLD["current_max"]))
        self.tempDeviceMaxEdit.setText(str(DEFAULT_THRESHOLD["temp_device_max"]))
        self.smokeCheck.setChecked(bool(DEFAULT_THRESHOLD["smoke_alarm"]))
        self.saveConfig()

    def _sendReloadConfig(self):
        """通知主程序热更新配置。"""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                sock.connect(VISION_SOCKET_PATH)
                # 配置保存后只发一条 reload_config 指令。
                # 这里使用统一的 VISION_SOCKET_PATH，避免 UI 写完 config.json 后
                # 通知了旧 socket，导致视觉服务端没有收到热更新请求。
                sock.sendall(b'{"cmd":"reload_config"}\n')
        except Exception:
            pass
