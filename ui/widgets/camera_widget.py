"""camera_widget.py

摄像头画面组件。

作用：
1. 显示摄像头画面；
2. 支持直连模式和共享模式；
3. 叠加检测框、状态文字和时间戳；
4. 报警时边框闪烁提示。

硬件依赖：
- OpenCV 摄像头输入
- 视觉模块输出帧或共享状态

作者：Cursor
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from data.ui_state import UIState


class CameraWidget(QWidget):
    """摄像头画面显示控件。"""

    def __init__(self, ui_state: UIState, parent=None):
        super().__init__(parent)
        self.uiState = ui_state
        self.label = QLabel("摄像头未连接")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(640, 400)
        self.label.setStyleSheet("color: white; font-size: 18px; background-color: #111827;")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateFrame)
        self.timer.start(100)

        self.cap = None
        self.useSharedMode = True
        self.blinkState = False
        self.lastBlinkTime = time.time()

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def startDirectCamera(self):
        """切换到直连摄像头模式。"""
        if self.cap is None:
            self.cap = cv2.VideoCapture(0)
        self.useSharedMode = False

    def useSharedFrameMode(self):
        """切换到共享帧模式。"""
        self.useSharedMode = True
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def updateFrame(self):
        """刷新画面。"""
        frame = None

        if self.useSharedMode:
            frame = self._readSharedFrame()
        else:
            if self.cap is None:
                self.cap = cv2.VideoCapture(0)
            if self.cap is not None and self.cap.isOpened():
                ok, raw = self.cap.read()
                if ok:
                    frame = raw

        if frame is None:
            self.label.setText("摄像头未连接")
            return

        frame = cv2.resize(frame, (640, 400))
        frame = self._drawOverlay(frame)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytesPerLine = ch * w
        image = QImage(rgb.data, w, h, bytesPerLine, QImage.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(image))

    def _readSharedFrame(self):
        """从共享状态读取已处理画面。"""
        previewPath = self.uiState.latest_frame_path
        if previewPath and Path(previewPath).exists():
            img = cv2.imread(previewPath)
            return img
        return None

    def _drawOverlay(self, frame):
        """叠加状态、时间戳和报警闪烁边框。"""
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
        """关闭窗口时释放摄像头。"""
        if self.cap is not None:
            self.cap.release()
        super().closeEvent(event)
