"""报警状态组件。

这个组件负责把“报警历史”和“当前是否报警”展示到界面右侧。
它不做报警判断，报警判断已经由后端和视觉模块完成；这里的工作只是展示。

作用：
1. 显示最近 5 条报警记录；
2. 支持清空记录；
3. 报警时边框红色闪烁；
4. 5 秒后停止闪烁但保留历史记录。

流程：
1. `refresh()` 从 CSV 读最近记录；
2. 把记录整理成几行短文本；
3. `_updateBorder()` 根据最后一条记录决定是否闪烁；
4. QLabel / 样式表更新到界面。

关键输入：
- `records.csv`
- `records.jsonl`
- `ui_state.alarm_records`

返回值：
- 无；通过更新界面文本和边框样式生效。

硬件依赖：
- `vision/app/output/recodes/records.csv`

作者：Cursor
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QPushButton, QVBoxLayout, QWidget, QLabel

from data.ui_state import UIState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_OUTPUT_DIR = PROJECT_ROOT / "vision" / "app" / "output"
VISION_RECORDS_CSV_PATH = VISION_OUTPUT_DIR / "recodes" / "records.csv"
VISION_RECORDS_JSONL_PATH = VISION_OUTPUT_DIR / "recodes" / "records.jsonl"
LEGACY_VISION_RECORDS_CSV_PATH = VISION_OUTPUT_DIR / "records.csv"


class AlarmWidget(QWidget):
    """报警列表和状态面板。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state
        self.title = QLabel("• 报警记录")
        self.title.setStyleSheet("color:#8fcaff; font-size:18px; font-weight:bold; padding:10px 14px;")

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#c8d8f0; font-size:14px; padding:8px 14px;")

        self.clearButton = QPushButton("清空记录")
        self.clearButton.clicked.connect(self.clearRecords)
        self.clearButton.setStyleSheet(
            "background:#2a080b; color:#ff5050; border:1px solid #6b171f; border-radius:7px; padding:8px; font-size:14px; font-weight:bold;"
        )

        layout = QVBoxLayout()
        layout.addWidget(self.title)
        layout.addWidget(self.info)
        layout.addWidget(self.clearButton)
        self.setLayout(layout)
        self.setStyleSheet("background:#0d1220; border:1px solid #1e2d4a; border-radius:8px;")

        self.flashState = False
        self.flashStartTime = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

    def refresh(self):
        """刷新最近报警记录。

        流程：
        1. 读取最新记录；
        2. 写入 `uiState.alarm_records`；
        3. 生成显示文本；
        4. 更新闪烁边框。
        """
        records = self._loadRecords()
        self.uiState.alarm_records = records

        lines = []
        for idx, row in enumerate(reversed(records[-5:])):
            timeText = row.get("timestamp") or row.get("alarm_time") or "--:--:--"
            reason = row.get("reason") or row.get("alarm_reason") or row.get("alarm_type") or "未知报警"
            prefix = "●" if idx == 0 else ("✓" if str(row.get("status", "")) == "NORMAL" else "•")
            lines.append(f"{prefix} {timeText}  {reason}")

        if not lines:
            lines = ["当前没有报警记录"]

        self.info.setText("<br>".join(lines))
        self._updateBorder(records)

    def _loadRecords(self):
        """从视觉记录 CSV 加载记录。"""
        for csv_path in (VISION_RECORDS_CSV_PATH, LEGACY_VISION_RECORDS_CSV_PATH):
            if not csv_path.exists():
                continue
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        return []

    def clearRecords(self):
        """清空视觉记录 CSV 文件。"""
        VISION_RECORDS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(VISION_RECORDS_CSV_PATH, "w", encoding="utf-8-sig") as f:
            f.write("timestamp,status,reason,speech_text,raw_path,result_path,person_count,summary,temperature,humidity,voltage,current,temp_device,smoke,zone_hit,alarm_frame_count,confidence,alarm_type,alarm_reason,zone_name\n")
        VISION_RECORDS_JSONL_PATH.write_text("", encoding="utf-8")
        self.refresh()

    def _updateBorder(self, records):
        """根据报警状态决定边框颜色。"""
        alarmActive = False
        if records:
            last = records[-1]
            status = str(last.get("status", "")).upper()
            alarmActive = (
                status == "ALARM"
                or bool(str(last.get("alarm_type", "")).strip())
                or bool(str(last.get("alarm_time", "")).strip())
                or bool(str(last.get("alarm_reason", "")).strip())
            )

        if alarmActive:
            if self.flashStartTime == 0:
                self.flashStartTime = time.time()
            if time.time() - self.flashStartTime < 5:
                self.flashState = not self.flashState
                if self.flashState:
                    self.setStyleSheet("background:#0d1220; border:2px solid #ff5050; border-radius:8px;")
                else:
                    self.setStyleSheet("background:#0d1220; border:2px solid #8a2430; border-radius:8px;")
            else:
                self.setStyleSheet("background:#0d1220; border:1px solid #ff5050; border-radius:8px;")
        else:
            self.flashStartTime = 0
            self.setStyleSheet("background:#0d1220; border:1px solid #1e2d4a; border-radius:8px;")
