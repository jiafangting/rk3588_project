"""传感器数值显示组件。

每个传感器单独一行：
- 左侧是名称；
- 右侧是实时数值；
- 下方是一条 3px 高的进度条；
- 超标时显示超出量，方便快速定位问题。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from data.ui_state import UIState


COLOR_NORMAL = "#1de498"
COLOR_WARN = "#ffb020"
COLOR_ALARM = "#ff5050"
COLOR_TEXT = "#c8d8f0"
COLOR_MUTED = "#5a80a0"


class SensorRow(QWidget):
    """单个传感器行。"""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.nameLabel = QLabel(name)
        self.valueLabel = QLabel("--")
        self.extraLabel = QLabel("")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.nameLabel)
        top.addStretch(1)
        top.addWidget(self.valueLabel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(5)
        layout.addLayout(top)
        layout.addWidget(self.progress)
        layout.addWidget(self.extraLabel)

        self.nameLabel.setStyleSheet(f"color:{COLOR_MUTED}; font-size:15px; font-weight:bold;")
        self.valueLabel.setStyleSheet(f"color:{COLOR_TEXT}; font-size:18px; font-weight:bold;")
        self.extraLabel.setStyleSheet(f"color:{COLOR_MUTED}; font-size:12px;")
        self.setStyleSheet("border-bottom:1px solid #14233a;")

    def update_value(self, value_text: str, threshold_text: str, percent: int, level: int, exceed_text: str = ""):
        """更新本行显示。

        level:
        - 0：正常，绿色；
        - 1：接近阈值，橙色；
        - 2：超标，红色。
        """
        color = COLOR_NORMAL
        state = "正常"
        if level == 1:
            color = COLOR_WARN
            state = "接近阈值"
        elif level == 2:
            color = COLOR_ALARM
            state = "超标"

        self.valueLabel.setText(value_text)
        self.valueLabel.setStyleSheet(f"color:{color}; font-size:18px; font-weight:bold;")
        extra = f"{threshold_text}"
        if exceed_text:
            extra = f"{threshold_text} · {exceed_text}"
        self.extraLabel.setText(f"{state} · {extra}")
        self.extraLabel.setStyleSheet(f"color:{color if level == 2 else COLOR_MUTED}; font-size:12px;")
        self.progress.setValue(max(0, min(int(percent), 100)))
        self.progress.setStyleSheet(
            f"""
            QProgressBar {{
                background:#0f1e30;
                border:0;
                border-radius:1px;
            }}
            QProgressBar::chunk {{
                background:{color};
                border-radius:1px;
            }}
            """
        )


class SensorWidget(QWidget):
    """传感器数值面板。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state
        self.title = QLabel("• 传感器数值")
        self.title.setStyleSheet("color:#8fcaff; font-size:18px; font-weight:bold; padding:10px 14px;")

        self.rows = {
            "temperature": SensorRow("环境温度"),
            "humidity": SensorRow("环境湿度"),
            "voltage": SensorRow("电    压"),
            "current": SensorRow("电    流"),
            "temp_device": SensorRow("设备温度"),
            "smoke": SensorRow("烟    雾"),
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title)
        for row in self.rows.values():
            layout.addWidget(row)
        layout.addStretch(1)

        self.setStyleSheet("background:#0d1220; border:1px solid #1e2d4a; border-radius:8px;")

    def refresh(self):
        """刷新所有传感器行。"""
        th = self.uiState.threshold
        self._update_max_row(
            "temperature",
            self.uiState.temperature,
            th.get("temp_max", 60),
            "°C",
            "上限",
        )
        self._update_range_row(
            "humidity",
            self.uiState.humidity,
            th.get("humidity_min", 20),
            th.get("humidity_max", 80),
            "%",
        )
        self._update_range_row(
            "voltage",
            self.uiState.voltage,
            th.get("voltage_min", 210),
            th.get("voltage_max", 240),
            "V",
        )
        self._update_max_row(
            "current",
            self.uiState.current,
            th.get("current_max", 10),
            "A",
            "上限",
        )
        self._update_max_row(
            "temp_device",
            self.uiState.temp_device,
            th.get("temp_device_max", 80),
            "°C",
            "上限",
        )
        self._update_smoke_row()

    def _update_max_row(self, key, value, limit, unit, label):
        """处理“越高越危险”的传感器。"""
        value = float(value or 0)
        limit = float(limit or 1)
        ratio = value / limit if limit else 0
        level = 2 if ratio >= 1.0 else 1 if ratio >= 0.8 else 0
        exceed = ""
        if level == 2:
            exceed = f"超标 +{value - limit:.1f}"
        self.rows[key].update_value(
            f"{value:.1f} {unit}",
            f"{label} {limit:g}{unit}",
            int(ratio * 100),
            level,
            exceed,
        )

    def _update_range_row(self, key, value, min_limit, max_limit, unit):
        """处理“必须落在范围内”的传感器。"""
        value = float(value or 0)
        min_limit = float(min_limit or 0)
        max_limit = float(max_limit or 1)
        span = max(max_limit - min_limit, 1.0)
        percent = int((value - min_limit) / span * 100)
        near_edge = value <= min_limit + span * 0.1 or value >= max_limit - span * 0.1
        level = 0
        exceed = ""
        if value < min_limit:
            level = 2
            exceed = f"低于 {min_limit - value:.1f}"
            percent = 0
        elif value > max_limit:
            level = 2
            exceed = f"超标 +{value - max_limit:.1f}"
            percent = 100
        elif near_edge:
            level = 1

        self.rows[key].update_value(
            f"{value:.1f} {unit}",
            f"范围 {min_limit:g}~{max_limit:g}{unit}",
            percent,
            level,
            exceed,
        )

    def _update_smoke_row(self):
        """烟雾是离散值，不按连续阈值算。"""
        smoke = int(self.uiState.smoke or 0)
        level = 2 if smoke else 0
        text = "报警" if smoke else "正常"
        self.rows["smoke"].update_value(text, f"原始值 {smoke}", 100 if smoke else 0, level)
