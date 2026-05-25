# 软件仿真版工业巡检系统运行指南

这份文档给“小白阶段的自己”看：先不用买 STM32、传感器、摄像头，也能把项目跑成一个完整闭环。

## 1. 仿真版在模拟什么

真实系统以后会长这样：

```text
STM32 传感器 -> RK3588 C 主控 -> 决策报警 -> 视觉 / 语音 / UI 展示
```

现在没有硬件，所以先用 Python 仿真器代替真实设备：

```text
软件仿真器
  -> 模拟 STM32 传感器数据
  -> 模拟视觉 NORMAL / ABNORMAL / ALARM 状态
  -> 按 rk3588/config.json 做报警判断
  -> 写入 CSV / JSONL 记录
  -> 提供 vision socket 给 UI 和语音模块查询
```

也就是说，`scripts/run_software_simulation.py` 暂时扮演了这几个角色：

- STM32：生成温度、湿度、电压、电流、设备温度、烟雾数据；
- 摄像头 + YOLO：生成正常、异常、禁区报警等视觉状态；
- RK3588 决策层：判断当前是否报警；
- 视觉 socket 服务端：让 UI、语音模块可以通过 `get_status` 查询状态；
- 日志模块：写入 `vision/app/output/recodes/records.csv` 和 `rk3588/alarm_log.csv`。

## 2. 启动仿真后端

在项目根目录运行：

```powershell
python scripts/run_software_simulation.py --reset
```

如果你的终端提示 `python` 不是命令，就用项目里一直使用的 Conda 环境：

```powershell
D:\anaconda3\envs\rk3588-ai\python.exe scripts/run_software_simulation.py --reset
```

参数说明：

- `--reset`：启动前清空旧的仿真记录，方便看本次运行结果；
- 不加 `--reset`：保留旧记录，继续往后追加。

启动后，你会看到类似输出：

```text
[SIM] 软件仿真系统已启动
[SIM] 2026-05-10 12:30:00 | normal | NORMAL | T=28.1 H=54.6 I=3.21 Smoke=0 | 模拟巡检正常，检测到 1 名人员
```

这说明仿真后端已经开始持续生成状态。

## 2.1 Windows 一键启动演示

如果你想一次打开仿真后端、UI、语音文本模式，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_software_simulation_demo.ps1
```

这个脚本默认会让仿真后端尝试接入你电脑的 0 号摄像头。
如果摄像头打不开，仿真器会自动回退到软件绘制的车间画面。

它会打开三个窗口：

- `RK3588 软件仿真后端`：持续生成仿真数据；
- `RK3588 仿真 UI`：显示仿真画面和状态；
- `RK3588 语音文本模式`：输入 `wake`、`vision`、`有没有报警` 等命令。

如果只想启动后端，不打开 UI 和语音：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_software_simulation_demo.ps1 -NoUi -NoVoice
```

如果你的电脑有多个摄像头，可以换编号：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_software_simulation_demo.ps1 -CameraIndex 1
```

如果你暂时不想用电脑摄像头，只想用软件绘制的仿真画面：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_software_simulation_demo.ps1 -NoCamera
```

