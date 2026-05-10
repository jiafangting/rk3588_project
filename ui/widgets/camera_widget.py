"""Camera preview widget for the UI.

The widget prefers a live local camera feed. If the camera is already owned by
the vision process, it falls back to the shared live frame path published by the
vision socket status.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from data.ui_state import UIState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_PHOTOS_DIR = PROJECT_ROOT / "vision" / "app" / "output" / "photos"
VISION_LIVE_FRAME_PATH = VISION_PHOTOS_DIR / "live_frame.jpg"


class CameraWidget(QWidget):
    """Live camera/vision-frame display widget."""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state
        self.label = QLabel("Camera not connected")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(640, 400)
        self.label.setStyleSheet("color: white; font-size: 18px; background-color: #111827;")

        self.cap = None
        self.useSharedMode = True
        self.directCameraFailed = False
        self.directFallbackAfter = time.time() + 1.5
        self.blinkState = False
        self.lastBlinkTime = time.time()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateFrame)
        self.timer.start(100)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def startDirectCamera(self):
        """Switch to direct camera mode."""
        if self.cap is None:
            self.cap = self._openCamera()
        self.useSharedMode = False
        self.directCameraFailed = False
        self.directFallbackAfter = 0.0

    def useSharedFrameMode(self):
        """Switch to shared frame mode."""
        self.useSharedMode = True
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def updateFrame(self):
        """Refresh the preview image."""
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

        frame = cv2.resize(frame, (640, 400))
        frame = self._drawOverlay(frame)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytesPerLine = ch * w
        image = QImage(rgb.data, w, h, bytesPerLine, QImage.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(image))

    def _openCamera(self):
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
        candidates = list(VISION_PHOTOS_DIR.glob("voice_result_*.jpg"))
        if not candidates:
            candidates = list(VISION_PHOTOS_DIR.glob("*.jpg"))
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _drawOverlay(self, frame):
        status = self.uiState.vision_status
        color = (15, 155, 88)
        if status == "ALARM":
            color = (233, 69, 96)
        elif status == "ABNORMAL":
            color = (240, 165, 0)

        if status == "ALARM":
            if time.time() - self.lastBlinkTime > 0.5:
                self.blinkState = not self.blinkState
                self.lastBlinkTime = time.time()
            if self.blinkState:
                cv2.rectangle(frame, (0, 0), (639, 399), color, 4)
        else:
            cv2.rectangle(frame, (0, 0), (639, 399), color, 2)

        cv2.putText(frame, f"STATUS: {status}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(frame, time.strftime("%H:%M:%S"), (530, 385), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return frame

    def closeEvent(self, event):
        if self.cap is not None:
            self.cap.release()
        super().closeEvent(event)
