"""alarm_voice_demo.py

================================================================
工业巡检系统 —— 视觉异常自动报警 + 语音查询 演示主脚本
================================================================

本脚本把答辩演示需要的全套链路整合到一个文件里,方便你一眼看懂流程,
也方便讲解。生产代码已经分散在 vision/ 和 voice/ 目录下的多个模块中,
这个文件不替换它们,只是把"演示用的最小闭环"集中展示出来。

整体流程:
    摄像头/图片
        └→ YOLO 推理
              └→ 4 种异常判断:
                    1. 禁区闯入 (person 中心点在禁区矩形内)
                    2. 越线检测 (person 中心点穿越警戒线)
                    3. 明火检测 (YOLO 输出 fire/flame 标签)
                    4. 画面遮挡 (整张图灰度均值 + 模糊度)
              └→ 触发后:
                    ├→ TTS 自动播报 ("检测到 XXX,请注意")
                    ├→ 保存截图    (output/alarm_xxx.jpg)
                    ├→ 写报警记录  (records.jsonl + records.csv)
                    └→ 串口指令    (通知 STM32 触发蜂鸣器,可选)
        └→ 语音查询(文本模式或对接 voice_loop.py)
              ├→ "有没有报警"        → 读 JSONL 统计今日条数
              ├→ "最近一次报警是什么"→ 读 JSONL 最后一条
              ├→ "报警几次了"        → 读 JSONL 计数
              └→ "帮我保存"          → 手动触发截图

运行方式:
    1) 摄像头模式(默认,演示禁区闯入 + 越线 + 遮挡):
       python alarm_voice_demo.py

    2) 图片测试模式(演示明火,需要事先准备一张火焰图片):
       python alarm_voice_demo.py --image test_fire.jpg

    3) 摄像头 + 文本语音查询并行(开两个终端):
       终端 1: python alarm_voice_demo.py
       终端 2: python alarm_voice_demo.py --query

================================================================
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


# ============================================================
# 第 1 部分:重要参数集中区
# ------------------------------------------------------------
# 答辩老师最爱问的就是"这个数怎么定的",所以把所有阈值都放这里,
# 方便你对着这一段讲解,也方便后期调参。
# ============================================================

# ---- 路径配置 ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "yolo11n" / "yolo11n.pt"
# 输出目录:截图和报警记录都放这里
OUTPUT_DIR = PROJECT_ROOT / "demo_output"
JSONL_PATH = OUTPUT_DIR / "alarm_records.jsonl"   # 主日志,程序读这个
CSV_PATH = OUTPUT_DIR / "alarm_records.csv"       # 备份,Excel 打开看

# ---- 摄像头参数 ----
CAMERA_INDEX = 0          # 摄像头编号,笔记本一般 0 是内置摄像头
PREVIEW_WIDTH = 640       # 推理用的图像宽,降到 640 能显著加速
PREVIEW_HEIGHT = 480
YOLO_CONF = 0.30          # YOLO 置信度阈值,越低越敏感越容易误报
MIN_PERSON_SCORE = 0.50   # 把"person"算成有效检测的最低置信度

# ---- 禁区参数(矩形) ----
# 重要:坐标系是 OpenCV 的,左上角 (0,0),x 向右,y 向下
# 这里给的是基于 PREVIEW_WIDTH x PREVIEW_HEIGHT (640x480) 的坐标
HAZARD_ZONE = {
    "name": "right_zone",      # 禁区名称,会出现在播报里
    "top_left": (420, 80),     # 矩形左上角
    "bottom_right": (630, 420),  # 矩形右下角
}

# ---- 越线检测参数 ----
# 一条线段,人员中心点 y 坐标从线上方变到下方(或相反)就算越线
LINE_CROSSING = {
    "name": "front_line",
    "point_a": (50, 300),      # 线段起点
    "point_b": (590, 300),     # 线段终点
    # direction:
    #   "down_to_up"  仅当从下往上越过才报警(防止从外进入)
    #   "up_to_down"  仅当从上往下越过才报警(防止离开)
    #   "both"        两个方向都报警
    "direction": "both",
}

# ---- 明火检测参数 ----
# yolo11n.pt 通用模型不识别 fire/flame,所以默认走"备用方案":
#   ENABLE_FIRE_MOCK=True 时,在图片测试模式下强制当作识别到明火
# 你后面换成 fire 专用模型时,把 ENABLE_FIRE_MOCK 设为 False 即可
FIRE_LABELS = {"fire", "flame"}    # 模型输出这些标签时算明火
ENABLE_FIRE_MOCK = True            # 演示开关:图片模式下若没识别到 fire,也强制触发

# ---- 画面遮挡参数 ----
# 两个判定指标,任意一个超阈值就算遮挡
# 1. 整张图灰度均值过低 → 摄像头被布盖住或没光
# 2. 拉普拉斯方差过低 → 整张图模糊(失焦或被脏污遮挡)
OCCLUSION_MEAN_THRESHOLD = 25.0    # 灰度均值低于这个值算太黑
OCCLUSION_BLUR_THRESHOLD = 50.0    # 拉普拉斯方差低于这个值算太糊
OCCLUSION_FRAMES_REQUIRED = 15     # 连续多少帧异常才报警,防误报

# ---- 报警节流参数 ----
# 防止同一种异常被疯狂播报和写入
ALARM_COOLDOWN_SECONDS = 8         # 同类报警最少间隔多少秒才再播一次
ALARM_FRAMES_REQUIRED = 3          # 连续多少帧检测到异常才正式触发

# ---- 串口参数(发给 STM32 触发蜂鸣器) ----
ENABLE_SERIAL = False              # 没接 STM32 时设 False,避免报错
SERIAL_PORT = "COM5"               # Windows 上是 COM5,Linux 上是 /dev/ttyUSB0
SERIAL_BAUDRATE = 115200

# ---- TTS 参数 ----
TTS_RATE = 180                     # 语速,数字越大说得越快
TTS_VOLUME = 1.0


# ============================================================
# 第 2 部分:工具函数
# ============================================================

def ensure_output_dir():
    """确保输出目录存在,不存在就建。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def now_text():
    """返回当前时间的字符串,格式: 2026-05-08 14:32:05"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_filename():
    """返回适合当文件名的时间字符串,格式: 20260508_143205"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_text(text: str) -> str:
    """去掉空格和标点,方便做关键词匹配。"""
    if not text:
        return ""
    for ch in " ,。!?,.、:;:;\"'\t\r\n":
        text = text.replace(ch, "")
    return text


