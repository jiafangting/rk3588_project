"""工业巡检项目的软件仿真器。

这个文件故意写成“小白也能顺着读”的迷你后端。
它不会打开真实摄像头，不会连接 STM32，也不需要 YOLO 模型。
它要模拟的是整个项目运行时最核心的四类东西：

1. STM32 传感器数据：
   环境温度、湿度、电压、电流、设备温度、烟雾状态。
2. 视觉状态：
   NORMAL / ABNORMAL / ALARM、检测人数、状态原因。
3. 决策逻辑：
   读取 rk3588/config.json 里的阈值，再判断是否报警。
4. 运行输出：
   socket 状态、CSV/JSONL 记录、给 UI 显示的实时预览图。

运行仿真后端：
    python scripts/run_software_simulation.py

再另开终端启动 UI：
    python ui/main_window.py

或者另开终端启动语音文本模式：
    python voice/voice_loop.py --text
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import random
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VISION_APP_DIR = PROJECT_ROOT / "vision" / "app"

# 真正的视觉模块里已经有 socket 服务端类。
# 仿真器复用这个类，是为了让 UI、语音模块、C 主控都继续使用同一套 JSON 协议。
# 这样以后从“假视觉”换成“真视觉”时，上层调用代码不用大改。
if str(VISION_APP_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_APP_DIR))

from vision_socket import VisionSocketServer  # noqa: E402，必须先把 vision/app 加进 sys.path 后才能导入


CONFIG_PATH = PROJECT_ROOT / "rk3588" / "config.json"
RK_ALARM_LOG_PATH = PROJECT_ROOT / "rk3588" / "alarm_log.csv"

VISION_OUTPUT_DIR = VISION_APP_DIR / "output"
VISION_PHOTOS_DIR = VISION_OUTPUT_DIR / "photos"
VISION_RECORDS_DIR = VISION_OUTPUT_DIR / "recodes"
VISION_RECORDS_CSV_PATH = VISION_RECORDS_DIR / "records.csv"
VISION_RECORDS_JSONL_PATH = VISION_RECORDS_DIR / "records.jsonl"
LIVE_FRAME_PATH = VISION_PHOTOS_DIR / "live_frame.jpg"


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


VISION_RECORD_FIELDS = [
    "timestamp",
    "status",
    "reason",
    "speech_text",
    "raw_path",
    "result_path",
    "person_count",
    "summary",
    "temperature",
    "humidity",
    "voltage",
    "current",
    "temp_device",
    "smoke",
    "zone_hit",
    "alarm_frame_count",
    "confidence",
    "alarm_type",
    "alarm_reason",
    "zone_name",
]

RK_LOG_FIELDS = [
    "timestamp",
    "level",
    "reason",
    "temperature",
    "humidity",
    "voltage",
    "current",
    "temp_device",
    "smoke",
    "vision_status",
    "person_count",
]


@dataclass
class SensorReading:
    """一帧模拟出来的 STM32 传感器数据。

    你可以这样理解：
    如果现在真的有 STM32，它每 500ms 或 1s 往 RK3588 发的就是这些字段。
    """

    temperature: float
    humidity: float
    voltage: float
    current: float
    temp_device: float
    smoke: int


@dataclass
class VisionReading:
    """一帧模拟出来的视觉识别结果。

    真实视觉模块后面也会通过 socket 发类似结构。
    当前阶段其他模块主要关心状态、人数、原因和图片路径，所以这里先保持简单。
    """

    status: str
    person_count: int
    reason: str
    zone_name: str = ""
    alarm_type: str = ""
    alarm_reason: str = ""


@dataclass
class Scenario:
    """仿真器里的一个具名场景。

    仿真器会按顺序切换这些场景，这样你不用硬件也能看到 UI 和语音模块的反应。
    每个场景提供一组传感器基础值和一组视觉基础值，运行时再加一点随机波动，
    避免界面看起来像卡住了一样。
    """

    name: str
    sensor: SensorReading
    vision: VisionReading


SCENARIOS = [
    Scenario(
        name="normal",
        sensor=SensorReading(temperature=28.0, humidity=55.0, voltage=220.0, current=3.2, temp_device=43.0, smoke=0),
        vision=VisionReading(status="NORMAL", person_count=1, reason="模拟巡检正常，检测到 1 名人员"),
    ),
    Scenario(
        name="abnormal_empty_area",
        sensor=SensorReading(temperature=31.0, humidity=48.0, voltage=221.0, current=3.5, temp_device=45.0, smoke=0),
        vision=VisionReading(status="ABNORMAL", person_count=0, reason="模拟画面中暂未检测到人员"),
    ),
    Scenario(
        name="smoke_alarm",
        sensor=SensorReading(temperature=35.0, humidity=52.0, voltage=222.0, current=4.0, temp_device=48.0, smoke=1),
        vision=VisionReading(status="NORMAL", person_count=1, reason="视觉正常，但模拟烟雾传感器报警"),
    ),
    Scenario(
        name="zone_alarm",
        sensor=SensorReading(temperature=30.0, humidity=50.0, voltage=219.0, current=3.8, temp_device=46.0, smoke=0),
        vision=VisionReading(
            status="ALARM",
            person_count=2,
            reason="模拟检测到人员进入右侧禁区",
            zone_name="right_third_zone",
            alarm_type="zone_intrusion",
            alarm_reason="人员进入右侧禁区",
        ),
    ),
    Scenario(
        name="current_alarm",
        sensor=SensorReading(temperature=32.0, humidity=54.0, voltage=218.0, current=11.5, temp_device=51.0, smoke=0),
        vision=VisionReading(status="NORMAL", person_count=1, reason="视觉正常，但模拟电流过载"),
    ),
]


def now_text() -> str:
    """生成当前时间字符串，给 CSV、JSONL 和 socket 消息共用。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_threshold() -> Dict[str, float]:
    """读取 rk3588/config.json，读取失败时回退到默认阈值。

    工业软件不能因为一个配置文件缺失就直接崩掉。
    所以这里会捕获异常，配置坏了就先用 DEFAULT_THRESHOLD，让系统继续跑。
    """

    threshold = dict(DEFAULT_THRESHOLD)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, default_value in DEFAULT_THRESHOLD.items():
            threshold[key] = data.get(key, default_value)
    except Exception as exc:
        print(f"[SIM] config.json 读取失败，使用默认阈值：{exc}")
    return threshold


