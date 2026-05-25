# RK3588 工业巡检系统 — 项目结构

离线工业巡检系统，由 STM32 采集传感器、RK3588 上的 C 主控做融合决策、Python 视觉/语音模块做检测和交互、PyQt 上位机做可视化。

> 说明
>
> 下面的目录说明尽量按“新人学习顺序”来写：先看整体，再看单个模块，最后看启动和部署入口。

## 顶层目录

```text
rk3588_project/
├── rk3588/         # C 主控（多线程 + STM32 串口 + 心跳，当前正式版）
├── stm32/          # STM32 端代码（FreeRTOS：sensor / alarm / uart）
├── vision/         # Python 视觉模块（YOLO 推理 + Unix Socket 服务）
├── voice/          # Python 语音模块（ASR / TTS / 唤醒 / 文本调试）
├── ui/             # PyQt 上位机（摄像头/传感器/报警/阈值面板）
├── models/         # 模型权重（不进 git，weights only）
├── scripts/        # 启动/停止/健康检查/演示入口
├── deploy/         # systemd 服务文件和安装脚本
├── archive/        # 已废弃但暂留备查的旧代码
├── PROJECT_STRUCTURE.md
└── .gitignore
```

**说明**

- `rk3588/` 是运行在 RK3588 上的 C 主控目录，负责多线程调度和报警决策。
- `stm32/` 是底层采集端，主要负责传感器和执行器。
- `vision/` 和 `voice/` 是 Python 侧能力模块，分别负责视觉和语音。
- `ui/` 是图形界面，适合做演示和参数调整。
- `scripts/` 是最常见的启动入口，建议先从这里跑通项目。

## rk3588/ — C 主控（当前版本）

多线程主控框架，5 个核心线程 + 共享 `SystemState` + 阈值配置。

```text
rk3588/
├── main.c                  # 主入口，启动 5 个线程，等待退出信号
├── system_state.h          # 全局共享状态结构（互斥锁保护）
├── threshold_config.c/.h   # config.json 加载，缺失时回退默认值
├── thread_sensor.c         # 串口读 STM32，失败时切模拟模式
├── thread_vision.c         # 通过 Unix Socket 查询 Python 视觉
├── thread_decision.c       # 传感器+视觉融合，触发报警
├── thread_alarm.c          # 报警执行，写 alarm_log.csv
├── thread_heartbeat.c      # 心跳监控（30s 阈值）
├── config.json             # 阈值配置示例
├── alarm_log.csv           # 报警日志（运行时追加）
├── Makefile
├── README.md
└── project_开发日志.md
```

**关键说明**

- `main.c` 是总入口，只负责“启动线程 + 收尾退出”，不写业务逻辑。
- `system_state.h` 是所有线程共享的数据中心。
- `threshold_config.c/.h` 负责读取 `config.json`，并在配置缺失时提供默认值。
- `thread_sensor.c` / `thread_vision.c` / `thread_decision.c` / `thread_alarm.c` / `thread_heartbeat.c` 分别对应采集、视觉查询、决策、报警和健康检查。

构建：`cd rk3588 && make` → `./inspection`

> 注意
>
> - `config.json` 里的阈值影响报警判断结果；
> - 如果模型、socket 或串口暂时不可用，代码里通常会有降级逻辑，方便先跑通整体流程。

## stm32/ — STM32 端

```text
stm32/
├── Core/
│   ├── sensor_task.c/.h    # 温湿度/电流/烟雾采样
│   ├── alarm_task.c/.h     # 蜂鸣器/LED 输出
│   └── uart_protocol.c/.h  # 与 RK3588 的协议
├── config/freertos_config.h
├── docs/stm32_开发日志.md
└── README.md
```

**说明**

- `sensor_task.c` 一般负责采样；
- `alarm_task.c` 一般负责执行器输出；
- `uart_protocol.c` 定义和 RK3588 通信的协议格式。

## vision/ — Python 视觉

```text
vision/
├── app/
│   ├── config.py                   # 路径与运行参数
│   ├── startup.py                  # 启动检查
│   ├── vision_main.py              # 正式入口
│   ├── vision_core.py              # 摄像头/模型/推理/决策辅助
│   ├── vision_pipeline.py          # 主循环
│   ├── vision_socket.py            # 给 C 主控的 Socket 服务
│   ├── vision_bridge.py            # 给语音/UI 调用的桥
│   ├── vision_logger.py            # 记录、截图、片段
│   └── voice_command_handler.py    # 处理语音指令
├── test/
│   ├── run_test.py
│   ├── vision_camera_test.py
│   ├── vision_save_frame_test.py
│   ├── mock_vision_socket_server.py
│   └── vision_test_guide.md
└── vision_开发日志.md
```

**说明**

- `config.py` 是视觉模块参数集中地，建议改参数先看这里。
- `startup.py` 负责启动前检查，避免主循环一开始就报错。
- `vision_main.py` 只是入口，真正逻辑在 `vision_pipeline.py`。
- `vision_socket.py` 是对外状态服务，UI、语音和 C 主控都可能查询它。
- `vision_bridge.py` 负责把“识别结果”变成“日志、截图、查询数据”。

## voice/ — Python 语音

