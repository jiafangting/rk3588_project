"""Record and snapshot helpers for the vision module."""

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

from vision_core import build_speech_text


def ensure_parent_dir(file_path):
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)


def _now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json_safe(value: Any):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _record_to_csv_row(record):
    return {key: _json_safe(value) for key, value in record.items()}


def append_jsonl(record, jsonl_path):
    ensure_parent_dir(jsonl_path)
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_csv(record, csv_path):
    ensure_parent_dir(csv_path)
    file_exists = os.path.exists(csv_path)
    row = _record_to_csv_row(record)

    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def save_record(record, jsonl_path, csv_path=None):
    append_jsonl(record, jsonl_path)
    if csv_path:
        append_csv(record, csv_path)


def build_record(timestamp=None, status="", reason="", speech_text="", raw_path="", result_path="", person_count=None, summary=None):
    if timestamp is None:
        timestamp = _now_text()
    return {
        "timestamp": timestamp,
        "status": status,
        "reason": reason,
        "speech_text": speech_text,
        "raw_path": raw_path,
        "result_path": result_path,
        "person_count": person_count,
        "summary": summary if summary is not None else [],
    }


def build_alarm_record(
    alarm_type,
    alarm_time=None,
    zone_name="",
    intruded_people=0,
    alarm_frame_count=0,
    raw_path="",
    result_path="",
    alarm_reason="",
    speech_text="",
):
    if alarm_time is None:
        alarm_time = _now_text()
    return {
        "alarm_type": alarm_type,
        "alarm_time": alarm_time,
        "zone_name": zone_name,
        "intruded_people": intruded_people,
        "alarm_frame_count": alarm_frame_count,
        "raw_path": raw_path,
        "result_path": result_path,
        "alarm_reason": alarm_reason,
        "speech_text": speech_text,
    }


def save_alarm_clip(frames, fps, output_path):
    if not frames:
        raise ValueError("No video frames to save")

    ensure_parent_dir(output_path)
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Cannot open video writer: {output_path}")

    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()

    return output_path


def _save_image(image, path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return cv2.imwrite(path, image)


def save_snapshot_record(preview, result_image, stable_status, decision, output_dir, jsonl_path, csv_path):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"voice_raw_{timestamp}.jpg"
    result_path = output_dir / f"voice_result_{timestamp}.jpg"

    if not _save_image(preview, str(raw_path)) or not _save_image(result_image, str(result_path)):
        raise RuntimeError("Snapshot save failed")

    record_status = stable_status if stable_status else decision.status
    speech_text = build_speech_text(record_status, decision.reason)

    record = build_record(
        timestamp=_now_text(),
        status=record_status,
        reason=decision.reason,
        speech_text=speech_text,
        raw_path=str(raw_path),
        result_path=str(result_path),
        person_count=decision.person_count,
        summary=decision.summary,
    )

    if decision.status == "ALARM":
        alarm_record = build_alarm_record(
            alarm_type=decision.alarm_name or decision.zone_name or "ALARM",
            alarm_time=_now_text(),
            zone_name=decision.zone_name or "",
            intruded_people=decision.intruded_people,
            alarm_frame_count=decision.alarm_frame_count,
            raw_path=str(raw_path),
            result_path=str(result_path),
            alarm_reason=decision.reason,
            speech_text=speech_text,
        )
        save_record(alarm_record, str(jsonl_path), str(csv_path))
    else:
        save_record(record, str(jsonl_path), str(csv_path))

    return raw_path, result_path, speech_text, record
