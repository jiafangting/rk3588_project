# RK3588 工业巡检系统 — 项目结构

离线工业巡检系统，由 STM32 采集传感器、RK3588 上的 C 主控做融合决策、Python 视觉/语音模块做检测和交互、PyQt 上位机做可视化。

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

构建：`cd rk3588 && make` → `./inspection`

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

常用命令（项目根目录下）：

```bash
# 调试：仅 Python（视觉 + 语音）
D:\anaconda3\envs\rk3588-ai\python.exe scripts/run_device.py

# 文本模式语音（不用麦克风）
D:\anaconda3\envs\rk3588-ai\python.exe scripts/run_device.py --voice-text

# 现场：C 主控 + Python 全启
bash scripts/start_system.sh
bash scripts/health_check.sh
bash scripts/stop_system.sh
```

## deploy/ — systemd 部署

```text
deploy/
├── inspection.service   # systemd unit（部署时把 /项目根目录/ 替换成实际路径）
└── install_service.sh   # 复制到 /etc/systemd/system/ 并 enable
```

## models/ — 模型权重

只放权重文件，例如 `models/yolo11n/yolo11n.pt`。不要把 Ultralytics 源码塞进来，用 pip 装。

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
