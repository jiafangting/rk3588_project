"""通用闲聊问答客户端。

这个文件的作用是：
当本地规则无法判断用户想问什么时，把语音识别文本交给云端大模型，
让它做“自由闲聊回答”。

它和设备查询模块的区别：
- 设备查询：问温度、报警、视觉状态时，应该走本地/实时数据；
- 闲聊问答：问天气、随便聊天、讲故事等，可以交给大模型。

设计意图：
- 当语音助手匹配不到设备查询指令时（温度/视觉/报警等都没命中），
  把用户原话交给云端 LLM，自由回答；
- 涉及当前设备实时数据的问题，由 system prompt 引导模型让用户现场查询，
  避免编造数值。

流程：
1. 初始化 OpenAI 兼容客户端；
2. `classify_intent()` 先把语音文本分类成“设备指令”或“聊天”；
3. 如果是聊天，就调用 `ask()` 直接生成回复；
4. 如果是设备指令，则交给本地控制逻辑处理。

关键参数：
- `DASHSCOPE_API_KEY`：阿里云百炼 API Key
- `LLM_MODEL`：默认模型名，默认 `qwen-turbo`
- `LLM_BASE_URL`：OpenAI 兼容接口地址
- `history_turns`：保留几轮上下文记忆
- `timeout`：请求超时秒数

依赖：
- `pip install openai`
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
    "3) 涉及当前设备的温度、湿度、电压、电流、烟雾、视觉报警等实时数据时，"
    "回答“这个需要现场查询”，绝对不要编造具体数值；"
    "4) 回答直接给结论，不要客套寒暄、不要重复用户的问题。"
)

INTENT_PROMPT = (
    "你是语音指令纠错器。用户语音识别文本可能有同音错字。"
    "请只从这些意图中选择一个：alarm_query, latest_alarm, alarm_count, "
    "vision_status, trigger_inspection, temperature, humidity, current, voltage, smoke, "
    "mode, stop, standby, chat。"
    "输出严格 JSON，格式：{\"intent\":\"...\"}。"
    "例子：有没有抱枪=>alarm_query；报警了几次=>alarm_count；"
    "最近一次抱紧是什么时候=>latest_alarm；开始寻衅=>trigger_inspection。"
)


class LLMChat:
    """带短期记忆的同步问答客户端。

    这个类是“把一句话发给大模型，再把结果拿回来”的封装。
    它会保留少量上下文，避免每一句都像第一次聊天。
    """

    def __init__(self, model=None, history_turns=3, timeout=10):
        """初始化聊天客户端。

        参数：
        - `model`：模型名，默认从环境变量 `LLM_MODEL` 读取，否则用 `DEFAULT_MODEL`
        - `history_turns`：保留几轮对话记忆
        - `timeout`：请求超时时间，单位秒

        说明：
        - `history_turns * 2` 是因为一轮对话包含“用户一句 + 助手一句”；
        - 这样保留少量上下文，能让闲聊更自然，但不会无限增长。
        """
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
        """同步问答，返回字符串。

        参数：
        - `user_text`：用户输入的原始文本

        返回值：
        - 大模型回复文本
        - 失败时返回友好提示，不抛异常

        流程：
        1. 先把系统提示词和历史对话拼起来；
        2. 再追加本次用户输入；
        3. 请求云端模型；
        4. 取出回复文本；
        5. 写入历史记忆。
        """
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
        """用大模型把有噪声的识别文本映射成本地意图。

        参数：
        - `user_text`：语音识别后得到的原始文本，可能有错字、同音字

        返回值：
        - 预定义意图之一：`alarm_query`、`latest_alarm`、`vision_status` 等
        - 如果无法识别，则返回 `chat`

        原理：
        - 用一个专门的意图提示词约束模型只输出 JSON；
        - 通过低温度 `temperature=0` 让分类结果更稳定；
        - 如果模型输出不是合法 JSON，也会做容错解析。
        """
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
            "humidity",
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
