"""Core vision helpers: camera, model inference, decision helpers and TTS."""

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
    return cv2.resize(frame, (PREVIEW_WIDTH, PREVIEW_HEIGHT))


def load_model(model_path="yolo11n.pt"):
    if os.path.exists(model_path):
        print(f"Using local model: {model_path}")
    else:
        print(f"Local model not found, YOLO may try to download: {model_path}")
    return YOLO(model_path)


def run_inference(model, frame):
    results = model.predict(frame, conf=YOLO_CONF, verbose=False)
    return results[0]


def parse_result(result):
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
    return sum(1 for label, score in zip(labels, scores) if label == "person" and score >= min_score)


def detect_alarm_label(labels, scores):
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
    person_count = count_persons(labels, scores)
    stable_person_history.append(person_count)

    if len(stable_person_history) < stable_frames_required:
        return VisionDecision("WAIT", "等待足够的稳定帧", person_count, summary, labels, scores)

    stable_person_count, votes = majority_vote(stable_person_history)
    required_votes = stable_frames_required // 2 + 1
    count_text = "1 person" if stable_person_count == 1 else f"{stable_person_count} persons"
    return VisionDecision(
        status="NORMAL",
        reason=f"Detected {count_text}",
        person_count=stable_person_count,
        summary=summary,
        labels=labels,
        scores=scores,
        stable=True,
    )
    if votes < required_votes:
        return VisionDecision("WAIT", "等待连续帧结果一致", person_count, summary, labels, scores)

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

    alarm_label, alarm_name, alarm_score, alarm_matched = detect_alarm_label(labels, scores)
    if alarm_matched:
        status = "ALARM"
        reason = f"检测到报警目标：{alarm_name}（{label_to_cn(alarm_label)}，{alarm_score:.2f}）"

    return VisionDecision(
        status=status,
        reason=reason,
        person_count=stable_person_count,
        summary=summary,
        labels=labels,
        scores=scores,
        stable=True,
        alarm_label=alarm_label,
        alarm_name=alarm_name,
        alarm_score=alarm_score,
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
    if request_tts is not None and request_tts(text):
        return
    speech_queue.put(text)
