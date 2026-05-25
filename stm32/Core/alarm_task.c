/*
 * 文件名: alarm_task.c
 * 功能描述: STM32 报警执行任务实现。
 * 硬件依赖: 蜂鸣器 / LED / 继电器。
 * 作者: Cursor
 */

#include "alarm_task.h"
#include "FreeRTOS.h"
#include "freertos_config.h"
#include "queue.h"
#include "task.h"
#include <stdio.h>

/* 报警队列句柄 */
extern QueueHandle_t gAlarmQueue;

/* 报警计数器 */
static uint32_t gAlarmCount = 0;

/*
 * @brief 打开报警硬件。
 * @return 无返回值。
 */
void alarm_hw_enable(void)
{
    HAL_GPIO_WritePin(ALARM_BUZZER_GPIO_Port, ALARM_BUZZER_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(ALARM_LED_GPIO_Port, ALARM_LED_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(ALARM_RELAY_GPIO_Port, ALARM_RELAY_Pin, GPIO_PIN_SET);
}

/*
 * @brief 关闭报警硬件。
 * @return 无返回值。
 */
void alarm_hw_disable(void)
{
    HAL_GPIO_WritePin(ALARM_BUZZER_GPIO_Port, ALARM_BUZZER_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(ALARM_LED_GPIO_Port, ALARM_LED_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(ALARM_RELAY_GPIO_Port, ALARM_RELAY_Pin, GPIO_PIN_RESET);
}

/*
 * @brief 报警执行任务入口。
 * @param pvParameters FreeRTOS 任务参数，通常传入队列句柄。
 * @return 无返回值。
 */
void vAlarmTask(void *pvParameters)
{
    (void)pvParameters;
    uint8_t alarmCmd = ALARM_CMD_DISABLE;

    printf("[ALARM] 报警任务启动\n");
    alarm_hw_disable();

    while (1) {
        if (gAlarmQueue && xQueueReceive(gAlarmQueue, &alarmCmd, portMAX_DELAY) == pdPASS) {
            if (alarmCmd == ALARM_CMD_ENABLE) {
                alarm_hw_enable();
                gAlarmCount++;
                if (gAlarmCount > ALARM_COUNT_MAX) {
                    gAlarmCount = 0;
                }
                printf("[ALARM] 报警开启，当前累计次数：%lu\n", (unsigned long)gAlarmCount);
            } else {
                alarm_hw_disable();
                printf("[ALARM] 报警关闭\n");
            }
        }
    }
}
