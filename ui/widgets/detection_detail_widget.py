"""摄像头页检测详情面板。"""

from __future__ import annotations

from pathlib import Path
import sys

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from data.ui_state import UIState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_APP_DIR = PROJECT_ROOT / "vision" / "app"
VISION_PHOTOS_DIR = VISION_APP_DIR / "output" / "photos"
if str(VISION_APP_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_APP_DIR))

try:
    from config import ALARM_FRAMES_REQUIRED, YOLO_CONF
except Exception:
    ALARM_FRAMES_REQUIRED = 5
    YOLO_CONF = 0.30


class SnapshotDelegate(QStyledItemDelegate):
    """用自定义方式渲染截图历史列表。"""

    def sizeHint(self, option, index):
        return QSize(190, 124)

    def paint(self, painter: QPainter, option, index):
        rect = option.rect.adjusted(6, 6, -6, -6)
        path = index.data(Qt.UserRole)
        status = index.data(Qt.UserRole + 1) or "SNAPSHOT"
        timestamp = index.data(Qt.UserRole + 2) or ""

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#1e2d4a"))
        painter.setBrush(QColor("#071421"))
        painter.drawRoundedRect(rect, 8, 8)

        pixmap = QPixmap(str(path))
        image_rect = rect.adjusted(8, 8, -8, -34)
        if not pixmap.isNull():
            scaled = pixmap.scaled(image_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = image_rect.x() + (image_rect.width() - scaled.width()) // 2
            painter.drawPixmap(x, image_rect.y(), scaled)

        color = QColor("#1de498")
        if "ALARM" in status:
            color = QColor("#ff5050")
        elif "ABNORMAL" in status:
            color = QColor("#ffb020")
        painter.setPen(color)
        painter.drawText(rect.adjusted(10, rect.height() - 28, -10, -8), Qt.AlignLeft | Qt.AlignVCenter, status)
        painter.setPen(QColor("#4fc3f7"))
        painter.drawText(rect.adjusted(84, rect.height() - 28, -10, -8), Qt.AlignLeft | Qt.AlignVCenter, timestamp)
        painter.restore()


class DetectionDetailWidget(QWidget):
    """摄像头页右侧检测详情。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state

        title = QLabel("• 检测详情")
        title.setStyleSheet("color:#8fcaff; font-size:18px; font-weight:bold; padding:10px 12px;")

        self.statusValue = self._value_label()
        self.personValue = self._value_label()
        self.zoneValue = self._value_label()
        self.confidenceValue = self._value_label()
        self.alarmFrameValue = self._value_label()
        self.yoloValue = self._value_label()
        self.updateValue = self._small_value_label()

        self.personProgress = self._progress()
        self.confidenceProgress = self._progress()
        self.alarmProgress = self._progress()

        details = QVBoxLayout()
        details.setContentsMargins(14, 8, 14, 8)
        details.setSpacing(12)
        details.addLayout(self._row("当前状态", self.statusValue))
        details.addLayout(self._row("检测人数", self.personValue, self.personProgress))
        details.addLayout(self._row("禁区命中", self.zoneValue))
        details.addLayout(self._row("置信度", self.confidenceValue, self.confidenceProgress))
        details.addLayout(self._row("报警帧计数", self.alarmFrameValue, self.alarmProgress))
        details.addLayout(self._row("YOLO 阈值", self.yoloValue))
        details.addLayout(self._row("最后更新", self.updateValue))

        historyTitle = QLabel("• 报警截图记录")
        historyTitle.setStyleSheet("color:#8fcaff; font-size:18px; font-weight:bold; padding:12px 12px 4px;")
        self.snapshotList = QListWidget()
        self.snapshotList.setItemDelegate(SnapshotDelegate(self.snapshotList))
        self.snapshotList.setSpacing(4)
        self.snapshotList.itemClicked.connect(self.open_snapshot)
        self.snapshotList.setStyleSheet(
            """
            QListWidget {
                background:#0d1220;
                border:0;
                color:#c8d8f0;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(title)
        layout.addLayout(details)
        layout.addWidget(historyTitle)
        layout.addWidget(self.snapshotList, 1)

        self.setStyleSheet("background:#0d1220; border:1px solid #1e2d4a; border-radius:8px;")
        self.refresh()

    def refresh(self):
        """根据 UIState 刷新检测详情。"""
        status = self.uiState.vision_status
        status_color = "#1de498" if status == "NORMAL" else "#ffb020"
        if status == "ALARM":
            status_color = "#ff5050"
        self.statusValue.setText(status)
        self.statusValue.setStyleSheet(f"color:{status_color}; font-size:18px; font-weight:bold;")

        person_count = max(0, int(self.uiState.person_count))
        self.personValue.setText(f"{person_count} 人")
        self.personProgress.setValue(min(person_count * 25, 100))

        hit_text = f"是 · {self.uiState.intruded_people} 人" if self.uiState.zone_hit else "否"
        self.zoneValue.setText(hit_text)
        self.zoneValue.setStyleSheet(
            f"color:{'#ff5050' if self.uiState.zone_hit else '#1de498'}; font-size:18px; font-weight:bold;"
        )

        confidence = max(0.0, min(1.0, float(self.uiState.confidence)))
        self.confidenceValue.setText(f"{confidence:.2f}")
        self.confidenceProgress.setValue(int(confidence * 100))

        alarm_frames = max(0, int(self.uiState.alarm_frame_count))
        self.alarmFrameValue.setText(f"{alarm_frames} / {ALARM_FRAMES_REQUIRED}")
        self.alarmProgress.setValue(min(int(alarm_frames / max(ALARM_FRAMES_REQUIRED, 1) * 100), 100))

        self.yoloValue.setText(f"{float(YOLO_CONF):.2f}")
        self.updateValue.setText(self.uiState.last_refresh_time or "--")
        self.populate_snapshots()

    def populate_snapshots(self):
        self.snapshotList.clear()
        for path in self.find_photos()[:12]:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, self.status_from_name(path))
            item.setData(Qt.UserRole + 2, self.time_from_mtime(path))
            self.snapshotList.addItem(item)

    def find_photos(self):
        if not VISION_PHOTOS_DIR.exists():
            return []
        photos = []
        for pattern in ("alarm_*.jpg", "alarm_*.png", "voice_result_*.jpg", "*.jpg"):
            photos.extend(VISION_PHOTOS_DIR.glob(pattern))
            if photos:
                break
        return sorted(set(photos), key=lambda path: path.stat().st_mtime, reverse=True)

    def open_snapshot(self, item):
        path = Path(item.data(Qt.UserRole))
        dialog = QDialog(self)
        dialog.setWindowTitle(path.name)
        dialog.resize(980, 700)
        dialog.setStyleSheet("background:#0a0e1a;")
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            label.setPixmap(pixmap.scaled(940, 660, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout = QVBoxLayout(dialog)
        layout.addWidget(label)
        dialog.exec_()

    def status_from_name(self, path: Path):
        name = path.name.upper()
        if "ALARM" in name:
            return "ALARM"
        if "ABNORMAL" in name:
            return "ABNORMAL"
        return self.uiState.vision_status or "SNAPSHOT"

    def time_from_mtime(self, path: Path):
        try:
            from datetime import datetime

            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M:%S")
        except Exception:
            return ""

    def _row(self, label_text, value_widget, progress=None):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setStyleSheet("color:#5a80a0; font-size:15px; font-weight:bold;")
        row.addWidget(label)
        if progress is not None:
            row.addWidget(progress, 1)
        else:
            row.addStretch(1)
        row.addWidget(value_widget)
        return row

    def _value_label(self):
        label = QLabel("--")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setStyleSheet("color:#c8d8f0; font-size:18px; font-weight:bold;")
        return label

    def _small_value_label(self):
        label = QLabel("--")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setStyleSheet("color:#5a80a0; font-size:13px; font-family:Consolas, Courier New;")
        return label

    def _progress(self):
        bar = QProgressBar()
        bar.setFixedHeight(4)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            """
            QProgressBar { background:#0f1e30; border:0; border-radius:2px; }
            QProgressBar::chunk { background:#1de498; border-radius:2px; }
            """
        )
        return bar
