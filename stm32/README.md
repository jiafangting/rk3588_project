# STM32 下位机模块

## 快速上手

### 开发环境
- STM32CubeIDE 或 Keil MDK
- STM32CubeMX（用于生成初始化代码）

### 编译步骤
1. 用 CubeMX 新建 STM32F103C8T6 工程
2. 使能：I2C1 / ADC1 / USART1 / FreeRTOS
3. 把 `Core/` 和 `config/` 下的文件加入工程
4. 编译烧录

### 串口参数
波特率：115200，8N1，TX=PA9，RX=PA10

### 注意事项
- ACS712 和 MQ-2 需要 5V 供电
- DS18B20 DATA 线必须接 4.7kΩ 上拉电阻
- STM32 与 RK3588 串口必须共地
- MQ-2 上电后预热 20 秒再采集
- 串口帧建议逐字节拼包，不要直接发送结构体内存