如果视频还是觉得卡，可以把摄像头刷新率调高一点，例如 20fps：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_software_simulation_demo.ps1 -VideoFps 20
```

## 3. 启动 UI 查看仿真状态

另开一个终端，运行：

```powershell
python ui/main_window.py
```

如果 `python` 不在 PATH：

```powershell
D:\anaconda3\envs\rk3588-ai\python.exe ui/main_window.py
```

UI 会从仿真后端读取：

- 顶部系统状态：正常 / 异常 / 报警；
- 左侧仿真画面：由 `live_frame.jpg` 生成；
- 右侧传感器数值：温度、湿度、电压、电流、设备温度、烟雾；
- 报警记录：最近几条仿真巡检记录；
- 阈值配置：读取 `rk3588/config.json`。

如果你在 UI 里保存阈值，UI 会发送 `reload_config` 到仿真 socket。仿真器下一帧会重新读取配置。

## 4. 启动语音文本模式测试

没有麦克风也可以测语音逻辑。另开终端运行：

```powershell
python voice/voice_loop.py --text
```

如果 `python` 不在 PATH：

```powershell
D:\anaconda3\envs\rk3588-ai\python.exe voice/voice_loop.py --text
```

可以输入：

```text
wake
vision
当前温度多少
当前湿度多少
当前电压多少
当前电流多少
有没有报警
报警几次
最近一次报警是什么
帮我保存一下
stop
```

对应效果：

- `wake`：进入工作模式；
- `vision`：查询当前仿真视觉状态；
- `当前温度多少 / 当前湿度多少 / 当前电压多少 / 当前电流多少`：读取实时仿真传感器值，并按阈值判断是否正常；
- `有没有报警`：优先查实时 socket，查不到再读历史记录；
- `报警几次`：统计历史报警记录数量，并补充当前是否也在报警；
- `最近一次报警是什么`：读取仿真日志；
- `帮我保存一下`：向仿真器发送 `trigger_inspection`，仿真器立刻写一条巡检记录；
- `stop`：退出语音文本模式。

## 5. 仿真场景怎么轮换

仿真器内置了 5 个场景：

1. `normal`
   - 传感器正常；
   - 视觉正常；
   - 系统状态为 `NORMAL`。

2. `abnormal_empty_area`
   - 传感器正常；
   - 视觉暂时没检测到人员；
   - 系统状态为 `ABNORMAL`。

3. `smoke_alarm`
   - 烟雾传感器模拟报警；
   - 系统状态为 `ALARM`。

4. `zone_alarm`
   - 视觉模拟人员进入右侧禁区；
   - 系统状态为 `ALARM`。

5. `current_alarm`
   - 电流超过 `rk3588/config.json` 里的 `current_max`；
   - 系统状态为 `ALARM`。

默认每 2 秒生成一帧，每 4 帧换一个场景。你可以这样改：

```powershell
python scripts/run_software_simulation.py --reset --interval 1 --scenario-ticks 6
```

含义：

- `--interval 1`：每 1 秒刷新一次；
- `--scenario-ticks 6`：每个场景停留 6 帧，也就是 6 秒。

如果你想让仿真视频直接使用电脑摄像头：

```powershell
python scripts/run_software_simulation.py --reset --camera
```

如果 0 号摄像头不是你想用的那个，可以换编号：

```powershell
python scripts/run_software_simulation.py --reset --camera --camera-index 1
```

如果只手动启动仿真后端，也可以调视频刷新率：

```powershell
python scripts/run_software_simulation.py --reset --camera --video-fps 20
```

## 6. 你应该重点读哪几个文件

建议按这个顺序读：

1. `scripts/run_software_simulation.py`
   - 先看 `SCENARIOS`：理解仿真场景；
   - 再看 `decide_alarm()`：理解报警判断；
   - 再看 `SoftwareInspectionSimulator.update_once()`：理解“一帧数据”怎么生成；
   - 最后看 `handle_socket_command()`：理解语音和 UI 怎么跟仿真器通信。

2. `ui/data/ui_state.py`
   - 看 UI 怎么统一读取 socket、CSV、配置文件；
   - 这相当于 UI 的数据中枢。

3. `voice/vision_control.py`
   - 看语音模块怎么向视觉 socket 发送 `get_status` 和 `trigger_inspection`。

4. `rk3588/thread_decision.c`
   - 对照 Python 的 `decide_alarm()`；
   - 你会发现 C 主控里的报警判断和仿真器是同一套思路。

## 7. 后面买硬件以后怎么替换

现在：

```text
run_software_simulation.py 生成假传感器数据
```

以后：

```text
STM32 通过串口发送真实传感器数据
```

现在：

```text
run_software_simulation.py 生成假视觉状态
```

以后：

```text
vision/app/vision_pipeline.py 使用摄像头和 YOLO 生成真实视觉状态
```

所以你现在写的 UI、语音查询、日志读取、阈值配置都不会白费。仿真版的目标就是先把系统逻辑学明白、演示跑顺，等硬件到了再把“假输入”换成“真输入”。
