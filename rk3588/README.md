# rk3588 C 主进程

这是离线工业巡检系统的 C 语言主进程示例工程。

## 结构说明

- `main.c`：主进程入口
- `thread_sensor.c`：串口传感器线程（支持模拟模式）
- `thread_vision.c`：视觉状态查询线程
- `thread_decision.c`：决策融合线程
- `thread_alarm.c`：报警执行线程
- `thread_heartbeat.c`：心跳监控线程
- `threshold_config.c/.h`：阈值配置模块
- `system_state.h`：系统状态结构体
- `config.json`：阈值配置示例
- `alarm_log.csv`：报警日志示例
- `Makefile`：编译脚本

## 编译

```bash
make
```

生成可执行文件：`inspection`

## 运行

```bash
./inspection
```

## 说明

- 串口未接入时，传感器线程会自动切换模拟模式。
- 视觉模块默认通过 Unix Socket `/tmp/vision.sock` 查询状态。
- 目前报警动作部分已预留 STM32 串口指令接口，后续可以直接接硬件。
