# STM32 端说明

这个目录是 STM32 固件相关代码的说明文档。
它负责传感器采样、执行器控制，以及和 RK3588 之间的串口通信。

> 说明
>
> STM32 更接近“硬件执行层”，通常负责采集和控制，不负责复杂识别。

## 这个模块做什么

STM32 端主要负责：

- 读取温度、湿度、电流、烟雾等传感器；
- 处理蜂鸣器、LED、继电器等报警输出；
- 通过 UART 把数据发给 RK3588；
- 接收 RK3588 发来的控制命令；
- 运行在 FreeRTOS 上的任务调度中。

## 目录结构

```text
stm32/
├── Core/
│   ├── sensor_task.c/.h    # 传感器采集任务
│   ├── alarm_task.c/.h     # 报警执行任务
│   ├── uart_protocol.c/.h  # 串口协议
│   └── freertos_app.c/.h   # 队列和任务创建入口
├── config/freertos_config.h
├── docs/stm32_开发日志.md
└── README.md
```

## 主要任务说明

### sensor_task.c

负责采集传感器数据，并打包成通信协议。

#### 常见数据

- 环境温度
- 环境湿度
- 设备温度
- 电流
- 烟雾

### alarm_task.c

负责执行报警动作，例如：

- 蜂鸣器响；
- LED 闪烁；
- 继电器开关。

### uart_protocol.c

负责 RK3588 与 STM32 之间的数据格式。

#### 作用

- 统一发送格式；
- 统一解析格式；
- 方便以后扩展更多字段。

### freertos_app.c

负责创建 FreeRTOS 队列和任务。

当前创建了：

- `gSensorQueue`：传感器数据队列；
- `gAlarmQueue`：报警命令队列；
- `vSensorTask`：传感器采集任务；
- `uart_sensor_send_task`：串口传感器发送任务；
- `uart_receive_task`：串口接收任务；
- `vAlarmTask`：报警执行任务。

接入完整 CubeMX 工程时，在 `MX_FREERTOS_Init()` 或 `vTaskStartScheduler()` 之前调用：

```c
app_freertos_init();
```

## 运行方式

STM32 固件不是通过 `python` 启动的，而是通过烧录进开发板后运行。

### 一般流程

1. 用 STM32CubeIDE 或其他工具编译；
2. 下载固件到板子；
3. 上电运行；
4. 通过串口与 RK3588 联动。

## 与 RK3588 的关系

- STM32 是数据采集和执行器控制端；
- RK3588 是上层主控端；
- 两者通过串口协议通信；
- RK3588 负责综合判断，STM32 负责落地执行。

## 新手建议

建议按这个顺序看：

1. `Core/sensor_task.c`：先看数据怎么采；
2. `Core/uart_protocol.c`：再看怎么发给 RK3588；
3. `Core/alarm_task.c`：看报警动作怎么执行；
4. `config/freertos_config.h`：看 FreeRTOS 相关配置。
