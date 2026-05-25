"""语音指令处理模块。

这个文件的作用是：
1. 接收 ASR 识别出来的文字；
2. 识别用户想问什么；
3. 去读取视觉报警记录；
4. 返回一句适合 TTS 播报的话。

它相当于“语音输入和系统功能之间的翻译层”：
- 用户说中文；
- ASR 变成文本；
- 这里把文本转成系统动作或播报回复。

流程：
1. `handle_command()` 接收文本；
2. `_normalize()` 统一去空格、标点；
3. 按关键词判断意图；
4. 读取报警日志或返回确认语句；
5. 把最终回复交给 TTS。

设计原则：
- 不改语音模块原有结构，只提供一个可调用的处理函数；
- 失败时抛出异常给上层捕获，但不要让整个语音模块崩掉；
- 如果后面语音模块和视觉模块分开运行，也可以继续扩展成 socket / 文件读取模式。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from vision_bridge import VisionBridge


# =========================
# 重要参数
# =========================
# DEFAULT_VISION_JSONL_PATH
#   视觉模块报警日志文件。
#   语音查询时优先读取它。
#
# DEFAULT_VISION_CSV_PATH
#   备用日志文件，用于 Excel 查看。
# =========================
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VISION_RECORDS_DIR = PROJECT_ROOT / "vision" / "app" / "output" / "recodes"
DEFAULT_VISION_JSONL_PATH = DEFAULT_VISION_RECORDS_DIR / "records.jsonl"
DEFAULT_VISION_CSV_PATH = DEFAULT_VISION_RECORDS_DIR / "records.csv"

# 这两个默认路径的意义：
# - JSONL 适合程序读取，字段完整；
# - CSV 适合 Excel / 人工查看。
# 如果日志格式变化，优先保持 JSONL 结构稳定。

_bridge = VisionBridge()
_bridge.vision_jsonl_path = DEFAULT_VISION_JSONL_PATH
_bridge.vision_csv_path = DEFAULT_VISION_CSV_PATH


def _normalize(text: str) -> str:
    """去掉空格和常见标点，方便命令匹配。"""
    if not text:
        return ""
    for ch in " ，。！？!?,.、：:；;“”\"' \t\r\n":
        text = text.replace(ch, "")
    return text.lower()


def _read_alarm_records():
    """从视觉模块日志里读取报警记录。

    优先 JSONL，因为它更完整；
    如果 JSONL 不存在，再尝试 CSV。
    """
    records = _bridge.load_alarm_records()
    return records


def _latest_alarm_summary(records):
    if not records:
        return "今天还没有报警记录。"
    last = records[-1]
    alarm_time = last.get("alarm_time") or last.get("timestamp") or "未知时间"
    alarm_type = last.get("alarm_type") or last.get("status") or "未知类型"
    alarm_reason = last.get("alarm_reason") or last.get("reason") or ""
    return f"{alarm_time}，检测到 {alarm_type}。{alarm_reason}"


def _handle_alarm_query(text: str) -> str:
    """处理报警查询类语音指令。"""
    normalized = _normalize(text)
    records = _read_alarm_records()

    if not records:
        return "今天还没有报警记录。"

    if "最近一次报警" in normalized or "最近报警是什么" in normalized or "最后一条报警" in normalized:
        return _latest_alarm_summary(records)

    if "有没有报警" in normalized or "报警记录" in normalized or "报警有几条" in normalized:
        return f"今天共有 {len(records)} 条报警记录。最近一次是 {_latest_alarm_summary([records[-1]])}"

    if "报警几次" in normalized or "报警次数" in normalized or "报了几次" in normalized:
        return f"当前已报警 {len(records)} 次。"

    return "我没有听懂报警查询指令。"


def _handle_save_request() -> str:
    """处理手动保存请求。

    这里先返回确认语音，真正的截图保存动作由视觉模块主流程完成。
    如果后续你把视觉模块和语音模块打到同一个桥里，也可以直接在这里触发保存。
    """
    return "已收到保存请求，请在视觉界面确认当前画面。"


def handle_command(asr_text: str) -> str:
    """统一的语音指令处理入口。

    参数：
    - `asr_text`：ASR 识别出来的原始文本

    返回值：
    - 适合 TTS 播报的回复字符串

    流程：
    1. 先归一化文本；
    2. 判断是不是报警查询；
    3. 判断是不是保存请求；
    4. 判断是不是视觉状态查询；
    5. 判断是不是巡检请求；
    6. 如果都不是，返回默认理解失败提示。

    说明：
    - 这个函数只负责“理解文字并返回回复”；
    - 不直接播放语音，播放由外层语音模块决定；
    - 失败时向上抛异常，方便语音模块打印错误但不中断主循环。
    """
    text = _normalize(asr_text)
    if not text:
        return "我没有听清，请再说一遍。"

    if any(k in text for k in ["有没有报警", "报警记录", "最近一次报警", "报警几次", "保存一下", "帮我保存", "保存当前画面"]):
        if "保存一下" in text or "帮我保存" in text or "保存当前画面" in text:
            return _handle_save_request()
        return _handle_alarm_query(text)

    if any(k in text for k in ["查询视觉状态", "视觉状态", "当前视觉状态", "vision", "status"]):
        # 这里先直接读取最近一次状态，如果后面要更完整，可继续接 socket 查询。
        records = _read_alarm_records()
        if records:
            return f"最近一次视觉报警是 {_latest_alarm_summary(records)}"
        return "当前没有视觉报警记录。"

    if any(k in text for k in ["开始巡检", "巡检", "检测", "inspect", "check"]):
        return "已收到巡检请求，请稍候。"

    return "我暂时没有理解这条指令。"
