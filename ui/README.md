# UI 界面模块

## 快速上手

### 开发环境
- Python 3.8+
- PyQt5
- OpenCV

### 启动方式
```bash
python ui/main_window.py
```

### 模块说明
- `main_window.py`：主窗口入口
- `widgets/camera_widget.py`：摄像头画面组件
- `widgets/sensor_widget.py`：传感器数值组件
- `widgets/alarm_widget.py`：报警状态组件
- `widgets/threshold_widget.py`：阈值配置组件
- `data/ui_state.py`：统一数据状态管理

### 注意事项
- 视觉模块未启动时，界面会自动切换到模拟数据模式
- `alarm_log.csv` 和 `config.json` 路径要与 RK3588 主工程保持一致
- 如果要真机运行，建议在 RK3588 Linux 桌面环境下启动
