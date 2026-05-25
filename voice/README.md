# Voice 语音模块

这个目录是语音交互模块的说明文档。
它负责把“人说的话”变成“系统能执行的动作或能播报的回复”。

> 说明
>
> 这个模块本身不负责视觉识别，它主要负责语音输入、语音输出、指令分流和与视觉模块联动。

## 这个模块做什么

语音模块主要负责以下几类任务：

- 麦克风监听；
- 自动静音结束；
- 保存录音；
- 中文语音识别（ASR，Automatic Speech Recognition，即语音转文字）；
- 唤醒词触发；
- 待机模式 / 工作模式切换；
- 根据指令播报回复；
- 长时间无有效语音自动回待机；
- “停止 / 退出 / 结束”退出程序。

## 主程序入口

设备正式运行时，推荐从项目根目录启动统一入口：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe scripts\run_device.py
```

### 这条命令的作用

启动整套设备流程，通常包括：

- 视觉模块连续检测；
- 语音模块待机并等待唤醒；
- 需要时再触发巡检、查询状态或播报信息。

### 使用场景

- 真机联调；
- 演示系统；
- 想一次启动整套设备时。

### 前置条件

- 已安装 Python 环境；
- 已安装语音模块依赖；
- 如果要接麦克风和扬声器，设备权限已准备好。

### 注意事项

- 如果没有摄像头或模型，视觉部分要先用模拟服务或单独视觉入口；
- 如果没有 API Key，在线问答会不可用，但本地指令仍可工作。

## 单独调试语音模块

单独运行语音循环：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\voice_loop.py
```

### 作用

单独测试语音识别、唤醒词、播报和命令分流。

### 使用场景

- 调试 ASR；
- 调试唤醒词；
- 调试本地语音回复；
- 验证语音和视觉联动。

### 前置条件

- 麦克风可用；
- 如果需要播报，扬声器可用；
- 依赖已安装。

### 注意事项

- 语音流程通常要配合“静音检测”和“唤醒词”一起看；
- 如果没声音，可以先用文本模式排查逻辑。

## 文本模拟模式

不能说话或不方便用麦克风时，可以用文本模拟模式：

```bash
D:\anaconda3\envs\rk3588-ai\python.exe voice\voice_loop.py --text
```

### 作用

不用麦克风，直接在终端输入文字测试整个语音逻辑。

### 使用场景

- 新手学习；
- 没有麦克风；
- 只想先验证指令处理逻辑；
- 调试语音到视觉的联动。

### 输入示例

```text
wake
mode
temp
inspect
vision
stop
```

### 注意事项

- 文本模式只适合学习和调试；
- 真正演示时还是要走麦克风输入。

## 唤醒词示例

```text
小杜你好
小度你好
小杜
小度
```

### 说明

这些词会触发语音模块进入工作模式。
“工作模式”通常表示后面的命令会被认真处理，而不是当成普通聊天。

## 工作模式下可说的指令

```text
当前温度多少
现在是什么模式
当前是什么模式
开始巡检
查询视觉状态
停止
```

### 说明

- `当前温度多少`：询问设备或环境温度；
- `现在是什么模式`：查询系统当前工作模式；
- `开始巡检`：尝试触发一次巡检保存；
- `查询视觉状态`：查询视觉模块当前状态；
- `停止`：退出或结束当前工作流程。

## 在线问答（通义千问）

也可以随便问，比如：

```text
中国首都是哪里
帮我讲个冷笑话
今天适合吃什么
```

这些问题如果本地没命中，就会走云端通义千问回答。

### 开启方式

在 [阿里云百炼控制台](https://bailian.console.aliyun.com/?apiKey=1) 申请 API Key，然后：

```bash
pip install openai
set DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx
```

#### 这条命令的作用

- `pip install openai`：安装 OpenAI 兼容客户端；
- `set DASHSCOPE_API_KEY=...`：设置云端 API Key。

#### 使用场景

- 需要在线问答；
- 需要语音助手在本地指令之外继续聊天。

#### 前置条件

- 网络可用；
- 账号已申请 API Key；
- 已安装 `openai` 包。

#### 注意事项

- 没有 API Key 时，语音助手仍能响应本地指令，只是在线闲聊不可用；
- 涉及实时数据的问题不要依赖 LLM 乱猜。

### 模型参数

```bash
set LLM_MODEL=qwen-turbo
```

#### 参数说明

- `qwen-turbo`：默认模型，便宜、速度快，适合闲聊；
- 也可以改成 `qwen-plus` 或 `qwen-max`，通常质量更高，但成本更高。

## 视觉联动说明

说明：

- `开始巡检 / 执行检测 / 截图 / 拍照` 会尝试触发视觉模块保存一次巡检结果；
- `查询视觉状态 / 当前视觉报警状态` 会尝试读取视觉模块当前状态；
- 使用视觉联动前，需要先启动视觉模块或模拟视觉服务。

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

### 注意

当前 Windows Python 环境如果不支持 Unix Domain Socket，会自动改用 `127.0.0.1:8765` TCP 通信；RK3588/Linux 上仍可使用 `/tmp/vision_inspection.sock`。

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

### 说明

这些测试命令主要用于验证某个单独功能，不代表完整系统入口。
如果你是新手，建议先看主流程，再回来看这些辅助测试。
