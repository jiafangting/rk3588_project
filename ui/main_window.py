"""main_window.py

工业巡检系统主窗口入口。

这个文件的职责很单纯，就是把界面各个组件组织起来，
并且定时去刷新统一状态对象 `UIState`。

你可以把它理解成 UI 层的“总指挥”：
- 它不直接处理传感器数据；
- 它不直接解析视觉 socket；
- 它不直接读 CSV 或改 config.json；
- 它只负责把这些模块拼成一个完整的屏幕界面。

作用：
1. 组织四个功能区域：摄像头、传感器、报警、阈值配置；
2. 顶部显示系统状态栏；
3. 定时刷新 UIState；
4. 适配 RK3588 工业屏的全屏显示。

作者：Cursor
"""

from __future__ import annotations

import sys
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QWidget

from data.ui_state import UIState
from widgets.alarm_widget import AlarmWidget
from widgets.camera_widget import CameraWidget
from widgets.sensor_widget import SensorWidget
from widgets.threshold_widget import ThresholdWidget


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self):
        super().__init__()
        self.uiState = UIState()
        self.setWindowTitle("工业巡检系统")
        self.resize(1024, 600)
        self.setStyleSheet("background-color: #1a1a2e; color: white;")

        central = QWidget()
        self.setCentralWidget(central)
        self.grid = QGridLayout(central)
        self.grid.setContentsMargins(10, 10, 10, 10)
        self.grid.setSpacing(10)

        self.header = QLabel("工业巡检系统")
        self.clockLabel = QLabel("00:00:00")
        self.statusLabel = QLabel("● 正常")
        self.statusLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        headerRow = QHBoxLayout()
        headerRow.addWidget(self.header)
        headerRow.addStretch(1)
        headerRow.addWidget(self.clockLabel)
        headerRow.addWidget(self.statusLabel)

        self.headerWidget = QWidget()
        self.headerWidget.setLayout(headerRow)
        self.grid.addWidget(self.headerWidget, 0, 0, 1, 2)

        self.cameraWidget = CameraWidget(self.uiState)
        self.sensorWidget = SensorWidget(self.uiState)
        self.alarmWidget = AlarmWidget(self.uiState)
        self.thresholdWidget = ThresholdWidget(self.uiState)

        self.grid.addWidget(self.cameraWidget, 1, 0, 2, 1)
        self.grid.addWidget(self.sensorWidget, 1, 1, 1, 1)
        self.grid.addWidget(self.alarmWidget, 2, 1, 1, 1)
        self.grid.addWidget(self.thresholdWidget, 3, 0, 1, 2)

        self.refreshTimer = QTimer(self)
        self.refreshTimer.timeout.connect(self.refreshUI)
        self.refreshTimer.start(500)

        self.clockTimer = QTimer(self)
        self.clockTimer.timeout.connect(self.updateClock)
        self.clockTimer.start(1000)
        self.updateClock()

    def updateClock(self):
        """更新顶部时间。"""
        self.clockLabel.setText(time.strftime("%H:%M:%S"))

    def refreshUI(self):
        """刷新整页数据。"""
        self.uiState.refresh()
        self.sensorWidget.refresh()
        self.alarmWidget.refresh()
        if self.uiState.vision_status == "ALARM":
            self.statusLabel.setText("🔴 报警")
            self.statusLabel.setStyleSheet("color: #e94560; font-size: 18px; font-weight: bold;")
        elif self.uiState.vision_status == "ABNORMAL":
            self.statusLabel.setText("● 异常")
            self.statusLabel.setStyleSheet("color: #f0a500; font-size: 18px; font-weight: bold;")
        else:
            self.statusLabel.setText("● 正常")
            self.statusLabel.setStyleSheet("color: #0f9b58; font-size: 18px; font-weight: bold;")


def main():
    """程序入口。"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showFullScreen()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
