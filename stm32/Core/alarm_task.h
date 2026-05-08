/*
 * 文件名: alarm_task.h
 * 功能描述: STM32 报警执行任务相关定义与接口。
 * 硬件依赖: 蜂鸣器 / LED / 继电器。
 * 作者: Cursor
 */

#ifndef ALARM_TASK_H
#define ALARM_TASK_H

#include "stm32f1xx_hal.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
}
#endif

/* 报警硬件引脚定义
 * 蜂鸣器：PB0，有源蜂鸣器，高电平触发
 * 红色LED：PB1，高电平亮
 * 继电器：PB2，高电平吸合（常开接法：吸合=断开被控设备）
 * 注意：继电器线圈有反电动势，必须加续流二极管保护STM32引脚 */
#define ALARM_BUZZER_GPIO_Port      GPIOB
#define ALARM_BUZZER_Pin            GPIO_PIN_0
#define ALARM_LED_GPIO_Port         GPIOB
#define ALARM_LED_Pin               GPIO_PIN_1
#define ALARM_RELAY_GPIO_Port       GPIOB
#define ALARM_RELAY_Pin             GPIO_PIN_2

/* 报警状态 */
#define ALARM_CMD_DISABLE           0x00U
#define ALARM_CMD_ENABLE            0x01U

/* 报警计数上限，防止溢出 */
#define ALARM_COUNT_MAX             0x7FFFFFFFU

/*
 * @brief 报警执行任务入口。
 * @param pvParameters FreeRTOS 任务参数，通常传入队列句柄。
 * @return 无返回值。
 */
void vAlarmTask(void *pvParameters);

/*
 * @brief 控制报警硬件打开。
 * @return 无返回值。
 */
void alarm_hw_enable(void);

/*
 * @brief 控制报警硬件关闭。
 * @return 无返回值。
 */
void alarm_hw_disable(void);

#ifdef __cplusplus
}
#endif

#endif /* ALARM_TASK_H */