def ensure_runtime_dirs() -> None:
    """创建 UI 和语音模块会用到的运行输出目录。"""

    VISION_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    VISION_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    RK_ALARM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def ensure_csv_header(path: Path, fields: List[str]) -> None:
    """如果 CSV 文件还不存在，就创建它并写入表头。

    这里不会随便覆盖旧日志，因为旧日志对学习和调试有用。
    仿真器只负责补齐缺失文件。
    """

    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()


def reset_runtime_outputs() -> None:
    """清空仿真器管理的运行输出文件。

    演示前建议加 --reset，这样不会被旧记录干扰。
    这里只清理 .gitignore 里忽略的运行输出，不会动源码。
    """

    ensure_runtime_dirs()
    with open(VISION_RECORDS_CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=VISION_RECORD_FIELDS).writeheader()
    VISION_RECORDS_JSONL_PATH.write_text("", encoding="utf-8")
    with open(RK_ALARM_LOG_PATH, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=RK_LOG_FIELDS).writeheader()


def add_noise(sensor: SensorReading) -> SensorReading:
    """给传感器数值加一点小随机波动，让仿真数据看起来更像实时读数。"""

    return SensorReading(
        temperature=round(sensor.temperature + random.uniform(-0.4, 0.4), 1),
        humidity=round(sensor.humidity + random.uniform(-1.5, 1.5), 1),
        voltage=round(sensor.voltage + random.uniform(-1.2, 1.2), 1),
        current=round(sensor.current + random.uniform(-0.15, 0.15), 2),
        temp_device=round(sensor.temp_device + random.uniform(-0.5, 0.5), 1),
        smoke=sensor.smoke,
    )


