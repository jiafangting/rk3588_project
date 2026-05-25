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
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_APP_DIR = PROJECT_ROOT / "vision" / "app"
if str(VISION_APP_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_APP_DIR))

from socket_config import get_vision_socket_path


VISION_SOCKET_PATH = get_vision_socket_path()
VISION_TCP_HOST = "127.0.0.1"
VISION_TCP_PORT = 8765
VISION_OUTPUT_DIR = PROJECT_ROOT / "vision" / "app" / "output"
VISION_PHOTOS_DIR = VISION_OUTPUT_DIR / "photos"
VISION_RECORDS_DIR = VISION_OUTPUT_DIR / "recodes"
VISION_RECORDS_CSV_PATH = VISION_RECORDS_DIR / "records.csv"
VISION_RECORDS_JSONL_PATH = VISION_RECORDS_DIR / "records.jsonl"
VISION_LIVE_FRAME_PATH = VISION_PHOTOS_DIR / "live_frame.jpg"
LEGACY_VISION_RECORDS_CSV_PATH = VISION_OUTPUT_DIR / "records.csv"
ALARM_LOG_PATH = PROJECT_ROOT / "rk3588" / "alarm_log.csv"
CONFIG_PATH = PROJECT_ROOT / "rk3588" / "config.json"

DEFAULT_THRESHOLD = {
    "temp_max": 60.0,
    "humidity_min": 20.0,
    "humidity_max": 80.0,
    "voltage_min": 210.0,
    "voltage_max": 240.0,
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
    voltage: float = 0.0
    current: float = 0.0
    temp_device: float = 0.0
    smoke: int = 0
    person_boxes: list = field(default_factory=list)
    alarm_frame_count: int = 0
    zone_hit: bool = False
    latest_alarm_screenshot: str = ""
    confidence: float = 0.0
    intruded_people: int = 0
    yolo_confidence_threshold: float = 0.30
    alarm_records: List[dict] = field(default_factory=list)
    threshold: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLD))
    latest_frame_path: str = ""
    live_frame_path: str = ""
    last_refresh_time: str = ""

    def refresh(self):
        """刷新全部 UI 数据。

        你可以把这个函数理解成 UI 的“统一取数入口”。
        UI 上所有面板要显示的数据，都尽量先来这里拿，避免每个组件
        自己到处查文件、查 socket，最后数据不一致。

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
            self.live_frame_path = str(vision_data.get("live_frame_path", ""))
            self.latest_frame_path = str(vision_data.get("result_path", "")) or self._find_latest_photo_path()
            self._apply_sensor_values(vision_data)
            self._apply_detection_values(vision_data)
            vision_ok = True
        except Exception:
            self.vision_status = "UNKNOWN"
            self.person_count = 0
            self.alarm_active = False
            self.live_frame_path = str(VISION_LIVE_FRAME_PATH) if VISION_LIVE_FRAME_PATH.exists() else ""
            self.latest_frame_path = self._find_latest_photo_path()
            self.person_boxes = self._estimate_person_boxes()

        try:
            self.alarm_records = self._read_alarm_records()
            self.latest_alarm_screenshot = self._find_latest_alarm_screenshot()
            latest_sensor = self._read_latest_sensor_values_from_csv()
            if latest_sensor:
                self._apply_sensor_values(latest_sensor)
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
        """通过 Unix Socket 查询视觉状态。

        这一步就是 UI 如何和仿真后端“说话”的地方。
        它发出的命令是 get_status，拿到的是服务端缓存的最新结果。
        这样 UI 反复刷新也不会强迫视觉模块重新做一次推理。
        """
        # 视觉 socket 协议和语音/C 主控保持一致：所有请求都是一行 JSON，
        # 以换行符结尾。get_status 只读取服务端缓存的最新结果，不触发新的
        # 相机推理，因此 UI 可以高频刷新而不会拖慢视觉主流程。
        payload = b'{"cmd":"get_status"}\n'
        if hasattr(socket, "AF_UNIX"):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2.0)
                    sock.connect(VISION_SOCKET_PATH)
                    sock.sendall(payload)
                    return self._read_json_line(sock)
            except Exception:
                # 有些 Windows/Python 环境虽然看得到 AF_UNIX，但实际连接不稳定。
                # 仿真器的视觉 socket 服务端支持 TCP 回退，所以 UI 会先试 Unix socket，
                # 失败后再试 127.0.0.1:8765。
                pass

        with socket.create_connection((VISION_TCP_HOST, VISION_TCP_PORT), timeout=2.0) as sock:
            sock.settimeout(2.0)
            sock.sendall(payload)
            return self._read_json_line(sock)

        raise RuntimeError("视觉模块没有返回数据")

    def _read_json_line(self, sock):
        """从 socket 里读取一行 JSON，并转成 dict。"""
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
        """读取视觉巡检记录的最近记录。

        这就是“日志怎么被 UI 读出来”的部分。
        仿真后端会不断往 records.csv / alarm_log.csv 里写内容，UI 只读取
        最后几条，这样界面刷新快，而且不会把历史全部一次性搬进来。
        """
        records = []
        for csv_path in (VISION_RECORDS_CSV_PATH, LEGACY_VISION_RECORDS_CSV_PATH, ALARM_LOG_PATH):
            if not csv_path.exists():
                continue
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row:
                        continue
                    records.append(row)
            if records:
                break
        return records[-5:]

    def _apply_sensor_values(self, data):
        """把 socket 或日志里的传感器字段写入 UIState。"""
        for key in ("temperature", "humidity", "voltage", "current", "temp_device"):
            if key in data and data[key] not in ("", None):
                try:
                    setattr(self, key, float(data[key]))
                except Exception:
                    pass
        if "smoke" in data and data["smoke"] not in ("", None):
            try:
                self.smoke = int(float(data["smoke"]))
            except Exception:
                pass

    def _apply_detection_values(self, data):
        """把 socket 里的视觉细节写入 UIState。

        真视觉模块和软件仿真器返回的字段不一定完全一样，所以这里会：
        - 有字段就直接使用；
        - 没有字段就按当前人数和报警状态估算一份 UI 可展示的数据。
        """
        self.zone_hit = self._to_bool(data.get("zone_hit")) or bool(str(data.get("zone_name", "")).strip())
        self.alarm_frame_count = self._to_int(data.get("alarm_frame_count"), 5 if self.alarm_active else 0)
        self.intruded_people = self._to_int(data.get("intruded_people"), self.person_count if self.zone_hit else 0)
        self.confidence = self._to_float(data.get("confidence") or data.get("alarm_score"), 0.87 if self.alarm_active else 0.0)

        raw_boxes = data.get("person_boxes") or []
        self.person_boxes = self._normalize_person_boxes(raw_boxes)
        if not self.person_boxes:
            self.person_boxes = self._estimate_person_boxes()

        if self.alarm_active:
            self.latest_alarm_screenshot = (
                str(data.get("snapshot_path") or data.get("result_path") or data.get("live_frame_path") or self.latest_alarm_screenshot)
            )

    def _to_bool(self, value):
        """把 socket 里的真假值安全转成 bool。"""
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "y", "是")

    def _to_int(self, value, default=0):
        """把数字字段安全转成 int。"""
        try:
            return int(float(value))
        except Exception:
            return default

    def _to_float(self, value, default=0.0):
        """把数字字段安全转成 float。"""
        try:
            return float(value)
        except Exception:
            return default

    def _normalize_person_boxes(self, raw_boxes):
        """统一人员框格式。

        约定 UI 内部统一使用 `(x1, y1, x2, y2)`，坐标按 640x400 画面理解。
        """
        boxes = []
        if not isinstance(raw_boxes, list):
            return boxes

        for item in raw_boxes:
            try:
                if isinstance(item, dict):
                    x1 = float(item.get("x1", item.get("left", 0)))
                    y1 = float(item.get("y1", item.get("top", 0)))
                    x2 = float(item.get("x2", item.get("right", 0)))
                    y2 = float(item.get("y2", item.get("bottom", 0)))
                else:
                    x1, y1, x2, y2 = [float(v) for v in item[:4]]
                boxes.append((x1, y1, x2, y2))
            except Exception:
                continue
        return boxes

    def _estimate_person_boxes(self):
        """没有真实检测框时，根据人数生成几个占位框。

        这些框只用于 UI 演示，不参与报警判断。
        """
        boxes = []
        if self.person_count <= 0:
            return boxes

        if self.zone_hit:
            base_points = [(330, 75, 510, 360), (475, 95, 610, 365)]
        else:
            base_points = [(170, 85, 310, 335), (245, 95, 385, 350), (95, 110, 215, 345)]

        for idx in range(min(self.person_count, len(base_points))):
            boxes.append(base_points[idx])
        return boxes

    def _find_latest_alarm_screenshot(self):
        """查找最新报警截图。"""
        if self.latest_alarm_screenshot and Path(self.latest_alarm_screenshot).exists():
            return self.latest_alarm_screenshot
        if not VISION_PHOTOS_DIR.exists():
            return ""

        patterns = ("alarm_*.jpg", "alarm_*.png", "voice_result_*.jpg", "*.jpg")
        for pattern in patterns:
            candidates = list(VISION_PHOTOS_DIR.glob(pattern))
            if candidates:
                return str(max(candidates, key=lambda path: path.stat().st_mtime))
        return ""

    def _find_latest_photo_path(self):
        """查找视觉 photos 目录里最新的一张结果图。"""
        if VISION_LIVE_FRAME_PATH.exists():
            return str(VISION_LIVE_FRAME_PATH)
        if not VISION_PHOTOS_DIR.exists():
            return ""

        candidates = list(VISION_PHOTOS_DIR.glob("voice_result_*.jpg"))
        if not candidates:
            candidates = list(VISION_PHOTOS_DIR.glob("*.jpg"))
        if not candidates:
            return ""
        return str(max(candidates, key=lambda path: path.stat().st_mtime))

    def _read_latest_sensor_values_from_csv(self):
        """从 CSV 中读取最新一行传感器值。

        这里同时兼容两种来源：
        1. `rk3588/alarm_log.csv`
           真实主控或软件仿真器写入的系统运行记录。
        2. `vision/app/output/recodes/records.csv`
           软件仿真器和视觉模块写入的巡检记录。

        这样做的好处是：你还没买硬件时，UI 也能显示“仿真的传感器值”；
        以后接入真 STM32 后，只要主控继续写 alarm_log.csv，UI 代码不用重写。
        """
        for csv_path in (ALARM_LOG_PATH, VISION_RECORDS_CSV_PATH, LEGACY_VISION_RECORDS_CSV_PATH):
            if not csv_path.exists():
                continue

            with open(csv_path, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                continue

            latest = rows[-1]
            result = {}
            for key in ("temperature", "humidity", "voltage", "current", "temp_device", "smoke"):
                if key in latest and latest[key] not in ("", None):
                    try:
                        result[key] = float(latest[key]) if key != "smoke" else int(float(latest[key]))
                    except Exception:
                        pass
            if result:
                return result

        return {}

    def _read_threshold_config(self):
        """读取阈值配置 JSON。

        阈值文件相当于“报警规则表”。
        UI 保存阈值后，后端下次刷新就会按新规则判断，所以你在界面里
        改参数后马上能看到效果。
        """
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
        self.zone_hit = self.alarm_active and random.choice([True, False])
        self.intruded_people = self.person_count if self.zone_hit else 0
        self.alarm_frame_count = random.randint(0, 5) if self.alarm_active else 0
        self.confidence = round(random.uniform(0.72, 0.94), 2) if self.person_count else 0.0
        self.person_boxes = self._estimate_person_boxes()
        self.latest_alarm_screenshot = self._find_latest_alarm_screenshot()
        self.temperature = round(random.uniform(20, 65), 1)
        self.humidity = round(random.uniform(10, 90), 1)
        self.voltage = round(random.uniform(205, 245), 1)
        self.current = round(random.uniform(0.5, 12), 1)
        self.temp_device = round(random.uniform(25, 90), 1)
        self.smoke = random.choice([0, 0, 0, 1, 2])
        self.alarm_records = [
            {"time": "14:32:10", "reason": "烟雾报警"},
            {"time": "13:15:22", "reason": "人员进入禁区"},
        ]
