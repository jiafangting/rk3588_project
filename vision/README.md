# vision 视觉模块

这个目录是 Python 视觉模块的说明文档。
它负责从摄像头读取画面、运行 YOLO 推理、判断视觉状态，并把结果通过 Socket、日志和截图对外提供。

> 说明
>
> 这一层主要做“看图 + 识别 + 输出状态”，不负责 UI 排版，也不负责语音播报。

## 这个模块做什么

视觉模块主要负责以下工作：

- 打开摄像头并读取视频帧；
- 使用 YOLO 模型做目标检测；
- 判断当前画面是否正常、异常或报警；
- 生成截图、记录和短视频；
- 通过 Unix Socket / TCP 向 UI、语音模块和 C 主控提供状态查询；
- 接收语音或 UI 发来的巡检触发命令。

## 目录结构

```text
vision/
├── app/
│   ├── config.py                   # 视觉模块参数、路径和默认阈值
│   ├── startup.py                  # 启动前检查
│   ├── vision_main.py              # 正式入口
│   ├── vision_core.py              # 摄像头、模型、推理、决策、TTS 工具
│   ├── vision_pipeline.py          # 主循环
│   ├── vision_socket.py            # 状态查询 Socket 服务
│   ├── vision_bridge.py            # 记录、截图、联动桥
│   ├── vision_logger.py            # 文件记录工具
│   └── voice_command_handler.py    # 语音指令处理
├── test/
│   ├── run_test.py
│   ├── vision_camera_test.py
│   ├── vision_save_frame_test.py
│   ├── mock_vision_socket_server.py
│   └── vision_test_guide.md
└── vision_开发日志.md
```

## 主入口

正式运行时推荐使用：

```bash
python vision/app/vision_main.py
```

### 作用

启动视觉模块主流程。

### 运行顺序

1. 检查配置是否有效；
2. 检查模型和输出目录；
3. 打开摄像头；
4. 进入实时检测主循环；
5. 将结果发布给 UI、语音和 C 主控。

## 关键参数

这些参数主要在 `vision/app/config.py` 中：

- `CAMERA_INDEX`：摄像头编号；
- `YOLO_CONF`：目标检测置信度阈值；
- `MIN_PERSON_SCORE`：人员检测最低分数；
- `STABLE_FRAMES_REQUIRED`：稳定帧数；
- `NO_PERSON_FRAMES_REQUIRED`：无人状态确认帧数；
- `ALARM_FRAMES_REQUIRED`：报警投票帧数；
- `ALARM_COOLDOWN_SECONDS`：报警冷却时间；
- `HAZARD_ZONE_MIN_OVERLAP_RATIO`：禁区命中比例；
- `TTS_RATE`：语速；
- `TTS_VOLUME`：音量。

## 输出文件

视觉模块运行后通常会生成这些内容：

- `vision/app/output/photos/live_frame.jpg`：最新画面；
- `vision/app/output/recodes/records.csv`：巡检记录；
- `vision/app/output/recodes/records.jsonl`：巡检记录的结构化版本；
- `vision/app/output/clips/`：报警短视频（如果开启）。

## 与其他模块的关系

- 与 `ui/`：UI 通过 socket 查询视觉状态，并读取结果图和记录；
- 与 `voice/`：语音模块通过 socket 查询当前视觉状态或触发巡检；
- 与 `rk3588/`：C 主控也会查询视觉状态并参与报警决策。

## 新手建议

建议按这个顺序看：

1. `app/config.py`：先看参数和路径；
2. `app/vision_main.py`：看入口怎么启动；
3. `app/startup.py`：看启动前检查；
4. `app/vision_core.py`：看摄像头、推理和决策工具；
5. `app/vision_pipeline.py`：看主循环；
6. `app/vision_socket.py`：看状态如何被外部查询。
