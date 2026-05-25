"""视觉核心工具集合。

这个文件是视觉模块最重要的“工具箱”，负责把一条视频流变成最终结果。

它包含四类能力：
1. 摄像头输入
2. YOLO 推理
3. 结果解析和决策
4. 语音播报

整体流程：
- `open_camera()` 打开摄像头；
- `read_one_frame()` 读取一帧；
- `preprocess_frame()` 统一尺寸；
- `load_model()` 加载 YOLO；
- `run_inference()` 运行推理；
- `parse_result()` 把推理结果转成人能读懂的文本；
- `build_decision()` 做稳定帧和报警判断；
- `build_speech_text()` 把状态转成播报文本；
- `speak_text()` 把播报内容送给语音线程。

关键配置参数：
- `YOLO_CONF`：YOLO 置信度阈值
- `MIN_PERSON_SCORE`：识别“人员”时的最低分数
- `PREVIEW_WIDTH` / `PREVIEW_HEIGHT`：预处理画面尺寸
- `TTS_RATE` / `TTS_VOLUME`：语音速度和音量
"""

import os
import queue
import subprocess
import sys
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import pyttsx3
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = PROJECT_ROOT / "voice"
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

try:
    from voice_broadcast import request_tts
except Exception:
    request_tts = None

from config import (
    MIN_PERSON_SCORE,
    PREVIEW_HEIGHT,
    PREVIEW_WIDTH,
    TTS_RATE,
    TTS_VOLUME,
    YOLO_CONF,
)


ALARM_LABELS = {
    "fire": "明火",
    "flame": "明火",
    "smoke": "烟雾",
}

LABEL_CN = {
    "person": "人员",
    "fire": "明火",
    "flame": "明火",
    "smoke": "烟雾",
}

LABEL_DISPLAY = {
    "person": "person",
    "fire": "fire",
    "flame": "flame",
    "smoke": "smoke",
}


def label_to_cn(label):
    return LABEL_CN.get(label, label)


def label_to_display(label):
    return LABEL_DISPLAY.get(label, str(label))


def open_camera(camera_index=0):
    """打开摄像头。

    参数：
    - `camera_index`：摄像头编号，默认 0

    返回值：
    - OpenCV 的 `VideoCapture` 对象

    原理：
    - 先尝试 Windows 常见的 DSHOW 后端；
    - 如果失败，再退回默认后端；
    - 如果还是失败，直接抛异常，让主流程知道摄像头不可用。
    """
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Camera open failed, index={camera_index}")
    return cap


def read_one_frame(cap):
    ret, frame = cap.read()
    if not ret or frame is None:
        raise RuntimeError("Failed to read camera frame")
    return frame


def preprocess_frame(frame):
    """把原始画面缩放到模型输入尺寸。

    这是推理前的标准化步骤。统一尺寸以后，模型更容易稳定处理，
    同时也能减少不必要的计算量。
    """
    return cv2.resize(frame, (PREVIEW_WIDTH, PREVIEW_HEIGHT))


def load_model(model_path="yolo11n.pt"):
    """加载 YOLO 模型。

    参数：
    - `model_path`：模型文件路径，既可以是本地权重，也可以是 Ultralytics 预置名

    返回值：
    - `YOLO` 模型对象

    原理：
    - 如果本地文件存在，就直接读取本地权重；
    - 如果不存在，YOLO 可能会尝试联网获取；
    - 这也是为什么部署时一般建议提前放好权重文件。
    """
    if os.path.exists(model_path):
        print(f"Using local model: {model_path}")
    else:
        print(f"Local model not found, YOLO may try to download: {model_path}")
    return YOLO(model_path)


def run_inference(model, frame):
    """执行一次 YOLO 推理。

    参数：
    - `model`：已加载的 YOLO 模型
    - `frame`：输入图像

    返回值：
    - 第一帧推理结果对象

    关键参数：
    - `YOLO_CONF`：置信度阈值，越高越严格，误报更少，但漏检可能更多
    """
    results = model.predict(frame, conf=YOLO_CONF, verbose=False)
    return results[0]