# ============================================================
# 第 3 部分:TTS 后台播报
# ------------------------------------------------------------
# 用一个线程后台播报,避免阻塞主流程。
# 优先 pyttsx3,失败时退回 PowerShell。
# ============================================================

class TTSBroadcaster:
    """后台 TTS 播报器。所有播报都丢进队列,后台线程顺序播。"""

    def __init__(self, rate=TTS_RATE, volume=TTS_VOLUME):
        self.rate = rate
        self.volume = volume
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def speak(self, text: str):
        """把一句话排入队列。"""
        if text:
            self._queue.put(text)

    def stop(self):
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._running = False

    def _worker(self):
        while True:
            text = self._queue.get()
            if text is None:
                break
            self._speak_once(text)

    def _speak_once(self, text: str):
        print(f"[TTS] {text}")
        try:
            import pyttsx3
            engine = pyttsx3.init("sapi5")
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
            engine.say(text)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass
        except Exception as exc:
            # pyttsx3 不行就用 PowerShell 兜底,Windows 自带,不需要装
            print(f"[TTS] pyttsx3 失败,改用 PowerShell:{exc}")
            self._speak_with_powershell(text)

    def _speak_with_powershell(self, text: str):
        import subprocess
        safe = text.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak('{safe}'); $s.Dispose()"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
        except Exception as exc:
            print(f"[TTS] PowerShell 也失败:{exc}")


# ============================================================
# 第 4 部分:报警记录读写
# ------------------------------------------------------------
# JSONL 是主存储,每行一个 JSON 对象,程序读这个。
# CSV 是给 Excel 看的,内容相同,只是格式不同。
# ============================================================

