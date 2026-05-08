"""vision_bridge.py

视觉联动桥模块。

这个模块负责把“视觉识别结果”变成后续动作：
1. 自动保存报警截图
2. 自动写入报警日志
3. 自动触发 TTS 文本
4. 可选发送串口指令给 STM32
5. 记录最近一次报警截图，供屏幕联动显示
6. 供语音查询模块读取报警统计

设计原则：
- 主流程只负责识别，不要把所有联动逻辑都塞进去；
- 保存、查询、外设控制尽量在这个桥模块里统一收口；
- 所有关键参数都集中在 config.py。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import (
    ALARM_CLIP_DIR,
    ALARM_CLIP_FPS,
    ALARM_CLIP_SECONDS,
    ALARM_COOLDOWN_SECONDS,
    ENABLE_VIDEO_CLIP_SAVE,
    OUTPUT_DIR,
)
from vision_logger import save_alarm_clip, save_record, save_snapshot_record


# =========================
# 重要参数说明
# =========================
# ENABLE_VIDEO_CLIP_SAVE
#   是否开启报警短视频保存。
#   False：只保存截图和日志，磁盘压力更小。
#   True ：报警时自动缓存最近几秒画面并保存短视频。
#
# ALARM_CLIP_SECONDS
#   短视频保存时长，单位秒。
#   例如 5 表示保存报警前后约 5 秒的视频片段。
#
# ALARM_CLIP_FPS
#   保存视频时使用的帧率。
#   这里要和实际摄像头帧率尽量接近，避免播放速度异常。
#
# ALARM_COOLDOWN_SECONDS
#   报警冷却时间，单位秒。
#   防止同一报警在很短时间内反复触发。
# =========================


@dataclass
class LatestAlarmPreview:
    """最近一次报警预览信息。

    这个结构主要给屏幕联动用：
    - 最近一张报警截图路径
    - 最近一次报警时间
    - 最近一次报警原因
    - 最近一次报警类型
    """

    alarm_type: str = ""
    alarm_time: str = ""
    alarm_reason: str = ""
    raw_path: str = ""
    result_path: str = ""
    snapshot_record: dict[str, Any] = field(default_factory=dict)


class VisionBridge:
    """视觉联动桥。

    这个类把视觉识别、日志保存、外设联动、语音查询的公共数据统一收口。
    你后面要做的“有没有报警记录”“最近一次报警是什么”“帮我保存一下”
    都可以从这个类里读到数据。
    """

    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.latest_alarm = LatestAlarmPreview()
        self.recent_records: list[dict[str, Any]] = []
        self.recent_alarm_records: list[dict[str, Any]] = []
        self.last_alarm_time: float = 0.0
        self.last_alarm_clip_path: str = ""

    # -------------------------
    # 基础记录存储
    # -------------------------
    def push_record(self, record: dict[str, Any]):
        """记录一条巡检结果到内存缓存。"""
        self.recent_records.append(record)
        if len(self.recent_records) > 200:
            self.recent_records.pop(0)

    def push_alarm_record(self, record: dict[str, Any]):
        """记录一条报警结果到内存缓存。"""
        self.recent_alarm_records.append(record)
        if len(self.recent_alarm_records) > 200:
            self.recent_alarm_records.pop(0)
        self.latest_alarm = LatestAlarmPreview(
            alarm_type=str(record.get("alarm_type", "")),
            alarm_time=str(record.get("alarm_time", "")),
            alarm_reason=str(record.get("alarm_reason", "")),
            raw_path=str(record.get("raw_path", "")),
            result_path=str(record.get("result_path", "")),
            snapshot_record=dict(record),
        )

    # -------------------------
    # 报警触发统一入口
    # -------------------------
    def handle_alarm(
        self,
        preview,
        result_image,
        stable_status,
        decision,
        jsonl_path,
        csv_path,
        speech_text: str,
        extra_payload: Optional[dict[str, Any]] = None,
    ):
        """处理一次报警联动。

        会做的事：
        1. 保存截图
        2. 写入 JSONL / CSV
        3. 更新最近报警缓存
        4. 返回报警记录，供主流程继续使用
        """
        raw_path, result_path, speech_text, record = save_snapshot_record(
            preview=preview,
            result_image=result_image,
            stable_status=stable_status,
            decision=decision,
            output_dir=self.output_dir,
            jsonl_path=jsonl_path,
            csv_path=csv_path,
        )

        alarm_record = {
            **record,
            "alarm_type": decision.alarm_name or decision.zone_name or "ALARM",
            "alarm_time": record.get("timestamp", ""),
            "zone_name": decision.zone_name or "",
            "intruded_people": decision.intruded_people,
            "alarm_frame_count": decision.alarm_frame_count,
            "alarm_reason": decision.reason,
            "speech_text": speech_text,
            "raw_path": str(raw_path),
            "result_path": str(result_path),
        }
        if extra_payload:
            alarm_record.update(extra_payload)

        self.push_record(record)
        self.push_alarm_record(alarm_record)
        self.last_alarm_time = datetime.now().timestamp()
        return alarm_record

    def manual_snapshot(
        self,
        preview,
        result_image,
        stable_status,
        decision,
        jsonl_path,
        csv_path,
    ):
        """手动保存一张巡检截图。

        对应你的语音命令：
        - "帮我保存一下"
        - "保存当前画面"
        """
        raw_path, result_path, speech_text, record = save_snapshot_record(
            preview=preview,
            result_image=result_image,
            stable_status=stable_status,
            decision=decision,
            output_dir=self.output_dir,
            jsonl_path=jsonl_path,
            csv_path=csv_path,
        )
        self.push_record(record)
        return raw_path, result_path, speech_text, record

    # -------------------------
    # 查询接口
    # -------------------------
    def count_today_alarm_records(self):
        """统计今天的报警条数。

        这里先用内存缓存统计，后面如果你想更严格，可以直接读 JSONL / CSV。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        count = 0
        for record in self.recent_alarm_records:
            time_text = str(record.get("alarm_time", ""))
            if time_text.startswith(today):
                count += 1
        return count

    def get_latest_alarm_summary(self):
        """获取最近一次报警摘要。"""
        if not self.recent_alarm_records:
            return "今天还没有报警记录。"
        latest = self.recent_alarm_records[-1]
        alarm_time = latest.get("alarm_time", "未知时间")
        alarm_type = latest.get("alarm_type", "未知类型")
        alarm_reason = latest.get("alarm_reason", "")
        return f"最近一次报警是 {alarm_time}，类型是 {alarm_type}，原因是 {alarm_reason}。"

    def get_alarm_count_summary(self):
        """统计报警总次数。"""
        return f"当前已记录报警 {len(self.recent_alarm_records)} 次。"

    def get_latest_alarm_preview_path(self):
        """返回最近一次报警截图路径，供屏幕联动显示。"""
        return self.latest_alarm.result_path or self.latest_alarm.raw_path or ""

    # -------------------------
    # 语音查询支持
    # -------------------------
    def query_alarm_records(self, query_text: str):
        """根据语音文本返回查询结果。

        这里先做最基础的关键词匹配：
        - 有没有报警
        - 最近一次报警是什么
        - 报警几次了
        - 帮我保存一下
        """
        text = (query_text or "").strip()
        if not text:
            return "我没有听清，请你再说一遍。"

        if any(k in text for k in ["有没有报警", "今天有几条", "报警有几条", "有没有报警记录"]):
            return f"今天共有 {self.count_today_alarm_records()} 条报警记录。"

        if any(k in text for k in ["最近一次报警", "最近报警是什么", "最后一条报警"]):
            return self.get_latest_alarm_summary()

        if any(k in text for k in ["报警几次", "报警次数", "报了几次"]):
            return self.get_alarm_count_summary()

        if any(k in text for k in ["帮我保存", "保存一下", "保存当前画面"]):
            return "已保存当前巡检记录。"

        return "我暂时没有理解这条指令。"

    # -------------------------
    # 外设联动
    # -------------------------
    def send_stm32_command(self, serial_port, alarm_triggered: bool, payload: Optional[dict[str, Any]] = None):
        """给 STM32 发送串口指令。

        参数说明：
        - serial_port: 串口对象，通常来自 pyserial
        - alarm_triggered: 当前是否处于报警
        - payload: 额外数据，方便 STM32 或调试端读取

        这里默认不依赖 pyserial 的具体写法，避免你环境里没装时直接报错。
        如果你后面确认用的是串口，再把真正的 serial.Serial 传进来即可。
        """
        if serial_port is None:
            return False
        try:
            message = {
                "cmd": "alarm" if alarm_triggered else "normal",
                "alarm": bool(alarm_triggered),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            if payload:
                message.update(payload)
            raw = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            serial_port.write(raw)
            return True
        except Exception:
            return False

    # -------------------------
    # 视频片段保存
    # -------------------------
    def save_alarm_video_if_enabled(self, frames):
        """如果开启短视频保存，就把报警片段写出去。"""
        if not ENABLE_VIDEO_CLIP_SAVE:
            return ""
        if not frames:
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clip_path = ALARM_CLIP_DIR / f"alarm_clip_{timestamp}.mp4"
        save_alarm_clip(frames, ALARM_CLIP_FPS, clip_path)
        self.last_alarm_clip_path = str(clip_path)
        return str(clip_path)