def parse_result(result):
    """把 YOLO 原始结果解析成更好用的三份数据。

    参数：
    - `result`：`model.predict()` 返回的一帧检测结果

    返回值：
    - `summary`：适合打印/播报的人类可读摘要列表
    - `labels`：检测到的类别名列表
    - `scores`：每个类别对应的置信度列表

    流程：
    1. 先拿到类别映射表 `names` 和框列表 `boxes`；
    2. 如果没有检测到框，就返回“没有检测到目标”；
    3. 遍历每个框，取出类别、置信度和标签；
    4. 对 person 类单独做一次有效性筛选；
    5. 生成中文摘要，供 UI / 语音使用。

    原理：
    - YOLO 给出来的是“机器能懂的框”；
    - 这里把它变成“人能懂的文本”和“后续逻辑能继续处理的数组”。
    """
    names = result.names if hasattr(result, "names") else {}
    boxes = result.boxes
    summary = []
    labels = []
    scores = []

    if boxes is None or len(boxes) == 0:
        summary.append("没有检测到目标")
        return summary, labels, scores

    for box in boxes:
        cls_id = int(box.cls[0].item())
        score = float(box.conf[0].item())
        label = names.get(cls_id, str(cls_id))
        if label == "person" and not is_valid_person_box(box, result):
            continue
        labels.append(label)
        scores.append(score)
        summary.append(f"{label_to_cn(label)}({score:.2f})")

    if not summary:
        summary.append("没有检测到有效目标")

    return summary, labels, scores


def count_persons(labels, scores, min_score=MIN_PERSON_SCORE):
    """统计当前帧里的人数。

    参数：
    - `labels`：类别列表
    - `scores`：置信度列表
    - `min_score`：人员有效分数阈值

    返回值：
    - 人员数量（int）

    原理：
    - 只统计 `person` 类；
    - 分数低于 `MIN_PERSON_SCORE` 的人框不算有效目标；
    - 这样可以减少误检。
    """
    return sum(1 for label, score in zip(labels, scores) if label == "person" and score >= min_score)


def detect_alarm_label(labels, scores):
    """从检测结果里找报警目标。

    参数：
    - `labels`：类别列表
    - `scores`：置信度列表

    返回值：
    - `label`：原始类别名
    - `alarm_name`：中文报警名称
    - `score`：命中分数
    - `matched`：是否命中报警目标

    原理：
    - 如果类别属于 `ALARM_LABELS`，就认为它是报警目标；
    - 这里适合扩展明火、烟雾等危险目标。
    """
    for label, score in zip(labels, scores):
        if label in ALARM_LABELS:
            return label, ALARM_LABELS[label], score, True
    return None, None, None, False


def get_result_shape(result):
    if hasattr(result, "orig_img") and result.orig_img is not None:
        return result.orig_img.shape[:2]
    if hasattr(result, "orig_shape") and result.orig_shape is not None:
        return result.orig_shape[:2]
    return PREVIEW_HEIGHT, PREVIEW_WIDTH


def is_valid_person_box(box, result):
    score = float(box.conf[0].item())
    return score >= MIN_PERSON_SCORE


def extract_person_centers(result):
    centers = []
    if not hasattr(result, "boxes") or result.boxes is None:
        return centers

    names = result.names if hasattr(result, "names") else {}
    for box in result.boxes:
        cls_id = int(box.cls[0].item())
        label = names.get(cls_id, str(cls_id))
        if label != "person":
            continue
        if not is_valid_person_box(box, result):
            continue
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        centers.append(((x1 + x2) / 2, (y1 + y2) / 2))
    return centers