def append_jsonl(record: dict):
    """追加一条记录到 JSONL。"""
    ensure_output_dir()
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_csv(record: dict):
    """追加一条记录到 CSV。"""
    ensure_output_dir()
    file_exists = CSV_PATH.exists()
    # 把 list/dict 类型的字段转成 JSON 字符串,免得 CSV 列错乱
    row = {
        k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
        for k, v in record.items()
    }
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def save_record(record: dict):
    """同时写 JSONL 和 CSV。"""
    append_jsonl(record)
    append_csv(record)


def load_today_alarm_records():
    """读取今日所有报警记录,返回 list[dict]。
    给"语音查询"模块用。
    """
    if not JSONL_PATH.exists():
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    records = []
    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = str(obj.get("timestamp", ""))
            if ts.startswith(today):
                records.append(obj)
    return records


# ============================================================
# 第 5 部分:4 种异常检测
# ============================================================

@dataclass
class DetectionResult:
    """单帧检测结果。"""
    persons: list = field(default_factory=list)   # 每个人的 (cx, cy, score)
    fire_detected: bool = False
    fire_score: float = 0.0
    occluded: bool = False
    occlusion_reason: str = ""


def point_in_rect(point, top_left, bottom_right):
    """判断点是否在矩形内。"""
    x, y = point
    x1, y1 = top_left
    x2, y2 = bottom_right
    return x1 <= x <= x2 and y1 <= y <= y2


def segment_side(point, line_a, line_b):
    """点在有向线段的哪一侧。
    返回:>0 表示一侧,<0 表示另一侧,=0 表示在线上。
    用叉积判断,几何里的标准做法。
    """
    ax, ay = line_a
    bx, by = line_b
    px, py = point
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def check_zone_intrusion(persons, zone):
    """检测 1:禁区闯入。
    只要任何一个人的中心点落在禁区矩形内就算闯入。
    """
    intruded = []
    for cx, cy, score in persons:
        if point_in_rect((cx, cy), zone["top_left"], zone["bottom_right"]):
            intruded.append((cx, cy, score))
    return len(intruded) > 0, len(intruded)


def check_line_crossing(person_id_to_history, line_config):
    """检测 2:越线检测。
    需要"上一帧 person 中心点的位置"才能判断是否越过线,
    所以用一个简单的轨迹历史 person_id_to_history。
    这里为简化起见,不做多目标跟踪,
    只用"当前帧最像上一帧那个人"的简单匹配(就近)。
    """
    # 这个函数的实现见 process_frame,这里只放工具
    pass


def check_fire(labels, scores):
    """检测 3:明火。
    模型输出标签里有 fire/flame 就算。
    """
    for label, score in zip(labels, scores):
        if label.lower() in FIRE_LABELS and score >= YOLO_CONF:
            return True, label, score
    return False, "", 0.0


