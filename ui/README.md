# UI 界面模块

这个目录是图形界面模块的说明。
它负责把视觉状态、传感器状态、报警记录、阈值配置这些信息显示给用户看。

> 说明
>
> UI 这一层本身不做识别，也不做报警判断，它只是“读数据 + 展示数据 + 允许改参数”。

## 快速上手

### 开发环境

- Python 3.8+
- PyQt5
- OpenCV

#### 说明

- **Python 3.8+**：表示 Python 版本至少要 3.8。
- **PyQt5**：Qt 图形界面的 Python 绑定，用来做窗口、按钮、标签等控件。
- **OpenCV**：图像处理库，用来读取和显示摄像头图像、结果图。

### 启动方式

```bash
python ui/main_window.py
```

#### 作用

启动 UI 主窗口。

#### 使用场景

- 想单独看界面；
- 想调试摄像头、报警记录或阈值面板；
- 想和视觉模块联动查看实时结果。

#### 前置条件

- Python 环境已安装；
- 依赖已安装；
- 如果要显示真实数据，视觉模块或仿真服务要先启动。

#### 注意事项

- 如果视觉模块没启动，界面会尽量降级到模拟数据或旧记录；
- 如果某些路径不存在，先检查 `vision/app/output/` 和 `rk3588/config.json`。

### 模块说明

- `main_window.py`：主窗口入口，组织整个界面布局；
- `widgets/camera_widget.py`：摄像头画面组件；
- `widgets/sensor_widget.py`：传感器数值组件；
- `widgets/alarm_widget.py`：报警状态组件；
- `widgets/threshold_widget.py`：阈值配置组件；
- `data/ui_state.py`：统一数据状态管理。

#### 说明

- `main_window.py` 负责“排版”和“定时刷新”；
- `ui_state.py` 负责“统一取数”；
- `widgets/` 中每个文件只负责一个面板，方便学习和维护。

## 注意事项

- 视觉模块未启动时，界面会自动切换到模拟数据模式；
- `alarm_log.csv` 和 `config.json` 路径要与 RK3588 主工程保持一致；
- 如果要真机运行，建议在 RK3588 Linux 桌面环境下启动。

## 新手建议

建议先从这几个文件看：

1. `data/ui_state.py`：看 UI 怎么统一取数；
2. `main_window.py`：看界面怎么组装；
3. `widgets/camera_widget.py`：看画面怎么显示；
4. `widgets/sensor_widget.py`：看传感器数值怎么展示；
5. `widgets/alarm_widget.py`：看报警记录怎么显示；
6. `widgets/threshold_widget.py`：看阈值怎么读写。