def decide_alarm(sensor: SensorReading, vision: VisionReading, threshold: Dict[str, float]) -> Tuple[str, str, int]:
    """把传感器结果和视觉结果融合成最终系统状态。

    返回值：
        status: NORMAL / ABNORMAL / ALARM
        reason: 中文原因，解释为什么是这个状态
        level: 0 表示正常，1 表示异常/预警，2 表示报警

    这就是 rk3588/thread_decision.c 的 Python 仿真版。
    你想理解整个项目，先读懂这个函数非常划算。
    """

    reasons = []

    if sensor.temperature > float(threshold["temp_max"]):
        reasons.append(f"环境温度过高 {sensor.temperature:.1f}°C")
    if sensor.humidity < float(threshold["humidity_min"]):
        reasons.append(f"湿度过低 {sensor.humidity:.1f}%")
    if sensor.humidity > float(threshold["humidity_max"]):
        reasons.append(f"湿度过高 {sensor.humidity:.1f}%")
    if sensor.voltage < float(threshold["voltage_min"]):
        reasons.append(f"电压过低 {sensor.voltage:.1f}V")
    if sensor.voltage > float(threshold["voltage_max"]):
        reasons.append(f"电压过高 {sensor.voltage:.1f}V")
    if sensor.current > float(threshold["current_max"]):
        reasons.append(f"电流过载 {sensor.current:.2f}A")
    if sensor.temp_device > float(threshold["temp_device_max"]):
        reasons.append(f"设备温度过高 {sensor.temp_device:.1f}°C")
    if int(threshold["smoke_alarm"]) and sensor.smoke:
        reasons.append("检测到烟雾")

    if vision.status == "ALARM":
        reasons.append(vision.alarm_reason or vision.reason or "视觉检测到报警")

    if reasons:
        return "ALARM", "；".join(reasons), 2
    if vision.status == "ABNORMAL":
        return "ABNORMAL", vision.reason or "视觉检测到异常", 1
    return "NORMAL", vision.reason or "系统正常", 0


