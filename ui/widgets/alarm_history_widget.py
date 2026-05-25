"""报警历史页。

左侧显示报警列表，右侧显示报警截图缩略图。
这个组件主要服务于“报警记录”页面，不再挤在总览页的小面板里。
"""

from __future__ import annotations

import csv
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data.ui_state import UIState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_OUTPUT_DIR = PROJECT_ROOT / "vision" / "app" / "output"
VISION_PHOTOS_DIR = VISION_OUTPUT_DIR / "photos"
VISION_RECORDS_CSV_PATH = VISION_OUTPUT_DIR / "recodes" / "records.csv"
LEGACY_VISION_RECORDS_CSV_PATH = VISION_OUTPUT_DIR / "records.csv"


class ClickableThumbnail(QLabel):
    """可点击截图缩略图。"""

    def __init__(self, image_path: Path, title: str, parent=None):
        super().__init__(parent)
        self.image_path = Path(image_path)
        self.setFixedSize(230, 150)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(str(self.image_path))
        self.setStyleSheet("background:#071421; border:1px solid #1e2d4a; border-radius:8px; color:#5a80a0;")
        self.setAlignment(Qt.AlignCenter)

        pixmap = QPixmap(str(self.image_path))
        if pixmap.isNull():
            self.setText(title)
        else:
            self.setPixmap(pixmap.scaled(226, 146, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def mousePressEvent(self, event):
        dialog = QDialog(self)
        dialog.setWindowTitle(str(self.image_path.name))
        dialog.resize(1000, 720)
        dialog.setStyleSheet("background:#0a0e1a;")
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(str(self.image_path))
        if not pixmap.isNull():
            label.setPixmap(pixmap.scaled(980, 680, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout = QVBoxLayout(dialog)
        layout.addWidget(label)
        dialog.exec_()


class AlarmHistoryWidget(QWidget):
    """报警记录完整页面。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["类型", "原因", "时间", "持续/超标"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(2, 140)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet(
            """
            QTableWidget {
                background:#0d1220;
                border:1px solid #1e2d4a;
                border-radius:8px;
                color:#c8d8f0;
                gridline-color:#14233a;
                font-size:14px;
            }
            QHeaderView::section {
                background:#101827;
                color:#8fcaff;
                border:0;
                border-bottom:1px solid #1e2d4a;
                padding:8px;
            }
            """
        )

        self.screenshotGrid = QGridLayout()
        self.screenshotGrid.setContentsMargins(14, 14, 14, 14)
        self.screenshotGrid.setSpacing(14)
        gridHolder = QWidget()
        gridHolder.setLayout(self.screenshotGrid)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(gridHolder)
        self.scroll.setStyleSheet("QScrollArea { background:#0d1220; border:1px solid #1e2d4a; border-radius:8px; }")

        leftTitle = self._section_title("今日报警记录")
        rightTitle = self._section_title("报警截图")

        left = QVBoxLayout()
        left.addWidget(leftTitle)
        left.addWidget(self.table, 1)
        right = QVBoxLayout()
        right.addWidget(rightTitle)
        right.addWidget(self.scroll, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        layout.addLayout(left, 1)
        layout.addLayout(right, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self):
        """刷新报警列表和截图网格。"""
        records = self.load_records()
        self.uiState.alarm_records = records[-5:]
        self.populate_table(records[-30:])
        self.populate_screenshots()

    def load_records(self):
        """从 CSV 读取报警记录。"""
        for path in (VISION_RECORDS_CSV_PATH, LEGACY_VISION_RECORDS_CSV_PATH):
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8-sig") as f:
                return [row for row in csv.DictReader(f) if row]
        return []

    def populate_table(self, records):
        self.table.setRowCount(0)
        for row in reversed(records):
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            alarm_type, color = self.classify_alarm(row)
            badge = QLabel(alarm_type)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"background:{color}; color:#0a0e1a; border-radius:6px; padding:4px 8px; font-weight:bold;"
            )
            self.table.setCellWidget(row_index, 0, badge)
            self.table.setItem(row_index, 1, QTableWidgetItem(row.get("reason") or row.get("alarm_reason") or "未知报警"))
            self.table.setItem(row_index, 2, QTableWidgetItem(row.get("timestamp") or row.get("alarm_time") or "--"))
            self.table.setItem(row_index, 3, QTableWidgetItem(self.format_extra(row)))
            self.table.setRowHeight(row_index, 54)

    def populate_screenshots(self):
        while self.screenshotGrid.count():
            item = self.screenshotGrid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        photos = self.find_alarm_photos()[:12]
        if not photos:
            empty = QLabel("暂无报警截图\n请查看 vision/app/output/photos/")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color:#5a80a0; font-size:15px;")
            self.screenshotGrid.addWidget(empty, 0, 0)
            return

        for idx, path in enumerate(photos):
            thumb = ClickableThumbnail(path, path.name)
            self.screenshotGrid.addWidget(thumb, idx // 2, idx % 2)

    def find_alarm_photos(self):
        if not VISION_PHOTOS_DIR.exists():
            return []
        photos = []
        for pattern in ("alarm_*.jpg", "alarm_*.png", "voice_result_*.jpg", "*.jpg"):
            photos.extend(VISION_PHOTOS_DIR.glob(pattern))
            if photos:
                break
        return sorted(set(photos), key=lambda path: path.stat().st_mtime, reverse=True)

    def classify_alarm(self, row):
        status = str(row.get("status", "")).upper()
        alarm_type = str(row.get("alarm_type", "")).lower()
        reason = str(row.get("reason", "")).lower()
        if status == "NORMAL":
            return "已解除", "#1de498"
        if "zone" in alarm_type or "禁区" in reason or "right_third" in reason:
            return "禁区", "#ff5050"
        return "传感器", "#ffb020"

    def format_extra(self, row):
        reason = str(row.get("reason", ""))
        if "过高" in reason or "过低" in reason or "过载" in reason:
            return "超标"
        if row.get("alarm_frame_count"):
            return f"{row.get('alarm_frame_count')} 帧"
        return row.get("summary", "")[:24]

    def _section_title(self, text):
        label = QLabel(f"• {text}")
        label.setStyleSheet("color:#8fcaff; font-size:18px; font-weight:bold; padding:10px 12px;")
        return label
