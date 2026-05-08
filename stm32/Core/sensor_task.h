/*
 * 文件名: sensor_task.h
 * 功能描述: STM32 传感器采集任务相关定义与接口。
 * 硬件依赖: SHT30 / DS18B20 / ACS712 / MQ-2。
 * 作者: Cursor
 */

#ifndef SENSOR_TASK_H
#define SENSOR_TASK_H

#include "stm32f1xx_hal.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================
 * 关键参数说明
 * 平台：STM32F103C8T6，主频 72MHz
 * ============================================================ */

/* 传感器采集周期（ms）
 * 说明：500ms 采集一次，约等于 2Hz。
 * 原因：
 *   - 传感器变化不需要过高频率；
 *   - 给串口和报警任务留出处理时间；
 *   - 降低 MCU 负载。 */
#define SENSOR_TASK_PERIOD_MS      500U

/* MQ-2 预热时间（秒）
 * 说明：MQ-2 上电后需要预热，预热期间数值不可靠。
 * 原因：
 *   - 气敏电阻在刚上电时不稳定；
 *   - 预热后数据更接近实际。 */
#define MQ2_WARMUP_SECONDS         20U

/* SHT30 I2C 地址（7位地址） */
#define SHT30_ADDR_7BIT            0x44U

/* SHT30 单次高精度测量命令 */
#define SHT30_CMD_MEASURE_HI       0x2C06U

/* DS18B20 读暂存器命令 */
#define DS18B20_CMD_READ_SCRATCH   0xBEU

/* DS18B20 跳过ROM命令 */
#define DS18B20_CMD_SKIP_ROM       0xCCU

/* DS18B20 启动温度转换命令 */
#define DS18B20_CMD_CONVERT_T      0x44U

/* DS18B20 默认转换等待时间（ms，12位分辨率） */
#define DS18B20_CONVERT_DELAY_MS   750U

/* 采样平均次数 */
#define ACS712_SAMPLE_COUNT        8U
#define MQ2_SAMPLE_COUNT           8U

/* MQ-2 阈值（ADC原始值） */
#define MQ2_LEVEL_NORMAL_MAX       1500U
#define MQ2_LEVEL_WARN_MAX         2500U

/* 传感器采集结构体。
 *
 * @brief 统一封装一次采集结果，供串口发送和队列传递使用。
 */
typedef struct {
    float    temperature_env;    /* 环境温度（SHT30），单位：°C */
    float    humidity;           /* 环境湿度（SHT30），单位：% */
    float    temperature_device; /* 设备温度（DS18B20），单位：°C */
    float    current;            /* 电流（ACS712），单位：A */
    uint8_t  smoke_level;        /* 烟雾等级：0=正常 1=预警 2=报警 */
    uint32_t timestamp;          /* 采集时刻的 HAL_GetTick() 值，单位ms */
} SensorData_t;

/*
 * @brief 传感器采集任务入口。
 * @param pvParameters FreeRTOS 任务参数，通常传入队列句柄或上下文指针。
 * @return 无返回值。
 */
void vSensorTask(void *pvParameters);

#ifdef __cplusplus
}
#endif

#endif /* SENSOR_TASK_H */
