"""UI 摄像头预览组件。

这个控件支持两种尺寸：
- 总览页：作为摄像头缩略图；
- 摄像头页：作为大画面显示区。

画面来源优先读仿真/视觉模块写出的 live_frame.jpg，避免 UI 和视觉模块抢摄像头。
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QPushButton, QStackedLayout, QHBoxLayout, QVBoxLayout, QWidget

from data.ui_state import UIState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_PHOTOS_DIR = PROJECT_ROOT / "vision" / "app" / "output" / "photos"
VISION_LIVE_FRAME_PATH = VISION_PHOTOS_DIR / "live_frame.jpg"


class CameraWidget(QWidget):
    """摄像头预览控件。"""

    expand_clicked = pyqtSignal()

    def __init__(self, ui_state: UIState, parent=None, compact=False, show_expand_button=True):
        super().__init__(parent)
        self.uiState = ui_state
        self.compact = compact
        self.cap = None
        self.useSharedMode = True
        self.directCameraFailed = False
        self.directFallbackAfter = time.time() + 1.5
        self.blinkState = False
        self.lastBlinkTime = time.time()

        self.label = QLabel("Camera not connected")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(420 if compact else 760, 260 if compact else 560)
        self.label.setStyleSheet("color:#5a80a0; font-size:18px; background:#071421; border-radius:8px;")

        self.expandButton = QPushButton("全屏查看 →")
        self.expandButton.clicked.connect(self.expand_clicked.emit)
        self.expandButton.setVisible(show_expand_button)
        self.expandButton.setCursor(Qt.PointingHandCursor)
        self.expandButton.setStyleSheet(
            """
            QPushButton {
                background:rgba(8, 22, 36, 190);
                color:#4fc3f7;
                border:1px solid #4fc3f7;
                border-radius:6px;
                padding:7px 12px;
                font-weight:bold;
            }
            QPushButton:hover {
                background:#10243a;
            }
            """
        )

        overlay = QWidget()
        overlayLayout = QVBoxLayout(overlay)
        overlayLayout.setContentsMargins(12, 12, 12, 12)
        overlayLayout.addStretch(1)
        buttonRow = QHBoxLayout()
        buttonRow.addStretch(1)
        buttonRow.addWidget(self.expandButton)
        overlayLayout.addLayout(buttonRow)

        stack = QStackedLayout(self)
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.addWidget(self.label)
        stack.addWidget(overlay)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateFrame)
        self.timer.start(66)

        self.setStyleSheet("background:#0d1220; border:1px solid #1e2d4a; border-radius:8px;")

    def startDirectCamera(self):
        """切换到本地摄像头模式。"""
        if self.cap is None:
            self.cap = self._openCamera()
        self.useSharedMode = False
        self.directCameraFailed = False
        self.directFallbackAfter = 0.0

    def useSharedFrameMode(self):
        """切换到共享结果图模式。"""
        self.useSharedMode = True
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def updateFrame(self):
        """刷新预览图。"""
        frame = None
        if self.useSharedMode:
            frame = self._readSharedFrame()
        if frame is None and not self.directCameraFailed and time.time() >= self.directFallbackAfter:
            frame = self._readDirectCameraFrame()
        if frame is None:
            frame = self._readSharedFrame()
        if frame is None:
            self.label.setText("Camera not connected")
            return

        target_w = max(self.label.width(), 320)
        target_h = max(self.label.height(), 200)
        frame = cv2.resize(frame, (target_w, target_h))
        frame = self._drawOverlay(frame)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(image))

    def _openCamera(self):
        """打开本地摄像头。"""
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            return cap
        cap.release()
        return None

    def _readDirectCameraFrame(self):
        if self.cap is None:
            self.cap = self._openCamera()
        if self.cap is None or not self.cap.isOpened():
            self.directCameraFailed = True
            return None
        ok, raw = self.cap.read()
        if ok and raw is not None:
            return raw
        self.directCameraFailed = True
        self.cap.release()
        self.cap = None
        return None

    def _readSharedFrame(self):
        """从共享路径读取最新画面。"""
        for previewPath in (self.uiState.live_frame_path, self.uiState.latest_frame_path, str(VISION_LIVE_FRAME_PATH)):
            if previewPath and Path(previewPath).exists():
                img = cv2.imread(previewPath)
                if img is not None:
                    return img
        latestPhoto = self._findLatestPhoto()
        if latestPhoto:
            return cv2.imread(str(latestPhoto))
        return None

    def _findLatestPhoto(self):
        if not VISION_PHOTOS_DIR.exists():
            return None
        candidates = list(VISION_PHOTOS_DIR.glob("live_frame.jpg"))
        if not candidates:
            candidates = list(VISION_PHOTOS_DIR.glob("*.jpg"))
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _drawOverlay(self, frame):
        """叠加状态、禁区、人员框、报警横幅和时间戳。"""
        h, w = frame.shape[:2]
        status = self.uiState.vision_status
        color = (228, 228, 29)
        if status == "ALARM":
            color = (80, 80, 255)
        elif status == "ABNORMAL":
            color = (32, 176, 255)

        if status == "ALARM":
            if time.time() - self.lastBlinkTime > 0.5:
                self.blinkState = not self.blinkState
                self.lastBlinkTime = time.time()
            if self.blinkState:
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), color, 4)
        else:
            cv2.rectangle(frame, (0, 0), (w - 1, h - 1), color, 2)

        self._draw_hazard_zone(frame)
        self._draw_person_boxes(frame)

        overlay = frame.copy()
        cv2.rectangle(overlay, (14, 14), (min(310, w - 20), 54), (10, 14, 26), -1)
        frame[:] = cv2.addWeighted(overlay, 0.66, frame, 0.34, 0)
        cv2.circle(frame, (34, 34), 7, color, -1)
        cv2.putText(frame, f"STATUS: {status}  P:{self.uiState.person_count}", (52, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (235, 245, 255), 2)

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text_size = cv2.getTextSize(timestamp, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.rectangle(frame, (w - text_size[0] - 24, h - 36), (w - 8, h - 8), (10, 14, 26), -1)
        cv2.putText(frame, timestamp, (w - text_size[0] - 16, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (79, 195, 247), 1)

        if status == "ALARM":
            banner = frame.copy()
            cv2.rectangle(banner, (0, 0), (w, 42), (30, 0, 150), -1)
            frame[:] = cv2.addWeighted(banner, 0.78, frame, 0.22, 0)
            cv2.putText(frame, f"ALARM ACTIVE  {self.uiState.intruded_people} person in hazard zone", (24, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)

        return frame

    def _scale_point(self, x, y, frame):
        h, w = frame.shape[:2]
        return int(x / 640 * w), int(y / 400 * h)

    def _draw_hazard_zone(self, frame):
        x1, y1 = self._scale_point(420, 80, frame)
        x2, y2 = self._scale_point(630, 340, frame)
        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (60, 20, 95), -1)
        frame[:] = cv2.addWeighted(overlay, 0.25, frame, 0.75, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (60, 60, 255), 2)

    def _draw_person_boxes(self, frame):
        for box in self.uiState.person_boxes:
            try:
                x1, y1, x2, y2 = box
            except Exception:
                continue
            p1 = self._scale_point(float(x1), float(y1), frame)
            p2 = self._scale_point(float(x2), float(y2), frame)
            cv2.rectangle(frame, p1, p2, (120, 255, 40), 2)
            cv2.putText(frame, f"person {self.uiState.confidence:.2f}", (p1[0], max(20, p1[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 255, 40), 1)

    def closeEvent(self, event):
        if self.cap is not None:
            self.cap.release()
        super().closeEvent(event)
