"""工业巡检系统主窗口。

主窗口只负责组织页面：
- 顶部 topbar 显示系统名、时钟和状态；
- 左侧 64px 导航栏切换 4 个页面；
- 右侧 QStackedWidget 承载总览、摄像头、报警记录、设置。
"""

from __future__ import annotations

import sys
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from data.ui_state import CONFIG_PATH, UIState, VISION_SOCKET_PATH
from widgets.alarm_history_widget import AlarmHistoryWidget
from widgets.alarm_widget import AlarmWidget
from widgets.camera_widget import CameraWidget
from widgets.detection_detail_widget import DetectionDetailWidget
from widgets.sensor_widget import SensorWidget
from widgets.threshold_widget import ThresholdWidget
from widgets.voice_widget import VoiceWidget


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self):
        super().__init__()
        self.uiState = UIState()
        self.statusFlash = False
        self.navButtons = []

        self.setWindowTitle("工业巡检系统")
        self.resize(1440, 900)
        self.setStyleSheet("QMainWindow { background:#0a0e1a; color:#c8d8f0; }")

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.build_navbar())
        self.stacked = QStackedWidget()
        self.stacked.setStyleSheet("background:#0a0e1a;")
        body.addWidget(self.stacked, 1)
        root.addLayout(body, 1)

        self.build_pages()
        self.switch_page(0)

        self.refreshTimer = QTimer(self)
        self.refreshTimer.timeout.connect(self.refreshUI)
        self.refreshTimer.start(500)

        self.clockTimer = QTimer(self)
        self.clockTimer.timeout.connect(self.updateClock)
        self.clockTimer.start(1000)
        self.updateClock()
        self.refreshUI()

    def build_topbar(self):
        """创建 44px 顶部状态栏。"""
        topbar = QFrame()
        topbar.setFixedHeight(44)
        topbar.setStyleSheet(
            """
            QFrame {
                background:#0d1220;
                border-bottom:1px solid #1e2d4a;
            }
            """
        )

        self.titleLabel = QLabel("工业巡检系统  RK3588")
        self.titleLabel.setStyleSheet("color:#4fc3f7; font-size:20px; font-weight:bold; letter-spacing:0px;")
        self.clockLabel = QLabel("00:00:00")
        self.clockLabel.setAlignment(Qt.AlignCenter)
        self.clockLabel.setStyleSheet("color:#c8d8f0; font-size:22px; font-weight:bold; font-family:Consolas, Courier New;")
        self.onlineLabel = QLabel("视觉 · 语音 · 传感  在线")
        self.onlineLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.onlineLabel.setStyleSheet("color:#5a80a0; font-size:13px;")
        self.statusLabel = QLabel("● 正常")
        self.statusLabel.setAlignment(Qt.AlignCenter)
        self.statusLabel.setMinimumWidth(116)

        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.addWidget(self.titleLabel, 1)
        layout.addWidget(self.clockLabel, 1)
        layout.addWidget(self.onlineLabel, 1)
        layout.addWidget(self.statusLabel)
        return topbar

    def build_navbar(self):
        """创建左侧 64px 导航栏。"""
        nav = QFrame()
        nav.setFixedWidth(64)
        nav.setStyleSheet(
            """
            QFrame {
                background:#090e19;
                border-right:1px solid #1e2d4a;
            }
            """
        )
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(8, 14, 8, 14)
        layout.setSpacing(12)

        items = [("总览", 0), ("摄像", 1), ("报警", 2), ("设置", 3)]
        for label, index in items:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setFixedSize(48, 70)
            button.clicked.connect(lambda checked=False, page=index: self.switch_page(page))
            self.navButtons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        return nav

    def build_pages(self):
        """创建 4 个页面。"""
        self.overviewCamera = CameraWidget(self.uiState, compact=True, show_expand_button=True)
        self.overviewCamera.expand_clicked.connect(lambda: self.switch_page(1))
        self.sensorWidget = SensorWidget(self.uiState)
        self.alarmWidget = AlarmWidget(self.uiState)
        self.voiceWidget = VoiceWidget()

        overview = QWidget()
        overviewLayout = QGridLayout(overview)
        overviewLayout.setContentsMargins(18, 18, 18, 18)
        overviewLayout.setSpacing(14)
        overviewLayout.addWidget(self.overviewCamera, 0, 0, 1, 2)
        overviewLayout.addWidget(self.sensorWidget, 0, 2, 1, 1)
        overviewLayout.addWidget(self.voiceWidget, 1, 0, 1, 2)
        overviewLayout.addWidget(self.alarmWidget, 1, 2, 1, 1)
        overviewLayout.setColumnStretch(0, 1)
        overviewLayout.setColumnStretch(1, 1)
        overviewLayout.setColumnStretch(2, 2)
        overviewLayout.setRowStretch(0, 3)
        overviewLayout.setRowStretch(1, 2)

        cameraPage = QWidget()
        cameraLayout = QHBoxLayout(cameraPage)
        cameraLayout.setContentsMargins(18, 18, 18, 18)
        cameraLayout.setSpacing(16)
        self.fullCamera = CameraWidget(self.uiState, compact=False, show_expand_button=False)
        self.detectionDetail = DetectionDetailWidget(self.uiState)
        cameraLayout.addWidget(self.fullCamera, 3)
        cameraLayout.addWidget(self.detectionDetail, 1)

        self.alarmHistoryWidget = AlarmHistoryWidget(self.uiState)
        settingsPage = self.build_settings_page()

        self.stacked.addWidget(overview)
        self.stacked.addWidget(cameraPage)
        self.stacked.addWidget(self.alarmHistoryWidget)
        self.stacked.addWidget(settingsPage)

    def build_settings_page(self):
        """创建设置页：阈值滑块 + 系统信息。"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        self.thresholdWidget = ThresholdWidget(self.uiState)
        self.systemInfoLabel = QLabel()
        self.systemInfoLabel.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.systemInfoLabel.setWordWrap(True)
        self.systemInfoLabel.setStyleSheet(
            """
            QLabel {
                background:#0d1220;
                border:1px solid #1e2d4a;
                border-radius:8px;
                color:#c8d8f0;
                font-size:15px;
                padding:16px;
                font-family:Microsoft YaHei, SimHei, sans-serif;
            }
            """
        )

        layout.addWidget(self.thresholdWidget, 2)
        layout.addWidget(self.systemInfoLabel, 1)
        return page

    def switch_page(self, index):
        """切换页面并刷新导航按钮状态。"""
        self.stacked.setCurrentIndex(index)
        for idx, button in enumerate(self.navButtons):
            button.setChecked(idx == index)
            self.apply_nav_style(button, active=idx == index)

    def apply_nav_style(self, button, active=False):
        border = "#4fc3f7" if active else "transparent"
        background = "#0f1e30" if active else "#090e19"
        color = "#4fc3f7" if active else "#5a80a0"
        button.setStyleSheet(
            f"""
            QPushButton {{
                background:{background};
                color:{color};
                border:1px solid {border};
                border-radius:8px;
                font-size:13px;
                font-weight:bold;
            }}
            QPushButton:hover {{
                border:1px solid #4fc3f7;
                color:#4fc3f7;
            }}
            """
        )

    def updateClock(self):
        """更新顶部时钟。"""
        self.clockLabel.setText(time.strftime("%H:%M:%S"))

    def refreshUI(self):
        """刷新整页数据。"""
        self.uiState.refresh()
        self.sensorWidget.refresh()
        self.alarmWidget.refresh()
        self.detectionDetail.refresh()
        self.update_status_badge()
        self.update_system_info()

    def update_status_badge(self):
        """更新右上角系统状态，报警时闪烁。"""
        status = self.uiState.vision_status
        if status == "ALARM":
            self.statusFlash = not self.statusFlash
            bg = "#ff5050" if self.statusFlash else "#4a1218"
            self.statusLabel.setText("● 报警中")
            self.statusLabel.setStyleSheet(
                f"background:{bg}; color:white; border:1px solid #ff5050; border-radius:16px; padding:6px 12px; font-size:15px; font-weight:bold;"
            )
        elif status == "ABNORMAL":
            self.statusLabel.setText("● 异常")
            self.statusLabel.setStyleSheet(
                "background:#2c2110; color:#ffb020; border:1px solid #ffb020; border-radius:16px; padding:6px 12px; font-size:15px; font-weight:bold;"
            )
        else:
            self.statusLabel.setText("● 正常")
            self.statusLabel.setStyleSheet(
                "background:#0d2a22; color:#1de498; border:1px solid #1de498; border-radius:16px; padding:6px 12px; font-size:15px; font-weight:bold;"
            )

    def update_system_info(self):
        """刷新设置页系统信息。"""
        info = (
            "<b style='color:#8fcaff;'>系统信息</b><br><br>"
            f"当前状态：{self.uiState.vision_status}<br>"
            f"检测人数：{self.uiState.person_count}<br>"
            f"禁区命中：{'是' if self.uiState.zone_hit else '否'}<br>"
            f"报警帧计数：{self.uiState.alarm_frame_count}<br>"
            f"最近刷新：{self.uiState.last_refresh_time}<br><br>"
            "<b style='color:#8fcaff;'>关键路径</b><br><br>"
            f"阈值配置：{CONFIG_PATH}<br>"
            f"视觉 Socket：{VISION_SOCKET_PATH}<br>"
            f"实时画面：{self.uiState.live_frame_path or '暂无'}<br>"
            f"最近报警截图：{self.uiState.latest_alarm_screenshot or '暂无'}<br>"
        )
        self.systemInfoLabel.setText(info)


def main():
    """程序入口。"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showFullScreen()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
