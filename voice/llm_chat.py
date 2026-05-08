"""通用闲聊问答客户端（阿里云 DashScope 通义千问，OpenAI 兼容协议）。

设计意图：
    - 当语音助手匹配不到设备查询指令时（温度/视觉/报警 等都没命中），
      把用户原话扔给云端 LLM，让它自由回答 ——“问什么答什么”。
    - 涉及当前设备实时数据的问题，由 system prompt 引导模型让用户现场查询，
      避免瞎编数值。

环境变量：
    DASHSCOPE_API_KEY  必填，阿里云百炼控制台申请：
                       https://bailian.console.aliyun.com/?apiKey=1
    LLM_MODEL          可选，默认 qwen-turbo（最便宜+最快，闲聊够用）
                       质量优先可换 qwen-plus / qwen-max
    LLM_BASE_URL       可选，默认走 DashScope 官方 OpenAI 兼容端点

依赖：
    pip install openai
"""

from __future__ import annotations

import os
import json
from collections import deque

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-turbo"

SYSTEM_PROMPT = (
    "你是 RK3588 工业巡检设备上的语音助手，名字叫小杜。"
    "你的回答会被 TTS 直接朗读出来，请严格遵守："
    "1) 用口语化中文，每次回答控制在 50 字以内；"
    "2) 不要使用 markdown、列表符号、表情、括号注释；"
    "3) 涉及当前设备的温度、电流、电压、烟雾、视觉报警等实时数据时，"
    "回答“这个需要现场查询”，绝对不要编造具体数值；"
    "4) 回答直接给结论，不要客套寒暄、不要重复用户的问题。"
)

INTENT_PROMPT = (
    "你是语音指令纠错器。用户语音识别文本可能有同音错字。"
    "请只从这些意图中选择一个：alarm_query, latest_alarm, alarm_count, "
    "vision_status, trigger_inspection, temperature, current, voltage, smoke, "
    "mode, stop, standby, chat。"
    "输出严格 JSON，格式：{\"intent\":\"...\"}。"
    "例子：有没有抱枪=>alarm_query；报警了几次=>alarm_count；"
    "最近一次抱紧是什么时候=>latest_alarm；开始寻衅=>trigger_inspection。"
)


class LLMChat:
    """带短期记忆的同步问答客户端。"""

    def __init__(self, model=None, history_turns=3, timeout=10):
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.history = deque(maxlen=history_turns * 2)

        api_key = os.environ.get("DASHSCOPE_API_KEY")
        base_url = os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL

        self._client = None
        self._init_error = None
        if OpenAI is None:
            self._init_error = "未安装 openai 包，请运行 pip install openai"
        elif not api_key:
            self._init_error = "未设置环境变量 DASHSCOPE_API_KEY"
        else:
            self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    @property
    def enabled(self):
        return self._client is not None

    def ask(self, user_text):
        """同步问答，返回字符串。失败时返回友好提示，不抛异常。"""
        if not self.enabled:
            return f"在线问答功能未启用，{self._init_error}。"

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_text})

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=self.timeout,
            )
        except Exception as exc:
            return f"在线问答暂时连不上，{exc}。"

        reply = (resp.choices[0].message.content or "").strip()
        if not reply:
            return "抱歉，我没想好怎么回答。"

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def classify_intent(self, user_text):
        """Use LLM to map noisy ASR text to one local command intent."""
        if not self.enabled:
            return "chat"

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": INTENT_PROMPT},
                    {"role": "user", "content": str(user_text)},
                ],
                temperature=0,
                timeout=self.timeout,
            )
        except Exception as exc:
            print(f"[LLM] 意图识别失败：{exc}")
            return "chat"

        content = (resp.choices[0].message.content or "").strip()
        try:
            data = json.loads(content)
            intent = str(data.get("intent", "chat")).strip()
        except Exception:
            intent = content.strip().strip('"').strip("'")

        allowed = {
            "alarm_query",
            "latest_alarm",
            "alarm_count",
            "vision_status",
            "trigger_inspection",
            "temperature",
            "current",
            "voltage",
            "smoke",
            "mode",
            "stop",
            "standby",
            "chat",
        }
        return intent if intent in allowed else "chat"

    def reset(self):
        self.history.clear()