def check_occlusion(frame):
    """检测 4:画面遮挡。
    指标 1:灰度均值过低 → 太黑
    指标 2:拉普拉斯方差过低 → 太糊
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean = float(np.mean(gray))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if mean < OCCLUSION_MEAN_THRESHOLD:
        return True, f"画面过暗 (亮度={mean:.1f})"
    if blur < OCCLUSION_BLUR_THRESHOLD:
        return True, f"画面模糊 (模糊度={blur:.1f})"
    return False, ""


# ============================================================
# 第 6 部分:报警管理器(节流 + 触发)
# ------------------------------------------------------------
# 同类报警在 ALARM_COOLDOWN_SECONDS 秒内只触发一次。
# 连续 ALARM_FRAMES_REQUIRED 帧检测到才认定有效,防误报。
# ============================================================

class AlarmManager:
    """统一管理 4 种报警的触发、播报和保存。"""

    def __init__(self, tts: TTSBroadcaster, serial_port=None):
        self.tts = tts
        self.serial_port = serial_port

        # 每种报警单独维护一个最近触发时间,用来做冷却
        self.last_trigger_time = {
            "zone": 0.0,
            "line": 0.0,
            "fire": 0.0,
            "occlusion": 0.0,
        }
        # 每种报警的连续帧计数器
        self.continuous_count = {
            "zone": 0,
            "line": 0,
            "fire": 0,
            "occlusion": 0,
        }

    def _can_trigger(self, alarm_type: str) -> bool:
        """判断这种报警是否可以触发(冷却时间过了没)。"""
        elapsed = time.time() - self.last_trigger_time[alarm_type]
        return elapsed >= ALARM_COOLDOWN_SECONDS

    def update_continuous(self, alarm_type: str, condition_met: bool) -> bool:
        """更新连续帧计数器,返回是否达到稳定触发条件。"""
        if condition_met:
            self.continuous_count[alarm_type] += 1
        else:
            self.continuous_count[alarm_type] = 0
        return self.continuous_count[alarm_type] >= ALARM_FRAMES_REQUIRED

    def trigger(self, alarm_type: str, alarm_name_cn: str, reason: str,
                preview_frame, result_image):
        """触发一次报警:播报 + 截图 + 写日志 + 串口。"""
        if not self._can_trigger(alarm_type):
            return None

        self.last_trigger_time[alarm_type] = time.time()
        timestamp = now_text()
        filename_ts = now_filename()

        # ---- 1. 保存截图 ----
        ensure_output_dir()
        raw_path = OUTPUT_DIR / f"alarm_{alarm_type}_{filename_ts}_raw.jpg"
        result_path = OUTPUT_DIR / f"alarm_{alarm_type}_{filename_ts}_result.jpg"
        cv2.imwrite(str(raw_path), preview_frame)
        cv2.imwrite(str(result_path), result_image)

        # ---- 2. 写报警记录 ----
        record = {
            "timestamp": timestamp,
            "alarm_type": alarm_type,           # zone / line / fire / occlusion
            "alarm_name": alarm_name_cn,        # 中文名,给人看
            "reason": reason,                   # 详细原因
            "raw_path": str(raw_path),
            "result_path": str(result_path),
        }
        save_record(record)

        # ---- 3. TTS 播报 ----
        speech = f"检测到{alarm_name_cn},请注意。{reason}"
        self.tts.speak(speech)

        # ---- 4. 串口通知 STM32(可选) ----
        if self.serial_port is not None:
            try:
                msg = json.dumps(
                    {"cmd": "alarm", "type": alarm_type, "time": timestamp},
                    ensure_ascii=False,
                ) + "\n"
                self.serial_port.write(msg.encode("utf-8"))
            except Exception as exc:
                print(f"[SERIAL] 发送失败:{exc}")

        # ---- 5. 控制台打印,方便调试 ----
        print(f"[ALARM] {timestamp} | {alarm_name_cn} | {reason}")
        print(f"        截图: {result_path}")

        return record


# ============================================================
# 第 7 部分:画面绘制(把检测结果画到画面上)
# ============================================================

def draw_zone(image, zone, intruded: bool):
    """画禁区矩形。闯入时变红加粗。"""
    color = (0, 0, 255) if intruded else (0, 255, 255)  # BGR: 红 / 黄
    cv2.rectangle(image, zone["top_left"], zone["bottom_right"], color, 3)
    cv2.putText(image, f"ZONE: {zone['name']}",
                (zone["top_left"][0], max(20, zone["top_left"][1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_line(image, line, crossed: bool):
    """画警戒线。被穿越时变红。"""
    color = (0, 0, 255) if crossed else (0, 255, 0)
    cv2.line(image, line["point_a"], line["point_b"], color, 3)
    cv2.putText(image, f"LINE: {line['name']}",
                (line["point_a"][0], line["point_a"][1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_persons(image, persons):
    """画每个人的中心点(小圆圈)。"""
    for cx, cy, score in persons:
        cv2.circle(image, (int(cx), int(cy)), 8, (255, 255, 0), 2)


def draw_status_panel(image, status_lines):
    """左上角状态面板,显示每种检测的状态。"""
    x1, y1 = 10, 10
    panel_w, panel_h = 300, 30 + 25 * len(status_lines)
    overlay = image.copy()
    cv2.rectangle(overlay, (x1, y1), (x1 + panel_w, y1 + panel_h),
                  (40, 40, 40), -1)
    cv2.addWeighted(overlay, 0.6, image, 0.4, 0, image)

    y = y1 + 25
    for text, is_alarm in status_lines:
        color = (0, 0, 255) if is_alarm else (0, 255, 0)
        cv2.putText(image, text, (x1 + 10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        y += 25


# ============================================================
# 第 8 部分:摄像头主流程
# ============================================================

def run_camera_mode(args):
    """摄像头模式:连续检测 + 自动报警。"""
    print("[INIT] 加载 YOLO 模型...")
    from ultralytics import YOLO
    model = YOLO(str(MODEL_PATH))
    print(f"[INIT] 模型就绪: {MODEL_PATH}")

    print(f"[INIT] 打开摄像头 {CAMERA_INDEX}...")
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"[ERROR] 摄像头打不开: {CAMERA_INDEX}")
        return

    # 串口(可选)
    serial_port = None
    if ENABLE_SERIAL:
        try:
            import serial
            serial_port = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
            print(f"[INIT] 串口就绪: {SERIAL_PORT}")
        except Exception as exc:
            print(f"[INIT] 串口初始化失败: {exc} (继续运行)")

    tts = TTSBroadcaster()
    tts.start()
    tts.speak("视觉巡检系统启动")

    alarm_mgr = AlarmManager(tts, serial_port=serial_port)

    # 越线检测需要记录人员上一帧位置。
    # 简化处理:只跟踪"画面里第一个 person",答辩演示足够。
    # 工业级要做多目标跟踪(ByteTrack/DeepSORT),代码量翻倍,这里不展开。
    last_person_center = None

    window = "Industrial Inspection Demo"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 960, 720)

    print("[RUN] 按 q 退出,按 s 手动保存当前画面")
    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("[WARN] 摄像头读取失败,跳过")
                time.sleep(0.05)
                continue

            preview = cv2.resize(frame, (PREVIEW_WIDTH, PREVIEW_HEIGHT))
            result_image = preview.copy()

            # ---- 检测 4:画面遮挡(在推理前判断,推理就跳过) ----
            occluded, occ_reason = check_occlusion(preview)
            if alarm_mgr.update_continuous("occlusion", occluded):
                alarm_mgr.trigger("occlusion", "画面遮挡", occ_reason,
                                  preview, result_image)

            # ---- YOLO 推理 ----
            yolo_result = model.predict(preview, conf=YOLO_CONF, verbose=False)[0]
            names = yolo_result.names if hasattr(yolo_result, "names") else {}
            boxes = yolo_result.boxes

            persons = []
            labels = []
            scores = []
            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    score = float(box.conf[0].item())
                    label = names.get(cls_id, str(cls_id)).lower()
                    labels.append(label)
                    scores.append(score)

                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2

                    if label == "person" and score >= MIN_PERSON_SCORE:
                        persons.append((cx, cy, score))
                        # 在结果图上画人员框
                        cv2.rectangle(result_image,
                                      (int(x1), int(y1)), (int(x2), int(y2)),
                                      (0, 255, 0), 2)
                        cv2.putText(result_image, f"person {score:.2f}",
                                    (int(x1), int(y1) - 6),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (0, 255, 0), 2)

            # ---- 检测 1:禁区闯入 ----
            zone_intruded, intruded_count = check_zone_intrusion(persons, HAZARD_ZONE)
            if alarm_mgr.update_continuous("zone", zone_intruded):
                alarm_mgr.trigger("zone", "人员进入禁区",
                                  f"禁区 {HAZARD_ZONE['name']} 内有 {intruded_count} 人",
                                  preview, result_image)

            # ---- 检测 2:越线检测 ----
            # 简化版:看最显眼的那个人(置信度最高的)
            line_crossed = False
            line_reason = ""
            if persons:
                # 取置信度最高的人作为代表
                main_person = max(persons, key=lambda p: p[2])
                cur_center = (main_person[0], main_person[1])

                if last_person_center is not None:
                    side_now = segment_side(cur_center,
                                            LINE_CROSSING["point_a"],
                                            LINE_CROSSING["point_b"])
                    side_prev = segment_side(last_person_center,
                                             LINE_CROSSING["point_a"],
                                             LINE_CROSSING["point_b"])
                    # 两侧符号变了 = 越过线
                    if side_now * side_prev < 0:
                        direction = LINE_CROSSING["direction"]
                        # 简化判断:这里 both 总是触发,
                        # 单向需要根据 side 符号决定,演示用 both 即可
                        if direction == "both":
                            line_crossed = True
                            line_reason = "人员穿越警戒线"
                        elif direction == "down_to_up" and side_prev > 0 and side_now < 0:
                            line_crossed = True
                            line_reason = "人员由下向上穿越警戒线"
                        elif direction == "up_to_down" and side_prev < 0 and side_now > 0:
                            line_crossed = True
                            line_reason = "人员由上向下穿越警戒线"

                last_person_center = cur_center
            else:
                last_person_center = None

            if alarm_mgr.update_continuous("line", line_crossed):
                alarm_mgr.trigger("line", "越线警告", line_reason,
                                  preview, result_image)

            # ---- 检测 3:明火 ----
            fire_detected, fire_label, fire_score = check_fire(labels, scores)
            if alarm_mgr.update_continuous("fire", fire_detected):
                alarm_mgr.trigger("fire", "检测到明火",
                                  f"标签={fire_label}, 置信度={fire_score:.2f}",
                                  preview, result_image)

            # ---- 在画面上绘制辅助信息 ----
            draw_zone(result_image, HAZARD_ZONE, zone_intruded)
            draw_line(result_image, LINE_CROSSING, line_crossed)
            draw_persons(result_image, persons)

            cv2.putText(result_image, now_text(),
                        (10, PREVIEW_HEIGHT - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            status_lines = [
                (f"Persons: {len(persons)}", False),
                (f"Zone: {'INTRUDED' if zone_intruded else 'clear'}", zone_intruded),
                (f"Line: {'CROSSED' if line_crossed else 'clear'}", line_crossed),
                (f"Fire: {'DETECTED' if fire_detected else 'clear'}", fire_detected),
                (f"Occlusion: {'YES' if occluded else 'no'}", occluded),
            ]
            draw_status_panel(result_image, status_lines)

            cv2.imshow(window, result_image)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                # 手动保存,对应"帮我保存"语音指令
                ts = now_filename()
                manual_path = OUTPUT_DIR / f"manual_{ts}.jpg"
                ensure_output_dir()
                cv2.imwrite(str(manual_path), result_image)
                save_record({
                    "timestamp": now_text(),
                    "alarm_type": "manual",
                    "alarm_name": "手动保存",
                    "reason": "用户手动触发",
                    "raw_path": "",
                    "result_path": str(manual_path),
                })
                tts.speak("已保存当前巡检记录")
                print(f"[MANUAL] 已保存: {manual_path}")

    except KeyboardInterrupt:
        print("[RUN] Ctrl+C 退出")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass
        tts.stop()
        print("[RUN] 结束")


# ============================================================
# 第 9 部分:图片测试模式(演示明火,因为不能真的点火)
# ============================================================

def run_image_mode(args):
    """图片测试模式:读一张图,跑检测,触发报警链路。
    主要是演示明火检测,因为不可能在答辩现场真的点火。
    """
    img_path = Path(args.image)
    if not img_path.exists():
        print(f"[ERROR] 图片不存在: {img_path}")
        return

    print(f"[IMAGE] 加载图片: {img_path}")
    frame = cv2.imread(str(img_path))
    if frame is None:
        print("[ERROR] 图片读取失败,可能格式不支持")
        return

    preview = cv2.resize(frame, (PREVIEW_WIDTH, PREVIEW_HEIGHT))
    result_image = preview.copy()

    print("[IMAGE] 加载 YOLO 模型...")
    from ultralytics import YOLO
    model = YOLO(str(MODEL_PATH))

    tts = TTSBroadcaster()
    tts.start()

    alarm_mgr = AlarmManager(tts)
    # 图片模式下,把连续帧门槛改成 1 帧,因为只跑一张图
    alarm_mgr.continuous_count["fire"] = ALARM_FRAMES_REQUIRED

    yolo_result = model.predict(preview, conf=YOLO_CONF, verbose=False)[0]
    names = yolo_result.names if hasattr(yolo_result, "names") else {}
    labels = []
    scores = []
    if yolo_result.boxes is not None:
        for box in yolo_result.boxes:
            cls_id = int(box.cls[0].item())
            labels.append(names.get(cls_id, str(cls_id)).lower())
            scores.append(float(box.conf[0].item()))

    fire_detected, fire_label, fire_score = check_fire(labels, scores)

    # ----- 兜底:模型识别不出来,但开了 mock 开关时强制触发 -----
    if not fire_detected and ENABLE_FIRE_MOCK:
        print("[IMAGE] 模型未识别到 fire/flame,启用演示兜底(强制触发)")
        fire_detected = True
        fire_label = "fire(mock)"
        fire_score = 0.99

    if fire_detected:
        alarm_mgr.trigger("fire", "检测到明火",
                          f"标签={fire_label}, 置信度={fire_score:.2f}",
                          preview, result_image)
    else:
        print("[IMAGE] 未检测到明火")

    # 等播报念完
    time.sleep(2)
    tts.stop()


# ============================================================
# 第 10 部分:语音查询模式(文本输入版)
# ------------------------------------------------------------
# 真实部署时,这部分由 voice/voice_loop.py 接 ASR 自动驱动。
# 这里给一个文本输入版本,方便你不用麦克风也能演示完整流程。
# ============================================================

def reply_for_query(text: str) -> str:
    """根据用户问的话,生成 TTS 回复。"""
    t = normalize_text(text)
    records = load_today_alarm_records()

    # 不同关键词路由到不同回答
    if any(k in t for k in ["有没有报警", "报警记录", "报警有几条"]):
        if not records:
            return "今天还没有报警记录"
        return f"今天共有 {len(records)} 条报警记录"

    if any(k in t for k in ["最近一次报警", "最近报警", "最后一条报警"]):
        if not records:
            return "今天还没有报警记录"
        last = records[-1]
        # 把时间戳里的"小时:分钟"提出来念,听起来更自然
        ts = str(last.get("timestamp", ""))
        time_part = ts.split(" ")[1][:5] if " " in ts else ts
        hh, mm = time_part.split(":") if ":" in time_part else (time_part, "00")
        return f"{hh}点{mm}分,{last.get('alarm_name', '未知报警')},{last.get('reason', '')}"

    if any(k in t for k in ["报警几次", "报警次数", "报了几次"]):
        return f"当前已报警 {len(records)} 次"

    if any(k in t for k in ["保存一下", "帮我保存", "保存当前画面"]):
        # 这里只能给确认回复,真截图要在摄像头主流程里(按 s)
        return "已收到保存请求,请在摄像头窗口按 s 保存当前画面"

    return "我没有理解这条指令,你可以问我:有没有报警,最近一次报警是什么,报警几次了"


def run_query_mode(args):
    """文本输入版语音查询循环。"""
    print("=" * 50)
    print("语音查询模式(文本模拟)")
    print("可问:有没有报警 / 最近一次报警是什么 / 报警几次了 / 帮我保存")
    print("输入 q 退出")
    print("=" * 50)

    tts = TTSBroadcaster()
    tts.start()
    tts.speak("语音查询模式已启动")

    try:
        while True:
            try:
                text = input(">>> ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text.lower() in ("q", "quit", "exit"):
                break

            reply = reply_for_query(text)
            print(f"[REPLY] {reply}")
            tts.speak(reply)
    finally:
        tts.stop()


# ============================================================
# 第 11 部分:入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="工业巡检视觉报警 + 语音查询演示"
    )
    parser.add_argument(
        "--image",
        help="给一张图片,走图片测试模式(演示明火)。例如:--image test_fire.jpg",
    )
    parser.add_argument(
        "--query",
        action="store_true",
        help="进入语音查询模式(文本输入版)",
    )
    args = parser.parse_args()

    ensure_output_dir()

    if args.query:
        run_query_mode(args)
    elif args.image:
        run_image_mode(args)
    else:
        run_camera_mode(args)


if __name__ == "__main__":
    main()
