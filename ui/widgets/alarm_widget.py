"""alarm_widget.py

报警状态组件。

作用：
1. 显示最近 5 条报警记录；
2. 支持清空记录；
3. 报警时边框红色闪烁；
4. 5 秒后停止闪烁但保留历史记录。

硬件依赖：
- alarm_log.csv

作者：Cursor
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QPushButton, QVBoxLayout, QWidget, QLabel

from data.ui_state import UIState


ALARM_LOG_PATH = Path(__file__).resolve().parents[2] / "rk3588" / "alarm_log.csv"


class AlarmWidget(QWidget):
    """报警列表和状态面板。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state
        self.title = QLabel("报警记录")
        self.title.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: white; font-size: 16px;")

        self.clearButton = QPushButton("清空记录")
        self.clearButton.clicked.connect(self.clearRecords)
        self.clearButton.setStyleSheet("background-color:#e94560; color:white; padding:8px; font-size:14px;")

        layout = QVBoxLayout()
        layout.addWidget(self.title)
        layout.addWidget(self.info)
        layout.addWidget(self.clearButton)
        self.setLayout(layout)
        self.setStyleSheet("background-color: #16213e; border-radius: 8px;")

        self.flashState = False
        self.flashStartTime = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

    def refresh(self):
        """刷新最近报警记录。"""
        records = self._loadRecords()
        self.uiState.alarm_records = records

        lines = []
        for idx, row in enumerate(reversed(records[-5:])):
            timeText = row.get("timestamp") or row.get("alarm_time") or "--:--:--"
            reason = row.get("reason") or row.get("alarm_reason") or row.get("alarm_type") or "未知报警"
            prefix = "🔴" if idx == 0 else ("✅" if str(row.get("status", "")) == "NORMAL" else "⚪")
            lines.append(f"{prefix} {timeText}  {reason}")

        if not lines:
            lines = ["当前没有报警记录"]

        self.info.setText("<br>".join(lines))
        self._updateBorder(records)

    def _loadRecords(self):
        """从 CSV 加载记录。"""
        if not ALARM_LOG_PATH.exists():
            return []
        with open(ALARM_LOG_PATH, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def clearRecords(self):
        """清空报警 CSV 文件。"""
        with open(ALARM_LOG_PATH, "w", encoding="utf-8-sig") as f:
            f.write("timestamp,level,reason\n")
        self.refresh()

    def _updateBorder(self, records):
        """根据报警状态决定边框颜色。"""
        alarmActive = False
        if records:
            last = records[-1]
            reason = str(last.get("reason", last.get("alarm_reason", "")))
            alarmActive = bool(reason) and str(last.get("level", last.get("status", ""))) != "0"

        if alarmActive:
            if self.flashStartTime == 0:
                self.flashStartTime = time.time()
            if time.time() - self.flashStartTime < 5:
                self.flashState = not self.flashState
                if self.flashState:
                    self.setStyleSheet("background-color: #16213e; border: 3px solid #e94560; border-radius: 8px;")
                else:
                    self.setStyleSheet("background-color: #16213e; border: 3px solid #ff8b94; border-radius: 8px;")
            else:
                self.setStyleSheet("background-color: #16213e; border: 2px solid #e94560; border-radius: 8px;")
        else:
            self.flashStartTime = 0
            self.setStyleSheet("background-color: #16213e; border-radius: 8px;")
