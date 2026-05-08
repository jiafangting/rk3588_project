# Voice 语音模块

这个目录是语音交互模块，核心能力是：

- 麦克风监听；
- 自动静音结束；
- 保存录音为 `test.wav`；
- 中文语音识别；
- 唤醒词触发；
- 待机模式 / 工作模式切换；
- 根据指令播报回复；
- 长时间无有效语音自动回待机；
- “停止 / 退出 / 结束”退出程序。

## 主程序

设备正式运行时，推荐从项目根目录启动统一入口：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe scripts\run_device.py
```

这个入口会同时启动：

- 视觉模块：自动连续检测；
- 语音模块：待机等待唤醒。

单独调试语音模块时，再运行：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\voice_loop.py
```

不能说话或不方便用麦克风时，可以用文本模拟模式：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\voice_loop.py --text
```

如果当前终端中文输入/管道有编码问题，可以用英文调试词：

```text
wake
mode
temp
inspect
vision
stop
```

唤醒词示例：

```text
小杜你好
小度你好
小杜
小度
```

工作模式下可说：

```text
当前温度多少
现在是什么模式
当前是什么模式
开始巡检
查询视觉状态
停止
```

也可以随便问，比如"中国首都是哪里""帮我讲个冷笑话""今天适合吃什么" —— 这些本地没命中的问题，会走云端通义千问回答。

## 开启在线问答（通义千问）

在 [阿里云百炼控制台](https://bailian.console.aliyun.com/?apiKey=1) 申请 API Key，然后：

```bash
pip install openai
set DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx
```

可选参数：

```bash
set LLM_MODEL=qwen-turbo    # 默认，最便宜最快。质量优先可换 qwen-plus / qwen-max
```

没有设置 `DASHSCOPE_API_KEY` 时，语音助手仍能正常响应温度/视觉/报警等本地指令，只是未命中时会回"暂时还没有对应的控制指令"，不影响主流程。

涉及设备实时数据（温度、电流、视觉报警等）的问题由本地逻辑优先处理，LLM 只负责闲聊和通识问答，不会对实时数值瞎编。

说明：

- `开始巡检 / 执行检测 / 截图 / 拍照` 会尝试触发视觉模块保存一次巡检结果；
- `查询视觉状态 / 当前视觉报警状态` 会尝试读取视觉模块当前状态；
- 使用视觉联动前，需要先启动 `python scripts/run_vision.py`。

如果暂时没有摄像头或模型，可以先启动模拟视觉服务：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe vision\test\mock_vision_socket_server.py
```

然后另开一个终端启动文本模式：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\voice_loop.py --text
```

输入：

```text
wake
vision
inspect
stop
```

这样可以先验证“语音模块 -> 视觉 Socket -> 语音播报结果”的联动链路。

注意：当前 Windows Python 环境如果不支持 Unix Domain Socket，会自动改用
`127.0.0.1:8765` TCP 通信；RK3588/Linux 上仍可使用 `/tmp/vision_inspection.sock`。

## 辅助测试

只测试播报：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\tts_test.py
```

测试视觉报警联动播报：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe vision\test\vision_voice_broadcast_test.py
```

测试语音文本模式和视觉命令解析：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\test_text_vision_flow.py
```

只测试录音：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\record_test.py
```
