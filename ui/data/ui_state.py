"""ui_state.py

UI 状态管理模块。

这个文件是整个 UI 的“数据中枢”。

为什么要单独做这一层？
因为界面里有很多组件：摄像头、传感器、报警记录、阈值配置。
如果每个组件都自己去读 socket、读 CSV、读 JSON，那么代码会很乱，
而且不同组件读到的数据很容易不一致。

所以这里专门做一个 `UIState`：
- 统一存放当前界面要显示的数据；
- 统一负责从视觉模块、日志文件、配置文件读取信息；
- 统一处理失败和降级逻辑；
- 数据源不可用时，自动切换模拟数据，保证界面仍然能跑起来。

硬件依赖：
- RK3588 上的视觉模块 socket
- rk3588/config.json
- rk3588/alarm_log.csv

作者：Cursor
"""

from __future__ import annotations

import csv
import json
import random
import socket
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_SOCKET_PATH = "/tmp/vision.sock"
ALARM_LOG_PATH = PROJECT_ROOT / "rk3588" / "alarm_log.csv"
CONFIG_PATH = PROJECT_ROOT / "rk3588" / "config.json"

DEFAULT_THRESHOLD = {
    "temp_max": 60.0,
    "humidity_min": 20.0,
    "humidity_max": 80.0,
    "current_max": 10.0,
    "temp_device_max": 80.0,
    "smoke_alarm": 1,
}


@dataclass
class UIState:
    """UI 需要的统一状态。

    这个对象把视觉状态、传感器数值、报警记录、阈值配置统一保存下来，
    这样主窗口各个组件只需要读这一份数据，不需要各自去查文件。
    """

    vision_status: str = "UNKNOWN"
    person_count: int = 0
    alarm_active: bool = False
    temperature: float = 0.0
    humidity: float = 0.0
    current: float = 0.0
    temp_device: float = 0.0
    smoke: int = 0
    alarm_records: List[dict] = field(default_factory=list)
    threshold: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLD))
    latest_frame_path: str = ""
    last_refresh_time: str = ""

    def refresh(self):
        """刷新全部 UI 数据。

        刷新顺序：
        1. 查询视觉 socket；
        2. 读取报警日志；
        3. 读取阈值配置；
        4. 如果全部都失败，就生成模拟数据。
        """
        vision_ok = False
        log_ok = False
        config_ok = False

        try:
            vision_data = self._query_vision_status()
            self.vision_status = str(vision_data.get("status", "UNKNOWN"))
            self.person_count = int(vision_data.get("person_count", 0))
            self.alarm_active = self.vision_status == "ALARM"
            self.latest_frame_path = str(vision_data.get("result_path", ""))
            vision_ok = True
        except Exception:
            self.vision_status = "UNKNOWN"
            self.person_count = 0
            self.alarm_active = False

        try:
            self.alarm_records = self._read_alarm_records()
            latest_sensor = self._read_latest_sensor_values_from_csv()
            if latest_sensor:
                self.temperature = latest_sensor.get("temperature", self.temperature)
                self.humidity = latest_sensor.get("humidity", self.humidity)
                self.current = latest_sensor.get("current", self.current)
                self.temp_device = latest_sensor.get("temp_device", self.temp_device)
                self.smoke = latest_sensor.get("smoke", self.smoke)
            log_ok = True
        except Exception:
            self.alarm_records = self.alarm_records or []

        try:
            self.threshold = self._read_threshold_config()
            config_ok = True
        except Exception:
            self.threshold = self.threshold or dict(DEFAULT_THRESHOLD)

        if not vision_ok and not log_ok and not config_ok:
            self._generate_mock_data()

        self.last_refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _query_vision_status(self):
        """通过 Unix Socket 查询视觉状态。"""
        payload = b'{"cmd":"query_status"}\n'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(VISION_SOCKET_PATH)
            sock.sendall(payload)
            buffer = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                if b"\n" in buffer:
                    line = buffer.split(b"\n", 1)[0].decode("utf-8", errors="replace")
                    return json.loads(line)
        raise RuntimeError("视觉模块没有返回数据")

    def _read_alarm_records(self):
        """读取报警日志的最近记录。"""
        records = []
        if not ALARM_LOG_PATH.exists():
            return records

        with open(ALARM_LOG_PATH, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                records.append(row)
        return records[-5:]

    def _read_latest_sensor_values_from_csv(self):
        """从 CSV 中读取最新一行传感器值。"""
        if not ALARM_LOG_PATH.exists():
            return {}

        with open(ALARM_LOG_PATH, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return {}

        latest = rows[-1]
        result = {}
        for key in ("temperature", "humidity", "current", "temp_device", "smoke"):
            if key in latest and latest[key] not in ("", None):
                try:
                    result[key] = float(latest[key]) if key != "smoke" else int(float(latest[key]))
                except Exception:
                    pass
        return result

    def _read_threshold_config(self):
        """读取阈值配置 JSON。"""
        if not CONFIG_PATH.exists():
            return dict(DEFAULT_THRESHOLD)
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        threshold = dict(DEFAULT_THRESHOLD)
        threshold.update({k: data.get(k, v) for k, v in threshold.items()})
        return threshold

    def _generate_mock_data(self):
        """生成模拟数据，方便界面调试。"""
        self.vision_status = random.choice(["NORMAL", "ABNORMAL", "ALARM"])
        self.person_count = random.randint(0, 3)
        self.alarm_active = self.vision_status == "ALARM"
        self.temperature = round(random.uniform(20, 65), 1)
        self.humidity = round(random.uniform(10, 90), 1)
        self.current = round(random.uniform(0.5, 12), 1)
        self.temp_device = round(random.uniform(25, 90), 1)
        self.smoke = random.choice([0, 0, 0, 1, 2])
        self.alarm_records = [
            {"time": "14:32:10", "reason": "烟雾报警"},
            {"time": "13:15:22", "reason": "人员进入禁区"},
        ]
