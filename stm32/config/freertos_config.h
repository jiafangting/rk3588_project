/* ============================================================
 * 文件名: freertos_config.h
 * 功能描述: FreeRTOS 关键参数配置。
 * 硬件依赖: STM32F103C8T6，主频 72MHz。
 * 作者: Cursor
 * ============================================================ */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

/* ============================================================
 * FreeRTOS 关键参数说明
 * 平台：STM32F103C8T6，主频 72MHz
 * ============================================================ */

/* 系统时钟节拍频率（Hz）
 * 说明：1000Hz 表示每 1ms 产生一次 Tick 中断
 * 影响：值越高定时精度越高，但中断开销越大
 * 推荐：嵌入式场景 1000Hz 是标准选择 */
#define configTICK_RATE_HZ    1000

/* 最大优先级数量
 * 说明：FreeRTOS 优先级从 0（最低）到 configMAX_PRIORITIES-1（最高）
 * 本项目使用 5 个优先级已足够：
 *   0 = 空闲任务（系统保留）
 *   1 = 传感器采集（低优先级，可以被打断）
 *   2 = 串口发送（中优先级）
 *   3 = 串口接收（高优先级，需要快速响应）
 *   4 = 报警执行（最高优先级，必须立即响应） */
#define configMAX_PRIORITIES  5

/* 任务栈大小（字，1字=4字节）
 * 说明：每个任务独立拥有一块栈空间
 * 传感器任务：128字=512字节，够用（局部变量少）
 * 串口任务：256字=1024字节，需要存帧缓冲
 * 报警任务：128字=512字节，逻辑简单 */
#define STACK_SIZE_SENSOR     128
#define STACK_SIZE_UART       256
#define STACK_SIZE_ALARM      128

/* 消息队列长度
 * 说明：队列满时发送方会阻塞等待
 * SensorQueue：存放传感器数据帧，8条够用（500ms采集一次）
 * AlarmQueue：存放报警指令，4条足够 */
#define SENSOR_QUEUE_LENGTH   8
#define ALARM_QUEUE_LENGTH    4

#endif /* FREERTOS_CONFIG_H */
