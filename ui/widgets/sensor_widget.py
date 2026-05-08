"""sensor_widget.py

传感器数值显示组件。

作用：
1. 显示环境温度、湿度、电流、设备温度、烟雾；
2. 根据阈值显示正常 / 预警 / 超标；
3. 以深色工业风展示，便于远距离查看。

硬件依赖：
- alarm_log.csv
- rk3588/config.json

作者：Cursor
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from data.ui_state import UIState


class SensorWidget(QWidget):
    """传感器数值面板。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state
        self.title = QLabel("传感器数值")
        self.title.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")

        self.info = QLabel("")
        self.info.setAlignment(Qt.AlignTop)
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: white; font-size: 16px;")

        layout = QVBoxLayout()
        layout.addWidget(self.title)
        layout.addWidget(self.info)
        self.setLayout(layout)
        self.setStyleSheet("background-color: #16213e; border-radius: 8px;")

    def refresh(self):
        """刷新显示内容。"""
        th = self.uiState.threshold
        lines = []
        lines.append(self._formatLine("环境温度", f"{self.uiState.temperature:.1f} °C", f"上限 {th.get('temp_max', 60)} °C", self.uiState.temperature, th.get("temp_max", 60), high_is_bad=True))
        lines.append(self._formatLine("环境湿度", f"{self.uiState.humidity:.1f} %", f"范围 {th.get('humidity_min', 20)}~{th.get('humidity_max', 80)} %", self.uiState.humidity, th.get("humidity_max", 80), high_is_bad=True))
        lines.append(self._formatLine("电    流", f"{self.uiState.current:.1f} A", f"上限 {th.get('current_max', 10)} A", self.uiState.current, th.get("current_max", 10), high_is_bad=True))
        lines.append(self._formatLine("设备温度", f"{self.uiState.temp_device:.1f} °C", f"上限 {th.get('temp_device_max', 80)} °C", self.uiState.temp_device, th.get("temp_device_max", 80), high_is_bad=True))
        smokeText = "正常" if self.uiState.smoke == 0 else ("预警" if self.uiState.smoke == 1 else "报警")
        smokeColor = self._getStateColor(0 if self.uiState.smoke == 0 else 1 if self.uiState.smoke == 1 else 2)
        lines.append(f"<span style='color:{smokeColor};'>烟    雾    {smokeText}</span>")
        self.info.setText("<br>".join(lines))

    def _formatLine(self, name, value, thresholdText, currentValue, thresholdValue, high_is_bad=False):
        """生成一行传感器显示文本。"""
        ratio = 0
        try:
            ratio = float(currentValue) / float(thresholdValue) if thresholdValue else 0
        except Exception:
            ratio = 0

        state = "正常"
        color = self._getStateColor(0)
        if ratio >= 1.0:
            state = "超标"
            color = self._getStateColor(2)
        elif ratio >= 0.8:
            state = "接近阈值"
            color = self._getStateColor(1)

        return f"<span style='color:{color};'>{name}    {value}    ● {state}    <small>({thresholdText})</small></span>"

    def _getStateColor(self, level):
        if level == 2:
            return "#e94560"
        if level == 1:
            return "#f0a500"
        return "#ffffff"