def extract_person_boxes(result):
    person_boxes = []
    if not hasattr(result, "boxes") or result.boxes is None:
        return person_boxes

    names = result.names if hasattr(result, "names") else {}
    for box in result.boxes:
        cls_id = int(box.cls[0].item())
        label = names.get(cls_id, str(cls_id))
        if label != "person":
            continue
        if not is_valid_person_box(box, result):
            continue
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        person_boxes.append((x1, y1, x2, y2))
    return person_boxes


def point_in_rect(point, top_left, bottom_right):
    x, y = point
    x1, y1 = top_left
    x2, y2 = bottom_right
    return x1 <= x <= x2 and y1 <= y <= y2


@dataclass
class VisionDecision:
    status: str
    reason: str
    person_count: int
    summary: list
    labels: list
    scores: list
    stable: bool = False
    alarm_label: str | None = None
    alarm_name: str | None = None
    alarm_score: float | None = None
    intruded_people: int = 0
    zone_name: str | None = None
    zone_hit: bool = False
    alarm_frame_count: int = 0


def draw_result(result, status_text, alarm_name=None, zone_name=None):
    """在原始图像上绘制检测框和类别文字。

    参数：
    - `result`：YOLO 检测结果
    - `status_text`：当前状态文本（预留给后续叠加使用）
    - `alarm_name`：报警名称（预留）
    - `zone_name`：禁区名称（预留）

    返回值：
    - 画好框的图像副本

    流程：
    1. 从 `result.orig_img` 复制原图；
    2. 遍历每个检测框；
    3. 计算像素坐标；
    4. 画矩形框和标签；
    5. 返回最终图像。

    原理：
    - YOLO 检测结果本质上是“框 + 类别 + 分数”；
    - 这里把结果画回图像上，方便 UI 和人工观察。
    """
    output = result.orig_img.copy()
    names = result.names if hasattr(result, "names") else {}

    if result.boxes is None:
        return output

    for box in result.boxes:
        cls_id = int(box.cls[0].item())
        score = float(box.conf[0].item())
        label = names.get(cls_id, str(cls_id))
        if label == "person" and not is_valid_person_box(box, result):
            continue

        x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
        color = (0, 200, 0) if label == "person" else (160, 160, 160)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        text = f"{label_to_display(label)} {score:.2f}"
        text_y = max(18, y1 - 8)
        cv2.putText(output, text, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return output


def draw_timestamp(image, timestamp_text):
    if image is not None:
        h = image.shape[0]
        cv2.putText(image, timestamp_text, (10, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
    return image


def create_stability_window(stable_frames_required):
    return deque(maxlen=stable_frames_required)


def create_alarm_window(alarm_frames_required):
    return deque(maxlen=alarm_frames_required)


def majority_vote(window):
    if not window:
        return None, 0
    counter = Counter(window)
    return counter.most_common(1)[0]


def build_decision(summary, labels, scores, stable_person_history, stable_frames_required):
    """把检测结果转成最终状态。

    这是“视觉判断逻辑”的核心函数之一。

    参数：
    - `summary`：检测摘要文本列表
    - `labels`：检测到的类别名列表
    - `scores`：对应置信度列表
    - `stable_person_history`：连续帧人数窗口
    - `stable_frames_required`：稳定帧数要求

    返回值：
    - `VisionDecision` 对象

    原理：
    - 先统计当前帧人数；
    - 再把人数压入稳定窗口；
    - 当窗口长度不够时返回 `WAIT`；
    - 当稳定帧足够时，用多数投票得到最终人数；
    - 根据人数决定 `NORMAL` / `ABNORMAL` / `ALARM`。
    """
    person_count = count_persons(labels, scores)
    stable_person_history.append(person_count)

    if len(stable_person_history) < stable_frames_required:
        return VisionDecision("WAIT", "等待足够的稳定帧", person_count, summary, labels, scores)

    stable_person_count, votes = majority_vote(stable_person_history)
    required_votes = stable_frames_required // 2 + 1
    if votes < required_votes:
        return VisionDecision("WAIT", "等待连续帧结果一致", person_count, summary, labels, scores)

    alarm_label, alarm_name, alarm_score, alarm_matched = detect_alarm_label(labels, scores)
    if alarm_matched:
        return VisionDecision(
            status="ALARM",
            reason=f"检测到报警目标：{alarm_name}（{label_to_cn(alarm_label)}，{alarm_score:.2f}）",
            person_count=stable_person_count,
            summary=summary,
            labels=labels,
            scores=scores,
            stable=True,
            alarm_label=alarm_label,
            alarm_name=alarm_name,
            alarm_score=alarm_score,
        )

    if stable_person_count == 1:
        status, reason = "NORMAL", "检测到 1 名人员"
    elif stable_person_count == 0:
        status, reason = "ABNORMAL", "未检测到人员"
    else:
        status, reason = "ABNORMAL", f"检测到 {stable_person_count} 名人员"

    return VisionDecision(
        status=status,
        reason=reason,
        person_count=stable_person_count,
        summary=summary,
        labels=labels,
        scores=scores,
        stable=True,
    )


def build_speech_text(status, reason):
    if status == "NORMAL":
        return f"当前状态正常。{reason}。"
    if status == "ABNORMAL":
        return f"当前状态异常。{reason}。"
    if status == "ALARM":
        return f"当前状态报警。{reason}。"
    return f"当前状态为 {status}。{reason}。"


def init_tts():
    """初始化 TTS 环境。

    返回值：
    - 一个语音队列 `queue.Queue()`，供后台线程消费

    原理：
    - 先尝试初始化 `pyttsx3`，验证本机 TTS 是否可用；
    - 如果失败，打印警告，但不让整个程序崩掉；
    - 真正播报时由后台线程从队列里取文本。
    """
    engine = None
    try:
        engine = pyttsx3.init("sapi5")
        engine.setProperty("rate", TTS_RATE)
        engine.setProperty("volume", TTS_VOLUME)
    except Exception as exc:
        print(f"TTS init warning, PowerShell fallback will be used if needed: {exc}")
    finally:
        try:
            if engine is not None:
                engine.stop()
        except Exception:
            pass
    return queue.Queue()


def speak_with_powershell(text):
    safe_text = str(text).replace("'", "''")
    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 0; "
        "$s.Volume = 100; "
        f"$s.Speak('{safe_text}'); "
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=False)


def speak_once(text):
    engine = None
    try:
        engine = pyttsx3.init("sapi5")
        engine.setProperty("rate", TTS_RATE)
        engine.setProperty("volume", TTS_VOLUME)
        engine.say(text)
        engine.runAndWait()
    except Exception as exc:
        print(f"TTS pyttsx3 error, using PowerShell fallback: {exc}")
        speak_with_powershell(text)
    finally:
        try:
            if engine is not None:
                engine.stop()
        except Exception:
            pass


def tts_worker(speech_queue):
    while True:
        text = speech_queue.get()
        if text is None:
            speech_queue.task_done()
            break
        try:
            print(f"TTS: {text}")
            speak_once(text)
        except Exception as exc:
            print(f"TTS error: {exc}")
        finally:
            speech_queue.task_done()


def speak_text(speech_queue, text):
    """把待播报文本送入播报系统。

    参数：
    - `speech_queue`：TTS 队列
    - `text`：要播报的文本

    返回值：
    - 无

    流程：
    1. 先尝试通过跨进程 TTS 服务播报；
    2. 如果远端服务不可用，就把文本放入本地队列；
    3. 后台线程再真正播报。

    原理：
    - 这样可以让视觉模块和语音模块共用一套播报入口；
    - 也可以避免多处同时播报导致声音打架。
    """
    if request_tts is not None and request_tts(text):
        return
    speech_queue.put(text)
