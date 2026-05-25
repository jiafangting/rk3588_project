/*
 * 文件名: freertos_app.h
 * 功能描述: STM32 FreeRTOS 应用层初始化入口。
 *
 * 说明:
 * - 本文件不替代 CubeMX 生成的 freertos.c/main.c；
 * - 实际工程中，在 MX_FREERTOS_Init() 或 vTaskStartScheduler()
 *   之前调用 app_freertos_init()；
 * - 这里集中创建传感器队列、报警队列和业务任务。
 */

#ifndef FREERTOS_APP_H
#define FREERTOS_APP_H

#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"

#ifdef __cplusplus
extern "C" {
#endif

extern QueueHandle_t gSensorQueue;
extern QueueHandle_t gAlarmQueue;

int app_freertos_init(void);

#ifdef __cplusplus
}
#endif

#endif /* FREERTOS_APP_H */
