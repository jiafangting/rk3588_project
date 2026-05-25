"""语音模块主入口。

这个文件把“麦克风录音 -> 语音识别 -> 指令判断 -> TTS 播报 -> 视觉联动”
串成一整条闭环。

整体流程：
1. 等待用户说话；
2. 用音量阈值自动结束录音；
3. 保存成 WAV；
4. 用 faster-whisper 识别中文；
5. 根据唤醒词切换待机/工作模式；
6. 在工作模式下处理温度、模式、视觉查询、报警查询、保存画面等指令；
7. 必要时调用 LLM 做意图纠错或闲聊回复；
8. 把最终回复交给语音播报模块；
9. 长时间没输入则自动回到待机；
10. 遇到停止词时退出程序。

运行方式：
    D:\\anaconda3\\envs\\rk3588-ai\\python.exe voice\\voice_loop.py

功能流程：
    1. 待机模式持续监听麦克风；
    2. 录到一段有效声音后，静音自动结束；
    3. 保存为项目根目录的 test.wav；
    4. 使用 faster-whisper 做中文识别；
    5. 识别到“小杜你好”等唤醒词后进入工作模式；
    6. 工作模式下回答“温度 / 模式 / 停止”等指令；
    7. 支持查询视觉报警记录；
    8. 支持手动触发视觉模块保存当前巡检画面；
    9. 长时间没有有效语音，自动回到待机模式；
    10. 听到“停止 / 退出 / 结束”后退出程序。
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write

from voice_broadcast import TTSRequestServer, VoiceBroadcaster, is_tts_active
from vision_control import DEFAULT_VISION_SOCKET_PATH, VisionSocketClient, format_vision_result
from llm_chat import LLMChat


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAV_PATH = PROJECT_ROOT / "test.wav"
DEFAULT_VISION_OUTPUT_DIR = PROJECT_ROOT / "vision" / "app" / "output"
DEFAULT_VISION_RECORDS_DIR = DEFAULT_VISION_OUTPUT_DIR / "recodes"
DEFAULT_VISION_JSONL_PATH = DEFAULT_VISION_RECORDS_DIR / "records.jsonl"
DEFAULT_VISION_CSV_PATH = DEFAULT_VISION_RECORDS_DIR / "records.csv"
LEGACY_VISION_JSONL_PATH = DEFAULT_VISION_OUTPUT_DIR / "records.jsonl"
LEGACY_VISION_CSV_PATH = DEFAULT_VISION_OUTPUT_DIR / "records.csv"
DEFAULT_THRESHOLD_CONFIG_PATH = PROJECT_ROOT / "rk3588" / "config.json"
RK_ALARM_LOG_PATH = PROJECT_ROOT / "rk3588" / "alarm_log.csv"
VOICE_EXCHANGE_PATH = PROJECT_ROOT / ".tmp" / "voice_last_exchange.json"

# 这份默认阈值要和 UI / 仿真后端保持一致。
# 如果 rk3588/config.json 存在，语音模块会优先读取配置文件里的阈值。
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


WAKE_WORDS = ("小杜你好", "小度你好", "小杜", "小度", "wake", "xiaodu", "xiaodu你好")
STOP_WORDS = ("停止", "退出", "结束", "关闭程序", "stop", "quit", "exit")
WORK_MODE_TIMEOUT_SECONDS = 20

# 重要参数说明：
# DEFAULT_VISION_JSONL_PATH
#   视觉模块默认 JSONL 日志路径。
#   语音查询“有没有报警记录 / 最近一次报警是什么”时，会优先读这个文件。
#
# DEFAULT_VISION_CSV_PATH
#   视觉模块默认 CSV 日志路径。
#   主要用于备用读取和后续人工分析。
#
# WORK_MODE_TIMEOUT_SECONDS
#   工作模式超时秒数。
#   如果进入工作模式后长时间没有有效输入，就自动回到待机模式。


@dataclass
class VoiceConfig:
    """语音模块运行参数。

    这是语音模块的“参数总表”。
    你后面要调麦克风灵敏度、录音时长、识别模型大小，基本都从这里入手。
    """

    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 100
    max_record_seconds: float = 6.0
    min_record_seconds: float = 0.6
    silence_seconds_to_stop: float = 1.0
    volume_threshold: float = 0.012
    wav_path: Path = DEFAULT_WAV_PATH
    whisper_model: str = "small"


class WhisperRecognizer:
    """faster-whisper 中文识别封装。

    模型第一次识别时才加载，避免程序启动时卡住。
    """

    def __init__(self, model_name="small"):
        self.model_name = model_name
        self._model = None

    def transcribe(self, wav_path):
        """把 WAV 文件识别成中文文本。

        参数：
        - `wav_path`：待识别的音频文件路径

        返回值：
        - `text`：识别出来的文本
        - `language`：识别语言
        - `probability`：语言置信度

        原理：
        - 模型第一次调用时才加载，避免启动卡顿；
        - `beam_size=5` 让识别结果更稳一些；
        - `vad_filter=True` 让模型尽量忽略静音段。
        """
        if self._model is None:
            print(f"[识别] 正在加载 faster-whisper 模型：{self.model_name}")
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            print("[识别] 模型加载完成")

        segments, info = self._model.transcribe(
            str(wav_path),
            language="zh",
            beam_size=5,
            vad_filter=True,
        )
        text = "".join(segment.text for segment in segments).strip()
        language = getattr(info, "language", "unknown")
        probability = getattr(info, "language_probability", 0.0)
        print(f"[识别] 语言：{language}，置信度：{probability:.2f}")
        print(f"[识别] 文本：{text if text else '<空>'}")
        return text, language, probability


def normalize_text(text):
    """去掉空格和常见标点，方便做关键词匹配。"""
    for old, new in NORMALIZATION_REPLACEMENTS.items():
        text = text.replace(old, new)
    for ch in " ，。！？!?,.、：:；;“”\"' \t\r\n":
        text = text.replace(ch, "")
    return text


def contains_any(text, words):
    normalized = normalize_text(text)
    return any(normalize_text(word) in normalized for word in words)


DIRECT_TEXT_COMMAND_WORDS = (
    "当前是什么模式",
    "当前温度多少",
    "温度",
    "湿度",
    "电流",
    "电压",
    "烟雾",
    "烟感",
    "设备温度",
    "传感器状态",
    "设备状态",
    "系统状态",
    "开始巡检",
    "巡检",
    "检测",
    "查询视觉状态",
    "视觉状态",
    "有没有报警",
    "有无报警",
    "有沒有報警",
    "最近一次报警",
    "最近一次報警",
    "报警几次",
    "报警了几次",
    "报了几次",
    "报警次数",
    "報警幾次",
    "帮我保存一下",
    "幫我保存一下",
    "mode",
    "temp",
    "humidity",
    "current",
    "voltage",
    "smoke",
    "inspect",
    "vision",
    "status",
)

NORMALIZATION_REPLACEMENTS = {
    "報": "报",
    "警": "警",
    "沒": "没",
    "有沒有": "有没有",
    "幾": "几",
    "幫": "帮",
    "尋": "寻",
    "檢": "检",
    "尋檢": "巡检",
    "寻检": "巡检",
    "寻衅": "巡检",
    "巡警": "巡检",
    "开始寻衅": "开始巡检",
    "开始寻检": "开始巡检",
    "抱枪": "报警",
    "爆警": "报警",
    "抱紧": "报警",
    "报紧": "报警",
}


def record_until_silence(config: VoiceConfig):
    """监听麦克风，检测静音后自动结束本轮录音。

    参数：
    - `config`：语音配置对象，里面定义采样率、阈值、录音时长等

    返回值：
    - `True`：录到了有效语音并写入 WAV
    - `False`：本轮基本是静音或录音无效

    流程：
    1. 先等待 TTS 播报结束，避免把自己的声音录进去；
    2. 打开麦克风输入流；
    3. 按 100ms 一帧读取音频；
    4. 计算每帧音量；
    5. 音量超过阈值就认为开始说话；
    6. 连续静音一段时间后结束录音；
    7. 保存成 `test.wav`；
    8. 返回是否成功。
    """
    frame_samples = int(config.sample_rate * config.frame_ms / 1000)
    max_frames = int(config.max_record_seconds * 1000 / config.frame_ms)
    min_frames = int(config.min_record_seconds * 1000 / config.frame_ms)
    silence_frames_to_stop = int(config.silence_seconds_to_stop * 1000 / config.frame_ms)

    frames = []
    active_started = False
    silence_count = 0
    max_volume = 0.0

    while is_tts_active():
        print("[监听] 正在播报，暂停开麦...")
        time.sleep(0.2)

    print("[监听] 请说话...")
    with sd.InputStream(samplerate=config.sample_rate, channels=config.channels, dtype="float32") as stream:
        for _ in range(max_frames):
            if is_tts_active():
                print("[监听] 播报开始，丢弃本轮录音，避免录入喇叭声")
                return False
            data, _overflowed = stream.read(frame_samples)
            mono = data[:, 0] if data.ndim > 1 else data
            volume = float(np.sqrt(np.mean(np.square(mono))))
            max_volume = max(max_volume, volume)

            if volume >= config.volume_threshold:
                active_started = True
                silence_count = 0
            elif active_started:
                silence_count += 1

            if active_started:
                frames.append(mono.copy())

            if active_started and len(frames) >= min_frames and silence_count >= silence_frames_to_stop:
                break

    if not frames:
        print(f"[监听] 未检测到有效语音，最大音量：{max_volume:.4f}")
        return False

    audio = np.concatenate(frames)
    if max_volume < config.volume_threshold:
        print(f"[监听] 声音太小，最大音量：{max_volume:.4f}")
        return False

    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    write(str(config.wav_path), config.sample_rate, pcm)
    print(f"[监听] 已保存录音：{config.wav_path}")
    return True


class VoiceAssistant:
    """带模式状态的语音助手。

    这个类是整个语音模块的调度中心：
    - 管理待机/工作模式；
    - 管理麦克风录音；
    - 管理语音识别；
    - 管理视觉查询；
    - 管理 LLM 闲聊兜底；
    - 管理 TTS 播报。
    """

    def __init__(self, config=None, text_mode=False, vision_socket_path=DEFAULT_VISION_SOCKET_PATH):
        """初始化语音助手。

        参数：
        - `config`：语音配置对象，默认创建 `VoiceConfig()`
        - `text_mode`：是否使用文本模式模拟语音识别
        - `vision_socket_path`：视觉模块 socket 路径

        返回值：
        - 无

        说明：
        - `text_mode=True` 时，不需要麦克风和 Whisper，适合调试；
        - 正常运行时会启动 TTS 请求服务器、Whisper 识别器和视觉客户端。
        """
        self.config = config or VoiceConfig()
        self.text_mode = text_mode
        self.mode = "standby"
        self.running = True
        self.last_work_time = 0.0
        self.broadcaster = VoiceBroadcaster()
        self.recognizer = WhisperRecognizer(self.config.whisper_model)
        self.vision_client = VisionSocketClient(vision_socket_path)
        self.vision_jsonl_path = DEFAULT_VISION_JSONL_PATH
        self.vision_csv_path = DEFAULT_VISION_CSV_PATH
        self.legacy_vision_jsonl_path = LEGACY_VISION_JSONL_PATH
        self.legacy_vision_csv_path = LEGACY_VISION_CSV_PATH
        self.threshold_config_path = DEFAULT_THRESHOLD_CONFIG_PATH
        self.rk_alarm_log_path = RK_ALARM_LOG_PATH
        self.llm = LLMChat()
        self.tts_server = TTSRequestServer(self.broadcaster)
        if self.llm.enabled:
            print(f"[LLM] 在线问答已启用，模型：{self.llm.model}")
        else:
            print("[LLM] 在线问答未启用，未命中本地指令时将提示用户重述。")

    def run(self):
        self.broadcaster.start()
        self.tts_server.start()
        self.broadcaster.speak("语音模块启动，当前处于待机模式。")

        try:
            if self.text_mode:
                self.run_text_loop()
                return

            while self.running:
                if self.mode == "work" and time.time() - self.last_work_time > WORK_MODE_TIMEOUT_SECONDS:
                    self.switch_to_standby("长时间没有检测到有效语音，已返回待机模式。")

                self.broadcaster.wait_until_done()
                time.sleep(0.3)

                has_voice = record_until_silence(self.config)
                if not has_voice:
                    continue

                text, _language, _probability = self.recognizer.transcribe(self.config.wav_path)
                if not text:
                    if self.mode == "work":
                        print("[模式] 工作模式下本轮无识别结果，继续监听")
                    continue

                self.handle_text(text)
        finally:
            self.tts_server.stop()
            self.broadcaster.stop()

    def run_text_loop(self):
        """文本模拟模式。

        这个模式不使用麦克风，也不加载 Whisper。
        你可以直接在终端输入文字，验证唤醒词、模式切换、指令解析和播报。
        """
        print("========== 语音模块文本模拟模式 ==========")
        print("直接输入：小杜你好 / 当前是什么模式 / 当前温度多少 / 当前湿度多少 / 当前电压多少 / 当前电流多少 / 烟雾状态 / 开始巡检 / 查询视觉状态 / 停止")
        print("语音查询：有没有报警 / 最近一次报警是什么 / 报警几次了 / 帮我保存一下")
        print("如果终端中文输入有编码问题，也可以输入：wake / mode / temp / current / voltage / smoke / inspect / vision / stop")
        print("=========================================")

        while self.running:
            if self.mode == "work" and time.time() - self.last_work_time > WORK_MODE_TIMEOUT_SECONDS:
                self.switch_to_standby("长时间没有检测到有效输入，已返回待机模式。")

            try:
                text = input(f"[{self.mode}] 输入 > ").strip()
            except EOFError:
                break

            if not text:
                continue

            print(f"[文本输入] {text}")
            self.handle_text(text)

    def handle_text(self, text):
        if contains_any(text, STOP_WORDS):
            reply = "好的，程序结束。"
            self.write_voice_exchange_pair(text, reply, event="clear")
            self.broadcaster.speak(reply)
            self.running = False
            return

        if self.mode == "standby":
            if contains_any(text, WAKE_WORDS):
                self.mode = "work"
                self.last_work_time = time.time()
                reply = "我在，已进入工作模式。"
                self.write_voice_exchange_pair(text, reply)
                self.broadcaster.speak(reply)
            elif self.text_mode and contains_any(text, DIRECT_TEXT_COMMAND_WORDS):
                self.mode = "work"
                self.last_work_time = time.time()
                reply = self.build_reply(text)
                self.write_voice_exchange_pair(text, reply)
                self.broadcaster.speak(reply)
            else:
                print("[模式] 待机模式，未检测到唤醒词")
            return

        self.last_work_time = time.time()
        reply = self.build_reply(text)
        self.write_voice_exchange_pair(text, reply)
        self.broadcaster.speak(reply)

    def write_voice_exchange_pair(self, user_text, bot_text, event="message"):
        """把最近一轮语音对话写给 UI。

        UI 的 VoiceWidget 每 500ms 读取 `.tmp/voice_last_exchange.json`。
        顶层字段仍然保留 role/text/timestamp，兼容简单读取；
        同时额外写入 messages，避免 UI 刷新慢时漏掉用户消息。
        """
        try:
            VOICE_EXCHANGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            user_timestamp = datetime.now().isoformat(timespec="milliseconds")
            bot_timestamp = datetime.now().isoformat(timespec="milliseconds")
            data = {
                "event": event,
                "role": "bot",
                "text": str(bot_text),
                "timestamp": bot_timestamp,
                "messages": [
                    {"role": "user", "text": str(user_text), "timestamp": user_timestamp},
                    {"role": "bot", "text": str(bot_text), "timestamp": bot_timestamp},
                ],
            }
            with open(VOICE_EXCHANGE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[语音UI] 写入语音共享状态失败：{exc}")

    def build_reply(self, text):
        normalized = normalize_text(text)

        if any(k in normalized for k in ["传感器状态", "设备状态", "系统状态", "传感器数值"]):
            return self.reply_sensor_summary()

        if "设备温度" in normalized or "机器温度" in normalized or "devicetemp" in normalized:
            return self.reply_sensor_value("temp_device")

        if "温度" in normalized or "temp" in normalized:
            return self.reply_sensor_value("temperature")

        if "湿度" in normalized or "humidity" in normalized:
            return self.reply_sensor_value("humidity")

        if "电流" in normalized or "current" in normalized:
            return self.reply_sensor_value("current")

        if "电压" in normalized or "voltage" in normalized:
            return self.reply_voltage_status()

        if "烟雾" in normalized or "烟感" in normalized or "smoke" in normalized:
            return self.reply_sensor_value("smoke")

        if "模式" in normalized or "mode" in normalized:
            if self.mode == "work":
                return "我当前处于工作模式。"
            return "我当前处于待机模式。"

        if "待机" in normalized or "休息" in normalized or "standby" in normalized:
            self.mode = "standby"
            return "好的，已返回待机模式。"

        if any(k in normalized for k in ["有没有报警", "有无报警", "报警记录", "最近一次报警", "报警几次", "报警了几次", "报了几次", "报警次数", "帮我保存"]):
            return self.reply_alarm_query(normalized)

        if (
            ("视觉" in normalized and ("状态" in normalized or "结果" in normalized or "报警" in normalized))
            or "vision" in normalized
            or "status" in normalized
        ):
            return self.reply_vision_status()

        if (
            "巡检" in normalized
            or "检测" in normalized
            or "拍照" in normalized
            or "截图" in normalized
            or "inspect" in normalized
            or "check" in normalized
            or "capture" in normalized
        ):
            return self.reply_trigger_inspection()

        if self.llm.enabled:
            intent_reply = self.reply_by_llm_intent(text)
            if intent_reply is not None:
                return intent_reply
            print(f"[LLM] 兜底问答：{text}")
            return self.llm.ask(text)

        return "我听到了，但暂时还没有对应的控制指令。"

    def reply_by_llm_intent(self, text):
        """Let LLM correct noisy ASR text into one known local command.

        This is only used after deterministic keyword matching fails. It keeps
        fast local commands fast, while still letting phrases like "有没有抱枪"
        or "开始寻衅" route to the right device action.
        """
        intent = self.llm.classify_intent(text)
        print(f"[LLM] 意图识别：{text} -> {intent}")

        if intent == "alarm_query":
            return self.reply_alarm_query("有没有报警")
        if intent == "latest_alarm":
            return self.reply_alarm_query("最近一次报警")
        if intent == "alarm_count":
            return self.reply_alarm_query("报警了几次")
        if intent == "vision_status":
            return self.reply_vision_status()
        if intent == "trigger_inspection":
            return self.reply_trigger_inspection()
        if intent == "temperature":
            return self.reply_sensor_value("temperature")
        if intent == "humidity":
            return self.reply_sensor_value("humidity")
        if intent == "current":
            return self.reply_sensor_value("current")
        if intent == "voltage":
            return self.reply_voltage_status()
        if intent == "smoke":
            return self.reply_sensor_value("smoke")
        if intent == "mode":
            return "我当前处于工作模式。" if self.mode == "work" else "我当前处于待机模式。"
        if intent == "standby":
            self.mode = "standby"
            return "好的，已返回待机模式。"
        if intent == "stop":
            self.running = False
            return "好的，程序结束。"
        return None

    def switch_to_standby(self, message):
        self.mode = "standby"
        self.broadcaster.speak(message)

    def reply_vision_status(self):
        """查询视觉模块当前状态并生成语音回复。"""
        try:
            result = self.vision_client.get_status()
        except Exception as exc:
            print(f"[视觉连接] 查询状态失败：{exc}")
            return "视觉模块暂时无法连接，请先启动视觉程序。"

        return format_vision_result("当前视觉状态", result)

    def reply_trigger_inspection(self):
        """触发视觉模块执行一次巡检并生成语音回复。"""
        try:
            result = self.vision_client.trigger_inspection()
        except Exception as exc:
            print(f"[视觉连接] 触发巡检失败：{exc}")
            return "无法触发视觉巡检，请先启动视觉程序。"

        return format_vision_result("巡检完成", result)

    # -------------------------
    # 新增：报警记录查询
    # -------------------------
    def reply_alarm_query(self, normalized_text):
        """根据语音内容查询报警记录。

        查询策略分两层：
        1. 先问视觉模块 socket 的实时状态。视觉刚报警但还没来得及写文件时，
           这里也能立刻回答“现在有报警”。
        2. 如果实时状态不是报警，或者视觉模块暂时没连上，再读取 JSONL/CSV
           历史记录，回答今天有没有报警、最近一次报警和报警次数。
        """
        if "帮我保存" in normalized_text or "保存一下" in normalized_text or "保存当前画面" in normalized_text:
            return self.manual_save_current_frame()

        latest_status = self.get_live_vision_status()
        records = self.load_alarm_records()

        if "报警几次" in normalized_text or "报警了几次" in normalized_text or "报警次数" in normalized_text or "报了几次" in normalized_text:
            reply = f"历史报警记录里共有 {len(records)} 次报警。"
            if self.is_live_alarm(latest_status):
                reply += f" 当前也有报警，{self.format_live_alarm_reason(latest_status)}"
            return reply

        if "最近一次报警" in normalized_text or "最近报警是什么" in normalized_text or "最后一条报警" in normalized_text:
            if not records:
                return "历史记录里还没有报警。"
            last = records[-1]
            return self.format_alarm_record_for_tts(last)

        if "报警记录" in normalized_text or "报警有几条" in normalized_text:
            count = len(records)
            if not records:
                return "历史记录里还没有报警。"
            last = records[-1]
            return f"今天共有 {count} 条报警记录。最近一次是 {self.format_alarm_record_for_short_tts(last)}"

        if "有没有报警" in normalized_text or "有无报警" in normalized_text:
            if self.is_live_alarm(latest_status):
                return f"现在有报警，{self.format_live_alarm_reason(latest_status)}"
            if latest_status is None:
                return "暂时读不到实时报警状态，请先确认仿真后端已经启动。"
            return "当前没有报警。"

        if self.is_live_alarm(latest_status):
            return f"现在有报警，{self.format_live_alarm_reason(latest_status)}"

        return "我没有理解你的报警查询指令。"

    def get_live_vision_status(self):
        """Read the current status from the vision socket.

        This is intentionally best-effort. Alarm history queries should still
        work from local files if the visual process is not running, so socket
        errors are logged for debugging but are not spoken to the user.
        """
        try:
            return self.vision_client.get_status()
        except Exception as exc:
            print(f"[视觉连接] 实时报警状态查询失败：{exc}")
            return None

    def is_live_alarm(self, status):
        """判断实时状态是不是报警。

        `status` 是仿真后端 socket 返回的字典，例如：
            {"status": "ALARM", "reason": "环境温度过高 31.0°C"}
        这里单独封装，是为了让“有无报警”和“报警几次”复用同一套判断。
        """
        if not status:
            return False
        return str(status.get("status", "")).upper() == "ALARM"

    def format_live_alarm_reason(self, status):
        """把实时报警状态整理成一句适合语音播报的话。"""
        if not status:
            return "原因未知。"

        reason = self.format_alarm_reason(status.get("alarm_reason") or status.get("reason") or "")
        alarm_type = self.format_alarm_type(status.get("alarm_type") or status.get("zone_name") or "")
        person_count = status.get("person_count", 0)

        parts = []
        if reason:
            if not reason.endswith(("。", "！", "!", ".")):
                reason += "。"
            parts.append(f"报警原因是{reason}")
        if alarm_type:
            parts.append(f"报警类型是{alarm_type}。")
        parts.append(f"检测人数 {person_count}。")
        return "".join(parts)

    def get_live_system_status(self):
        """读取“当前系统状态”，给语音查询传感器数值使用。

        优先级：
        1. 先读仿真后端 socket，这是最新、最实时的数据；
        2. 如果 socket 没启动，再读 rk3588/alarm_log.csv 或视觉 records.csv 的最后一行。

        这样做的好处是：
        - 仿真后端运行时，语音回答能跟 UI 看到的数值同步；
        - 后端没运行时，也能用最近一次日志给出尽量有用的回答。
        """
        live_status = self.get_live_vision_status()
        if live_status:
            return live_status
        return self.read_latest_status_from_logs()

    def read_latest_status_from_logs(self):
        """从本地日志里读取最后一条状态，作为 socket 断开时的备用数据。"""
        for csv_path in (self.rk_alarm_log_path, self.vision_csv_path, self.legacy_vision_csv_path):
            row = self.read_latest_csv_row(csv_path)
            if row:
                return self.normalize_status_row(row)

        for jsonl_path in (self.vision_jsonl_path, self.legacy_vision_jsonl_path):
            row = self.read_latest_jsonl_row(jsonl_path)
            if row:
                return self.normalize_status_row(row)

        return None

    def read_latest_csv_row(self, csv_path):
        """读取 CSV 最后一行。

        这里没有用 pandas，是为了让小白同学以后也容易看懂：
        csv.DictReader 会自动把表头变成字典 key。
        """
        if not csv_path.exists():
            return None

        latest = None
        try:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    latest = row
        except Exception as exc:
            print(f"[传感器] 读取 CSV 失败：{csv_path}，{exc}")
            return None
        return latest

    def read_latest_jsonl_row(self, jsonl_path):
        """读取 JSONL 最后一行。

        JSONL 是“一行一个 JSON 对象”的日志格式。
        视觉模块历史记录里会用到它。
        """
        if not jsonl_path.exists():
            return None

        latest = None
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        latest = json.loads(line)
        except Exception as exc:
            print(f"[传感器] 读取 JSONL 失败：{jsonl_path}，{exc}")
            return None
        return latest

    def normalize_status_row(self, row):
        """把不同日志来源的字段名统一成语音模块认识的字段名。"""
        data = dict(row)

        # rk3588/alarm_log.csv 用 vision_status 表示视觉/系统状态；
        # socket 和 records.csv 用 status。这里统一成 status。
        if not data.get("status") and data.get("vision_status"):
            data["status"] = data.get("vision_status")

        # 有些记录会把报警原因放在 alarm_reason，有些放在 reason。
        if not data.get("reason") and data.get("alarm_reason"):
            data["reason"] = data.get("alarm_reason")

        return data

    def load_threshold_config(self):
        """读取阈值配置。

        UI 里改的温度/湿度/电流阈值会保存到 rk3588/config.json。
        语音模块每次查询时重新读取一次，保证你改完阈值后不用重启语音。
        """
        threshold = dict(DEFAULT_THRESHOLD)
        if not self.threshold_config_path.exists():
            return threshold

        try:
            with open(self.threshold_config_path, "r", encoding="utf-8-sig") as f:
                user_threshold = json.load(f)
        except Exception as exc:
            print(f"[传感器] 读取阈值配置失败：{exc}")
            return threshold

        for key in threshold:
            if key in user_threshold:
                threshold[key] = user_threshold[key]
        return threshold

    def to_float(self, value):
        """把日志/socket 里的数值转成 float。

        有时数据是 32.1，有时可能是 "32.1°C" 这样的字符串。
        转换失败就返回 None，避免语音模块崩掉。
        """
        if value is None or value == "":
            return None
        try:
            text = str(value).strip()
            for unit in ("°C", "℃", "%", "A", "a", "V", "v", "度", "安", "伏"):
                text = text.replace(unit, "")
            return float(text)
        except Exception:
            return None

    def to_int(self, value):
        """把烟雾状态这类整数值安全转成 int。"""
        number = self.to_float(value)
        if number is None:
            return None
        return int(number)

    def reply_sensor_value(self, sensor_name):
        """回答单个传感器状态。

        `sensor_name` 的可选值：
        - temperature：环境温度
        - humidity：环境湿度
        - current：电流
        - temp_device：设备温度
        - smoke：烟雾
        """
        status = self.get_live_system_status()
        if not status:
            return "暂时读不到传感器数据，请先启动仿真后端。"

        threshold = self.load_threshold_config()

        if sensor_name == "temperature":
            value = self.to_float(status.get("temperature"))
            limit = self.to_float(threshold.get("temp_max"))
            if value is None:
                return "当前没有读到环境温度数值。"
            if limit is not None and value > limit:
                return f"当前环境温度 {value:.1f} 度，异常，超过上限 {limit:.1f} 度。"
            limit_text = f"{limit:.1f}" if limit is not None else "未知"
            return f"当前环境温度 {value:.1f} 度，正常，上限是 {limit_text} 度。"

        if sensor_name == "humidity":
            value = self.to_float(status.get("humidity"))
            min_limit = self.to_float(threshold.get("humidity_min"))
            max_limit = self.to_float(threshold.get("humidity_max"))
            if value is None:
                return "当前没有读到环境湿度数值。"
            if min_limit is not None and value < min_limit:
                return f"当前环境湿度 {value:.1f}%，异常，低于下限 {min_limit:.1f}%。"
            if max_limit is not None and value > max_limit:
                return f"当前环境湿度 {value:.1f}%，异常，超过上限 {max_limit:.1f}%。"
            min_text = f"{min_limit:.1f}" if min_limit is not None else "未知"
            max_text = f"{max_limit:.1f}" if max_limit is not None else "未知"
            return f"当前环境湿度 {value:.1f}%，正常，范围是 {min_text}% 到 {max_text}%。"

        if sensor_name == "current":
            value = self.to_float(status.get("current"))
            limit = self.to_float(threshold.get("current_max"))
            if value is None:
                return "当前没有读到电流数值。"
            if limit is not None and value > limit:
                return f"当前电流 {value:.2f} 安，异常，超过上限 {limit:.2f} 安。"
            limit_text = f"{limit:.2f}" if limit is not None else "未知"
            return f"当前电流 {value:.2f} 安，正常，上限是 {limit_text} 安。"

        if sensor_name == "temp_device":
            value = self.to_float(status.get("temp_device"))
            limit = self.to_float(threshold.get("temp_device_max"))
            if value is None:
                return "当前没有读到设备温度数值。"
            if limit is not None and value > limit:
                return f"当前设备温度 {value:.1f} 度，异常，超过上限 {limit:.1f} 度。"
            limit_text = f"{limit:.1f}" if limit is not None else "未知"
            return f"当前设备温度 {value:.1f} 度，正常，上限是 {limit_text} 度。"

        if sensor_name == "smoke":
            smoke = self.to_int(status.get("smoke"))
            smoke_alarm_enabled = int(self.to_float(threshold.get("smoke_alarm")) or 0)
            if smoke is None:
                return "当前没有读到烟雾数值。"
            if smoke_alarm_enabled and smoke != 0:
                return f"当前烟雾值 {smoke}，异常，已触发烟雾报警。"
            return f"当前烟雾值 {smoke}，正常，未检测到烟雾报警。"

        return "这个传感器我还不会查询。"

    def reply_voltage_status(self):
        """回答电压状态。

        电压字段来自仿真后端 socket / 日志。
        如果没有读到 voltage，语音模块不会假装正常，会明确告诉你缺数据。
        """
        status = self.get_live_system_status()
        if not status:
            return "暂时读不到传感器数据，请先启动仿真后端。"

        voltage = self.to_float(status.get("voltage") or status.get("voltage_v"))
        threshold = self.load_threshold_config()
        min_limit = self.to_float(threshold.get("voltage_min"))
        max_limit = self.to_float(threshold.get("voltage_max"))
        if voltage is None:
            return "当前系统还没有电压传感器数据，暂时不能判断电压是否正常。"
        if min_limit is not None and voltage < min_limit:
            return f"当前电压 {voltage:.1f} 伏，异常，低于下限 {min_limit:.1f} 伏。"
        if max_limit is not None and voltage > max_limit:
            return f"当前电压 {voltage:.1f} 伏，异常，超过上限 {max_limit:.1f} 伏。"
        min_text = f"{min_limit:.1f}" if min_limit is not None else "未知"
        max_text = f"{max_limit:.1f}" if max_limit is not None else "未知"
        return f"当前电压 {voltage:.1f} 伏，正常，范围是 {min_text} 到 {max_text} 伏。"

    def reply_sensor_summary(self):
        """回答传感器总状态，并带上关键数值。"""
        status = self.get_live_system_status()
        if not status:
            return "暂时读不到传感器数据，请先启动仿真后端。"

        threshold = self.load_threshold_config()
        temp = self.to_float(status.get("temperature"))
        humidity = self.to_float(status.get("humidity"))
        voltage = self.to_float(status.get("voltage") or status.get("voltage_v"))
        current = self.to_float(status.get("current"))
        temp_device = self.to_float(status.get("temp_device"))
        smoke = self.to_int(status.get("smoke"))
        temp_max = self.to_float(threshold.get("temp_max"))
        humidity_min = self.to_float(threshold.get("humidity_min"))
        humidity_max = self.to_float(threshold.get("humidity_max"))
        voltage_min = self.to_float(threshold.get("voltage_min"))
        voltage_max = self.to_float(threshold.get("voltage_max"))
        current_max = self.to_float(threshold.get("current_max"))
        temp_device_max = self.to_float(threshold.get("temp_device_max"))
        smoke_alarm_enabled = int(self.to_float(threshold.get("smoke_alarm")) or 0)

        problems = []
        if temp is not None and temp_max is not None and temp > temp_max:
            problems.append("环境温度过高")
        if humidity is not None and humidity_min is not None and humidity < humidity_min:
            problems.append("环境湿度过低")
        if humidity is not None and humidity_max is not None and humidity > humidity_max:
            problems.append("环境湿度过高")
        if voltage is not None and voltage_min is not None and voltage < voltage_min:
            problems.append("电压过低")
        if voltage is not None and voltage_max is not None and voltage > voltage_max:
            problems.append("电压过高")
        if current is not None and current_max is not None and current > current_max:
            problems.append("电流过载")
        if temp_device is not None and temp_device_max is not None and temp_device > temp_device_max:
            problems.append("设备温度过高")
        if smoke is not None and smoke_alarm_enabled and smoke != 0:
            problems.append("烟雾报警")

        values = []
        if temp is not None:
            values.append(f"温度 {temp:.1f} 度")
        if humidity is not None:
            values.append(f"湿度 {humidity:.1f}%")
        if voltage is not None:
            values.append(f"电压 {voltage:.1f} 伏")
        if current is not None:
            values.append(f"电流 {current:.2f} 安")
        if temp_device is not None:
            values.append(f"设备温度 {temp_device:.1f} 度")
        if smoke is not None:
            values.append(f"烟雾值 {smoke}")

        value_text = "，".join(values) if values else "暂无具体数值"
        if problems:
            return f"当前传感器异常：{'，'.join(problems)}。具体数值：{value_text}。"
        return f"当前传感器正常。具体数值：{value_text}。"

    def is_alarm_record(self, record):
        """Return True when a JSONL/CSV row represents a visual alarm.

        Older visual records were written as:
            {"alarm_type": "right_third_zone", "alarm_time": "..."}
        They do not contain status=ALARM and alarm_type does not include the
        literal word "alarm", so the old filter skipped real zone alarms. The
        presence of alarm_time/alarm_reason/zone_name is enough to treat the row
        as an alarm record.
        """
        status = str(record.get("status", "")).upper()
        alarm_type = str(record.get("alarm_type", "")).strip()
        alarm_time = str(record.get("alarm_time", "")).strip()
        alarm_reason = str(record.get("alarm_reason", "")).strip()
        zone_name = str(record.get("zone_name", "")).strip()

        return (
            status == "ALARM"
            or bool(alarm_type)
            or bool(alarm_time)
            or bool(alarm_reason)
            or bool(zone_name)
        )

    def load_alarm_records(self):
        """从 JSONL / CSV 里读取报警记录。

        重要参数：
        - JSONL 优先，因为它保留了更完整的原始结构；
        - CSV 作为备用，便于 Excel 打开查看。
        """
        records = []
        for jsonl_path in (self.vision_jsonl_path, self.legacy_vision_jsonl_path):
            if not jsonl_path.exists():
                continue
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        if self.is_alarm_record(obj):
                            records.append(obj)
            except Exception as exc:
                print(f"[查询] 读取 JSONL 失败：{jsonl_path}，{exc}")

        if records:
            return records

        for csv_path in (self.vision_csv_path, self.legacy_vision_csv_path):
            if not csv_path.exists():
                continue
            try:
                import csv

                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if self.is_alarm_record(row):
                            records.append(row)
            except Exception as exc:
                print(f"[查询] 读取 CSV 失败：{csv_path}，{exc}")

        return records

    def format_alarm_record_for_tts(self, record):
        """把单条报警记录转成适合 TTS 播报的话术。"""
        alarm_time = record.get("alarm_time") or record.get("timestamp") or "未知时间"
        alarm_type = self.format_alarm_type(record.get("alarm_type") or record.get("zone_name") or record.get("status") or "未知类型")
        alarm_reason = self.format_alarm_reason(record.get("alarm_reason") or record.get("reason") or "")
        return f"最近一次报警时间是 {alarm_time}，报警类型是 {alarm_type}。{alarm_reason}"

    def format_alarm_reason(self, reason):
        """Convert visual English/debug reasons into short Chinese TTS text."""
        reason = str(reason or "").strip()
        if not reason:
            return ""
        if "Intrusion into hazard zone" in reason or "Zone intrusion" in reason:
            return "检测到人员进入禁区。"
        return reason

    def format_alarm_type(self, alarm_type):
        """把视觉内部报警类型转成适合语音播报的中文。"""
        alarm_type = str(alarm_type or "").strip()
        type_map = {
            "right_third_zone": "右侧禁区",
            "ALARM": "报警",
            "UNKNOWN": "未知报警",
        }
        return type_map.get(alarm_type, alarm_type.replace("_", " "))

    def format_alarm_record_for_short_tts(self, record):
        """把单条报警记录压缩成一句更短的话术。"""
        alarm_time = record.get("alarm_time") or record.get("timestamp") or "未知时间"
        alarm_type = self.format_alarm_type(record.get("alarm_type") or record.get("zone_name") or record.get("status") or "未知类型")
        return f"{alarm_time} 的 {alarm_type}"

    def manual_save_current_frame(self):
        """手动保存当前画面。

        这里是纯语音侧的“确认回复”。
        真正的截图保存动作，由视觉模块的主流程配合完成。
        """
        try:
            result = self.vision_client.trigger_inspection()
            return format_vision_result("已保存当前巡检记录", result)
        except Exception as exc:
            print(f"[视觉连接] 保存当前画面失败：{exc}")
            return "已收到保存请求，但视觉模块暂时无法连接，请先启动视觉程序。"


def main():
    parser = argparse.ArgumentParser(description="语音唤醒、模式切换和视觉控制模块")
    parser.add_argument("--text", action="store_true", help="使用文本输入模拟语音识别，不打开麦克风")
    parser.add_argument("--socket", default=DEFAULT_VISION_SOCKET_PATH, help="视觉模块 Unix Socket 路径")
    args = parser.parse_args()

    assistant = VoiceAssistant(text_mode=args.text, vision_socket_path=args.socket)
    assistant.run()


if __name__ == "__main__":
    main()