```text
voice/
├── voice_loop.py            # 主循环（唤醒+ASR+TTS+查询）
├── asr_test.py / tts_test.py / record_test.py
├── voice_broadcast.py       # 报警播报
├── vision_control.py        # 通过 vision_bridge 查询视觉
├── test_text_vision_flow.py # 文本模式联调
├── README.md
└── voice_开发日志.md
```

**说明**

- `voice_loop.py` 是语音模块总入口；
- `voice_broadcast.py` 负责真正播报；
- `vision_control.py` 负责语音侧查询视觉状态。

## ui/ — PyQt 上位机

```text
ui/
├── main_window.py
├── widgets/
│   ├── camera_widget.py
│   ├── sensor_widget.py
│   ├── alarm_widget.py
│   └── threshold_widget.py
├── data/ui_state.py
├── README.md
└── ui_开发日志.md
```

**说明**

- `main_window.py` 负责组织整个界面；
- `ui_state.py` 是 UI 的统一数据中枢；
- `widgets/` 里每个文件对应一个功能面板。

## scripts/ — 启动入口

```text
scripts/
├── run_device.py        # Python 入口：同时启动视觉 + 语音
├── run_vision.py        # 仅启动视觉
├── start_system.sh      # Linux 一键启动 C 主控 + 视觉 + 语音
├── stop_system.sh       # 关闭所有模块
├── health_check.sh      # 检查进程和 socket 状态
└── alarm_voice_demo.py  # 答辩演示用单文件最小闭环
```

**常用命令说明**

```bash
# 调试：仅 Python（视觉 + 语音）
D:\anaconda3\envs\rk3588-ai\python.exe scripts/run_device.py
```

- 作用：启动 Python 侧的视觉和语音联动。
- 使用场景：没有先上 C 主控时，先验证 Python 联调。
- 前置条件：安装好 Python 环境和依赖。
- 注意事项：如果摄像头、模型或音频设备没装好，可能先报错。

```bash
# 文本模式语音（不用麦克风）
D:\anaconda3\envs\rk3588-ai\python.exe scripts/run_device.py --voice-text
```

- 作用：使用文本输入代替麦克风，方便调试。
- 使用场景：没有麦克风、想快速测试语音逻辑。
- 前置条件：语音模块依赖已安装。
- 注意事项：适合学习和联调，不代表最终语音硬件流程。

```bash
# 现场：C 主控 + Python 全启
bash scripts/start_system.sh
bash scripts/health_check.sh
bash scripts/stop_system.sh
```

- `start_system.sh`：启动全系统。
- `health_check.sh`：检查是否都有起来。
- `stop_system.sh`：结束所有相关进程。
- 使用场景：Linux 部署或正式演示。
- 注意事项：脚本通常依赖 systemd、socket、模型路径和权限。

## deploy/ — systemd 部署

```text
deploy/
├── inspection.service   # systemd unit（部署时把 /项目根目录/ 替换成实际路径）
└── install_service.sh   # 复制到 /etc/systemd/system/ 并 enable
```

**说明**

- `inspection.service` 是 systemd 服务文件，用于开机自启或后台守护。
- `install_service.sh` 负责安装和启用服务。

> 注意
>
> - 部署前通常需要把路径改成机器上的真实路径；
> - 如果服务启动失败，优先检查 `ExecStart`、工作目录和依赖环境。

## models/ — 模型权重

只放权重文件，例如 `models/yolo11n/yolo11n.pt`。不要把 Ultralytics 源码塞进来，用 pip 装。

**说明**

- 这里存放的是 YOLO 模型权重。
- 如果权重缺失，视觉模块通常无法正常启动。

## archive/ — 已废弃代码

```text
archive/
├── rk3588_main/          # 旧的 C 单体主控（vision_client + decision_engine），已被 rk3588/ 多线程版本取代
└── tools_use_cbuild.ps1  # 旧 Windows 构建包装脚本
```

留作历史备查，不参与构建。

## 不进版本控制的目录

`.gitignore` 已经覆盖：

- `__pycache__/`、`*.pyc`、`.pytest_cache/`、`.mypy_cache/`
- `*.o`、`*.exe`、C 主控可执行文件
- `.tmp/`、`debug.log`、`vision/**/output/`、`vision/records/`
- `*.pt`、`*.onnx`、`*.rknn`、`*.engine`
- `test.wav`

**说明**

- 这些目录或文件大多是运行时产物、缓存或大模型文件；
- 不纳入版本控制可以减少仓库体积，也避免误提交临时文件。

如果模型权重缺失，把 `yolo11n.pt` 放回 `models/yolo11n/`。

## 设备启动行为

```text
设备上电
├── C 主控启动 5 个线程（传感器/视觉/决策/报警/心跳）
├── 视觉模块自动持续检测，结果通过 Unix Socket 暴露
├── 语音模块进入待机，等待唤醒词
├── 视觉正常时不打扰
└── 视觉异常或决策报警时，触发语音播报 + 报警日志
```

**流程解释**

1. 设备上电后，RK3588 端先进入多线程主控状态。
2. 视觉模块持续工作并把最新状态发布出来。
3. 语音模块平时待机，收到唤醒后再工作。
4. UI 则负责展示这些状态，方便观察和调试。