class SoftwareInspectionSimulator:
    """一个不依赖硬件、但行为接近完整巡检系统的仿真后端。"""

    def __init__(
        self,
        interval: float,
        scenario_ticks: int,
        max_frames: int = 0,
        use_camera: bool = False,
        camera_index: int = 0,
        video_fps: float = 15.0,
    ):
        self.interval = interval
        self.scenario_ticks = max(1, scenario_ticks)
        self.max_frames = max(0, max_frames)
        self.use_camera = use_camera
        self.camera_index = camera_index
        self.video_fps = max(1.0, float(video_fps))
        self.camera_capture = None
        self.camera_failed = False
        self.camera_thread = None
        self.running = threading.Event()
        self.running.set()
        self.lock = threading.Lock()
        self.tick = 0
        self.current_scenario_index = 0
        self.latest_status: Dict[str, object] = {}
        self.socket_server = VisionSocketServer(command_callback=self.handle_socket_command)

    def start(self) -> None:
        """启动 socket 服务端和仿真主循环。"""

        ensure_runtime_dirs()
        ensure_csv_header(VISION_RECORDS_CSV_PATH, VISION_RECORD_FIELDS)
        ensure_csv_header(RK_ALARM_LOG_PATH, RK_LOG_FIELDS)

        if not self.socket_server.start():
            raise RuntimeError("视觉仿真 socket 启动失败")

        print("[SIM] 软件仿真系统已启动")
        if self.use_camera:
            print(f"[SIM] 已请求使用电脑摄像头，摄像头编号：{self.camera_index}")
            print(f"[SIM] 摄像头画面刷新率：{self.video_fps:.1f} FPS")
            print("[SIM] 如果摄像头打不开，会自动回退到纯绘制仿真画面")
            self.start_camera_writer()
        print("[SIM] 可另开终端运行：python ui/main_window.py")
        print("[SIM] 可另开终端运行：python voice/voice_loop.py --text")
        print("[SIM] 按 Ctrl+C 停止仿真")

        try:
            while self.running.is_set():
                self.update_once(record_reason="auto")
                if self.max_frames and self.tick >= self.max_frames:
                    break
                time.sleep(self.interval)
        finally:
            self.running.clear()
            if self.camera_thread is not None and self.camera_thread.is_alive():
                self.camera_thread.join(timeout=1.0)
            self.release_camera()
            self.socket_server.shutdown()
            print("[SIM] 软件仿真系统已停止")

    def update_once(self, record_reason: str) -> Dict[str, object]:
        """生成一帧仿真系统数据，并发布给其他模块。

        这里可以把它理解成“仿真系统的一次心跳”。
        每循环一次，就完成一整套流程：
        - 先读当前场景；
        - 再给传感器数据加一点随机波动；
        - 然后调用报警判断；
        - 再把结果写到日志、socket、预览图片；
        - 最后让 UI 和语音模块都能读到最新状态。

        一帧数据包含：
        - 一组类似 STM32 的传感器读数；
        - 一个类似视觉模块的识别结果；
        - 一个融合后的决策结果；
        - 一张给 UI 看的预览图；
        - 一份给 socket 客户端读取的状态 JSON。
        """

        threshold = load_threshold()
        scenario = self.get_current_scenario()
        sensor = add_noise(scenario.sensor)
        vision = scenario.vision
        final_status, final_reason, level = decide_alarm(sensor, vision, threshold)
        timestamp = now_text()

        live_frame = LIVE_FRAME_PATH
        payload = self.build_socket_payload(timestamp, final_status, final_reason, level, sensor, vision, live_frame)

        with self.lock:
            self.latest_status = payload
        self.socket_server.update_status(payload)

        # 没启用电脑摄像头，或者电脑摄像头已经失败时，才由低频仿真循环绘制画面。
        # 摄像头正常时，画面由独立线程高频刷新，避免视频两秒才动一下。
        if not self.use_camera or self.camera_failed:
            self.write_live_frame(final_status, final_reason, sensor, vision, timestamp, allow_camera=False)

        # 每一帧都写一行主控日志，UI 的传感器面板就能持续看到数据变化。
        self.append_rk_log(payload)

        # 视觉历史记录不用每帧都写，否则文件会刷得太快。
        # 这里选择在手动触发、报警、场景切换时写记录，既够用又不太吵。
        scenario_changed = self.tick % self.scenario_ticks == 0
        if record_reason == "manual" or level == 2 or scenario_changed:
            self.append_vision_record(payload, record_reason)

        self.print_status(payload, scenario.name)
        self.tick += 1
        if self.tick % self.scenario_ticks == 0:
            self.current_scenario_index = (self.current_scenario_index + 1) % len(SCENARIOS)
        return payload

    def get_current_scenario(self) -> Scenario:
        return SCENARIOS[self.current_scenario_index]

    def build_socket_payload(
        self,
        timestamp: str,
        status: str,
        reason: str,
        level: int,
        sensor: SensorReading,
        vision: VisionReading,
        live_frame: Path,
    ) -> Dict[str, object]:
        """构造返回给 UI、语音模块和 C 主控的 JSON 状态对象。"""

        return {
            "timestamp": timestamp,
            "status": status,
            "reason": reason,
            "level": level,
            "person_count": vision.person_count,
            "zone_name": vision.zone_name,
            "alarm_type": vision.alarm_type if vision.status == "ALARM" else "",
            "alarm_reason": reason if status == "ALARM" else "",
            "zone_hit": bool(vision.zone_name),
            "intruded_people": vision.person_count if vision.zone_name else 0,
            "alarm_frame_count": 5 if status == "ALARM" else (2 if status == "ABNORMAL" else 0),
            "confidence": 0.87 if vision.person_count else 0.0,
            "person_boxes": self.estimate_person_boxes(vision),
            "live_frame_path": str(live_frame),
            "result_path": str(live_frame),
            "temperature": sensor.temperature,
            "humidity": sensor.humidity,
            "voltage": sensor.voltage,
            "current": sensor.current,
            "temp_device": sensor.temp_device,
            "smoke": sensor.smoke,
            "summary": f"{status}: {reason}",
        }

    def estimate_person_boxes(self, vision: VisionReading) -> List[Tuple[int, int, int, int]]:
        """给 UI 演示用的人员框。

        真实视觉模块会从 YOLO 结果里拿框；软件仿真器没有跑 YOLO，
        所以根据人数和是否进入禁区生成几个固定框，方便 UI 做检测详情展示。
        """
        if vision.person_count <= 0:
            return []
        if vision.zone_name:
            candidates = [(500, 180, 540, 300), (548, 190, 590, 305)]
        else:
            candidates = [(285, 205, 325, 352), (235, 205, 275, 346), (335, 205, 375, 346)]
        return candidates[: vision.person_count]

    def handle_socket_command(self, cmd: str, payload: Dict[str, object]) -> Optional[Dict[str, object]]:
        """处理 UI、语音模块或 C 主控通过视觉 socket 发来的命令。

        这里就是“socket 怎么响应”的核心。
        UI、语音模块、甚至未来的 C 主控，只要发来一行 JSON 命令，
        仿真器就会根据 cmd 做不同事情。

        支持的命令：
        - get_status：由 VisionSocketServer 自己处理，返回最近一次状态；
        - trigger_inspection：让仿真器立刻生成并保存一条巡检记录；
        - reload_config：通知仿真器下一帧重新读取 rk3588/config.json；
        - shutdown：停止仿真器。
        """

        if cmd == "trigger_inspection":
            return self.update_once(record_reason="manual")
        if cmd == "reload_config":
            return {
                "ack": True,
                "cmd": cmd,
                "message": "仿真器已收到重新加载配置请求，下一帧会读取 config.json",
                "timestamp": now_text(),
            }
        if cmd == "shutdown":
            self.running.clear()
            return {"ack": True, "cmd": cmd, "message": "仿真器准备停止", "timestamp": now_text()}
        return None

    def append_vision_record(self, payload: Dict[str, object], record_reason: str) -> None:
        """追加一条视觉巡检记录，供 UI 和语音查询使用。

        这部分对应“日志怎么写”。
        你可以把 records.csv / records.jsonl 理解成视觉模块的历史档案：
        UI 会读它，语音模块也会读它，用来回答“最近一次报警是什么”。
        """

        row = {
            "timestamp": payload["timestamp"],
            "status": payload["status"],
            "reason": payload["reason"],
            "speech_text": f"仿真记录来源：{record_reason}",
            "raw_path": payload["live_frame_path"],
            "result_path": payload["result_path"],
            "person_count": payload["person_count"],
            "summary": payload["summary"],
            "temperature": payload["temperature"],
            "humidity": payload["humidity"],
            "voltage": payload["voltage"],
            "current": payload["current"],
            "temp_device": payload["temp_device"],
            "smoke": payload["smoke"],
            "zone_hit": payload["zone_hit"],
            "alarm_frame_count": payload["alarm_frame_count"],
            "confidence": payload["confidence"],
            "alarm_type": payload["alarm_type"],
            "alarm_reason": payload["alarm_reason"],
            "zone_name": payload["zone_name"],
        }
        with open(VISION_RECORDS_CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=VISION_RECORD_FIELDS).writerow(row)
        with open(VISION_RECORDS_JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def append_rk_log(self, payload: Dict[str, object]) -> None:
        """追加一条类似 RK3588 主控运行日志的记录。

        这部分就是“仿真版主控日志”。
        如果你打开 rk3588/alarm_log.csv，会看到每一帧的温湿度、电压、电流、烟雾、
        视觉状态都被记下来，这相当于给 UI 提供了第二份数据来源。
        """

        row = {
            "timestamp": payload["timestamp"],
            "level": payload["level"],
            "reason": payload["reason"],
            "temperature": payload["temperature"],
            "humidity": payload["humidity"],
            "voltage": payload["voltage"],
            "current": payload["current"],
            "temp_device": payload["temp_device"],
            "smoke": payload["smoke"],
            "vision_status": payload["status"],
            "person_count": payload["person_count"],
        }
        with open(RK_ALARM_LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=RK_LOG_FIELDS).writerow(row)

    def read_camera_frame(self, cv2):
        """读取一帧电脑摄像头画面。

        这个函数只在你传入 `--camera` 时启用。
        设计原则：
        - 摄像头能打开：用真实电脑摄像头当仿真视频背景；
        - 摄像头打不开：只提示一次，然后回退到软件绘制的仿真画面；
        - 摄像头由仿真后端独占，UI 不再抢摄像头，只读 live_frame.jpg。
        """

        if not self.use_camera or self.camera_failed:
            return None

        if self.camera_capture is None:
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                self.camera_failed = True
                print(f"[SIM] 摄像头 {self.camera_index} 打不开，已回退到仿真绘制画面")
                return None

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.camera_capture = cap
            print(f"[SIM] 摄像头 {self.camera_index} 已接入仿真视频")

        ok, frame = self.camera_capture.read()
        if ok and frame is not None:
            return frame

        self.camera_failed = True
        self.release_camera()
        print(f"[SIM] 摄像头 {self.camera_index} 读帧失败，已回退到仿真绘制画面")
        return None

    def start_camera_writer(self) -> None:
        """启动摄像头画面写入线程。

        这个线程只负责“视频流畅”：
        - 高频读取电脑摄像头；
        - 叠加禁区框和当前报警状态；
        - 写入 live_frame.jpg，供 UI 显示。

        主仿真循环仍然低频负责“状态变化、日志、socket”。
        两者拆开以后，视频不会再跟着状态刷新频率一起卡顿。
        """

        if self.camera_thread is not None and self.camera_thread.is_alive():
            return
        self.camera_thread = threading.Thread(target=self.camera_writer_loop, name="SimulationCameraWriter", daemon=True)
        self.camera_thread.start()

    def camera_writer_loop(self) -> None:
        """持续把电脑摄像头帧写成 UI 可读的 live_frame.jpg。"""

        try:
            import cv2
        except Exception as exc:
            self.camera_failed = True
            print(f"[SIM] OpenCV 不可用，无法接入电脑摄像头：{exc}")
            return

        sleep_seconds = 1.0 / self.video_fps
        while self.running.is_set() and not self.camera_failed:
            frame = self.read_camera_frame(cv2)
            if frame is None:
                break

            with self.lock:
                payload = dict(self.latest_status)

            if payload:
                sensor = SensorReading(
                    temperature=float(payload.get("temperature", 0.0)),
                    humidity=float(payload.get("humidity", 0.0)),
                    voltage=float(payload.get("voltage", 0.0)),
                    current=float(payload.get("current", 0.0)),
                    temp_device=float(payload.get("temp_device", 0.0)),
                    smoke=int(payload.get("smoke", 0)),
                )
                vision = VisionReading(
                    status=str(payload.get("status", "UNKNOWN")),
                    person_count=int(payload.get("person_count", 0)),
                    reason=str(payload.get("reason", "")),
                    zone_name=str(payload.get("zone_name", "")),
                    alarm_type=str(payload.get("alarm_type", "")),
                    alarm_reason=str(payload.get("alarm_reason", "")),
                )
                status = str(payload.get("status", "UNKNOWN"))
                reason = str(payload.get("reason", ""))
            else:
                sensor = SensorReading(temperature=0.0, humidity=0.0, voltage=0.0, current=0.0, temp_device=0.0, smoke=0)
                vision = VisionReading(status="UNKNOWN", person_count=0, reason="仿真状态准备中")
                status = "UNKNOWN"
                reason = "仿真状态准备中"

            self.write_live_frame(status, reason, sensor, vision, now_text(), camera_frame=frame, allow_camera=False)
            time.sleep(sleep_seconds)

    def release_camera(self) -> None:
        """释放电脑摄像头，避免程序退出后摄像头还被占用。"""

        if self.camera_capture is not None:
            try:
                self.camera_capture.release()
            except Exception:
                pass
            self.camera_capture = None

    def write_live_frame(
        self,
        status: str,
        reason: str,
        sensor: SensorReading,
        vision: VisionReading,
        timestamp: str,
        camera_frame=None,
        allow_camera: bool = True,
    ) -> Path:
        """画一张简单预览图，给 UI 的摄像头区域显示。

        UI 会用 cv2.imread() 读取图片路径。
        如果当前环境装了 OpenCV，就生成一张真正的 JPEG；
        如果没装 OpenCV，socket 和日志照样能跑，只是左侧预览图不会更新。
        """

        try:
            import cv2
            import numpy as np
        except Exception as exc:
            print(f"[SIM] OpenCV 不可用，跳过仿真画面生成：{exc}")
            return LIVE_FRAME_PATH

        color_map = {
            "NORMAL": (42, 150, 86),
            "ABNORMAL": (0, 165, 240),
            "ALARM": (96, 69, 233),
        }
        border_color = color_map.get(status, (180, 180, 180))
        if camera_frame is None and allow_camera:
            camera_frame = self.read_camera_frame(cv2)
        using_camera = camera_frame is not None

        if using_camera:
            frame = cv2.resize(camera_frame, (640, 400))
        else:
            frame = np.zeros((400, 640, 3), dtype=np.uint8)
            frame[:, :] = (30, 36, 48)

            # 画一个“车间监控画面”的背景，而不是文字状态面板。
            # 上半部分当作墙面，下半部分当作地面。
            cv2.rectangle(frame, (0, 0), (639, 135), (42, 49, 61), -1)
            cv2.rectangle(frame, (0, 135), (639, 399), (56, 60, 64), -1)
            for x in range(-80, 700, 80):
                cv2.line(frame, (x, 399), (x + 160, 135), (70, 74, 78), 1)
            for y in range(160, 400, 45):
                cv2.line(frame, (0, y), (639, y), (70, 74, 78), 1)

        # 画右侧禁区。正常时是淡黄色，报警时变红，方便一眼看出危险区域。
        zone_tl = (420, 80)
        zone_br = (630, 340)
        zone_overlay = frame.copy()
        zone_fill = (40, 80, 150) if status != "ALARM" else (60, 40, 180)
        cv2.rectangle(zone_overlay, zone_tl, zone_br, zone_fill, -1)
        frame = cv2.addWeighted(zone_overlay, 0.28, frame, 0.72, 0)
        cv2.rectangle(frame, zone_tl, zone_br, border_color, 3)
        for x in range(zone_tl[0] - 80, zone_br[0] + 80, 28):
            cv2.line(frame, (x, zone_br[1]), (x + 90, zone_tl[1]), border_color, 1)

        if not using_camera:
            # 没有电脑摄像头时，才画几台简化设备和模拟人员。
            cv2.rectangle(frame, (45, 105), (165, 255), (74, 87, 102), -1)
            cv2.rectangle(frame, (58, 122), (152, 170), (30, 120, 100), -1)
            cv2.circle(frame, (78, 215), 10, (40, 200, 120), -1)
            cv2.circle(frame, (112, 215), 10, (40, 170, 230), -1)
            cv2.rectangle(frame, (205, 210), (385, 250), (95, 99, 104), -1)
            cv2.rectangle(frame, (205, 250), (385, 268), (50, 54, 58), -1)
            cv2.circle(frame, (240, 270), 14, (35, 35, 35), -1)
            cv2.circle(frame, (350, 270), 14, (35, 35, 35), -1)
            cv2.rectangle(frame, (280, 145), (365, 205), (70, 95, 120), -1)
            cv2.circle(frame, (323, 174), 24, (35, 45, 55), 3)

            # 根据场景画人员。进入禁区时，人物会出现在右侧红框里。
            person_positions = []
            if vision.person_count > 0:
                if vision.zone_name:
                    person_positions.append((500, 235))
                    if vision.person_count > 1:
                        person_positions.append((555, 245))
                else:
                    person_positions.append((305, 290))
                    if vision.person_count > 1:
                        person_positions.append((250, 285))

            for px, py in person_positions[: max(0, vision.person_count)]:
                cv2.circle(frame, (px, py - 42), 14, (210, 190, 165), -1)
                cv2.rectangle(frame, (px - 12, py - 28), (px + 12, py + 28), (55, 145, 220), -1)
                cv2.line(frame, (px - 12, py - 8), (px - 34, py + 18), (55, 145, 220), 5)
                cv2.line(frame, (px + 12, py - 8), (px + 32, py + 18), (55, 145, 220), 5)
                cv2.line(frame, (px - 7, py + 28), (px - 18, py + 62), (40, 60, 80), 5)
                cv2.line(frame, (px + 7, py + 28), (px + 18, py + 62), (40, 60, 80), 5)

        # 烟雾报警时，在设备附近画几团灰色烟雾。
        if sensor.smoke:
            for sx, sy, radius in ((132, 88, 22), (164, 72, 28), (200, 92, 20), (184, 45, 18)):
                cv2.circle(frame, (sx, sy), radius, (155, 155, 155), -1)

        # 电流过载时，用黄色闪电线表示电气异常。
        if sensor.current > 10.0:
            points = np.array([(365, 145), (395, 180), (375, 180), (410, 230), (360, 175), (382, 175)], np.int32)
            cv2.polylines(frame, [points], True, (0, 220, 255), 4)

        # 如果是异常但不是报警，画一个淡黄色边框；报警由 UI 再做闪烁边框。
        if status == "ABNORMAL":
            cv2.rectangle(frame, (10, 10), (629, 389), border_color, 2)

        LIVE_FRAME_PATH.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(LIVE_FRAME_PATH), frame)
        return LIVE_FRAME_PATH

    def print_status(self, payload: Dict[str, object], scenario_name: str) -> None:
        """打印一行简短状态，方便你看到仿真循环还在运行。"""

        print(
            "[SIM] "
            f"{payload['timestamp']} | {scenario_name:<18} | {payload['status']:<8} | "
            f"T={payload['temperature']} H={payload['humidity']} V={payload['voltage']} "
            f"I={payload['current']} Smoke={payload['smoke']} | {payload['reason']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动无硬件工业巡检软件仿真系统")
    parser.add_argument("--interval", type=float, default=2.0, help="每隔多少秒生成一帧仿真数据")
    parser.add_argument("--scenario-ticks", type=int, default=4, help="每个场景停留多少帧后切到下一个场景")
    parser.add_argument("--frames", type=int, default=0, help="生成指定帧数后自动退出；0 表示一直运行")
    parser.add_argument("--camera", action="store_true", help="使用电脑摄像头作为仿真视频背景")
    parser.add_argument("--camera-index", type=int, default=0, help="电脑摄像头编号，默认 0")
    parser.add_argument("--video-fps", type=float, default=15.0, help="电脑摄像头画面刷新率，默认 15 FPS")
    parser.add_argument("--reset", action="store_true", help="启动前清空仿真输出日志")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_runtime_dirs()
    if args.reset:
        reset_runtime_outputs()

    simulator = SoftwareInspectionSimulator(
        interval=args.interval,
        scenario_ticks=args.scenario_ticks,
        max_frames=args.frames,
        use_camera=args.camera,
        camera_index=args.camera_index,
        video_fps=args.video_fps,
    )
    try:
        simulator.start()
    except KeyboardInterrupt:
        simulator.running.clear()


if __name__ == "__main__":
    main()
