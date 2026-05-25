# RK3588 工业巡检系统

这是一个面向工业巡检场景的多模块项目，包含：

- `stm32/`：传感器采集与执行器控制；
- `rk3588/`：C 端主控，多线程融合判断；
- `vision/`：Python 视觉识别与 socket 服务；
- `voice/`：Python 语音交互与播报；
- `ui/`：PyQt 上位机界面；
- `scripts/`：启动、停止和演示脚本。

## 项目目标

这个项目的目标是把“采集、识别、判断、报警、展示、语音交互”串成一个完整闭环。

你可以先把它理解成下面这条链路：

```text
STM32 传感器 -> RK3588 主控 -> 视觉识别 -> 报警决策 -> UI / 语音 / 日志
```

## 目录结构

```text
rk3588_project/
├── stm32/
├── rk3588/
├── vision/
├── voice/
├── ui/
├── scripts/
├── models/
└── archive/
```

## 推荐阅读顺序

如果你是新手，建议按这个顺序看：

1. `PROJECT_STRUCTURE.md`
2. `rk3588/README.md`
3. `vision/README.md`
4. `voice/README.md`
5. `ui/README.md`
6. `stm32/README.md`
7. `scripts/README.md`

## 启动建议

### 软件仿真

```powershell
python scripts/run_software_simulation.py --reset
```

作用：先不接硬件，用软件把整套流程跑通。

### UI 界面

```powershell
python ui/main_window.py
```

作用：打开上位机界面查看状态。

### 语音文本模式

```powershell
python voice/voice_loop.py --text
```

作用：不用麦克风，直接在终端输入文本测试语音逻辑。

### RK3588 主控

```bash
cd rk3588 && make && ./inspection
```

作用：启动 C 端主控多线程流程。

## 核心参数

这些参数最值得先看：

- `CAMERA_INDEX`：摄像头编号；
- `YOLO_CONF`：YOLO 置信度阈值；
- `STABLE_FRAMES_REQUIRED`：稳定帧数；
- `ALARM_FRAMES_REQUIRED`：报警投票帧数；
- `VISION_SOCKET_PATH`：视觉 socket 路径；
- `temp_max / humidity_min / humidity_max / voltage_min / voltage_max / current_max / temp_device_max / smoke_alarm`：报警阈值。

## 运行时会产生什么

- `vision/app/output/photos/live_frame.jpg`：最新画面；
- `vision/app/output/recodes/records.csv`：巡检记录；
- `rk3588/alarm_log.csv`：主控运行日志。

## 学习建议

先弄明白三件事：

1. 数据从哪里来；
2. 数据怎么在模块之间传；
3. 最后谁来决定报警。

只要你把这三件事看懂，整个项目就基本通了。
