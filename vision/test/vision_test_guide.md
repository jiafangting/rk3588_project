# vision/test 测试入口说明

这个目录只放开发和验收用的测试脚本，不作为正式业务入口。

## 常用脚本

### 1. 摄像头测试

文件：`vision_camera_test.py`

作用：

- 检查摄像头能不能打开；
- 检查能不能读到画面；
- 适合先做最基础的硬件确认。

### 2. 保存单帧测试

文件：`vision_save_frame_test.py`

作用：

- 从摄像头抓一帧图像；
- 保存到 `vision/test/output/`；
- 验证“摄像头 -> 图像文件”这条链路。

### 3. 测试菜单

文件：`run_test.py`

作用：

- 打印测试菜单；
- 通过编号选择测试脚本；
- 方便快速切换不同测试。

### 4. 视觉报警语音联动测试

文件：`vision_voice_broadcast_test.py`

作用：

- 不打开摄像头；
- 不加载 YOLO；
- 直接模拟视觉正常、异常、报警结果；
- 验证语音模块能不能播报报警内容。

### 5. Mock 视觉 Socket 服务

文件：`mock_vision_socket_server.py`

作用：

- 不打开摄像头；
- 不加载 YOLO；
- 模拟视觉 Socket 协议；
- 用来测试语音模块的 `查询视觉状态` 和 `开始巡检`。

## 推荐测试顺序

1. 先运行 `vision_camera_test.py`
2. 再运行 `vision_save_frame_test.py`
3. 再运行 `vision_voice_broadcast_test.py`
4. 如果要测试语音控制视觉，先运行 `mock_vision_socket_server.py`
5. 最后运行正式入口 `python scripts/run_vision.py`

## 正式入口和测试入口区别

正式入口：

```bash
python scripts/run_vision.py
```

测试入口：

```bash
python vision/test/run_test.py
```

测试脚本只用于调试，不要把正式业务逻辑写进 `vision/test`。
