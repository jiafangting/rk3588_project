/*
 * 文件名: freertos_app.c
 * 功能描述: 创建 STM32 侧 FreeRTOS 队列和任务。
 *
 * 数据流:
 * - vSensorTask 采集传感器数据，写入 gSensorQueue；
 * - uart_sensor_send_task 从 gSensorQueue 取数据，通过 UART 上报 RK3588；
 * - uart_receive_task 接收 RK3588 下发的报警命令，写入 gAlarmQueue；
 * - vAlarmTask 从 gAlarmQueue 取命令，控制蜂鸣器、LED、继电器。
 */

#include "freertos_app.h"

#include "alarm_task.h"
#include "freertos_config.h"
#include "sensor_task.h"
#include "uart_protocol.h"

QueueHandle_t gSensorQueue = NULL;
QueueHandle_t gAlarmQueue = NULL;

#define TASK_PRIORITY_SENSOR   1
#define TASK_PRIORITY_UART_TX  2
#define TASK_PRIORITY_UART_RX  3
#define TASK_PRIORITY_ALARM    4

int app_freertos_init(void)
{
    BaseType_t ok;

    gSensorQueue = xQueueCreate(SENSOR_QUEUE_LENGTH, sizeof(SensorData_t));
    if (gSensorQueue == NULL) {
        return -1;
    }

    gAlarmQueue = xQueueCreate(ALARM_QUEUE_LENGTH, sizeof(uint8_t));
    if (gAlarmQueue == NULL) {
        return -1;
    }

    ok = xTaskCreate(
        vSensorTask,
        "sensor",
        STACK_SIZE_SENSOR,
        NULL,
        TASK_PRIORITY_SENSOR,
        NULL
    );
    if (ok != pdPASS) {
        return -1;
    }

    ok = xTaskCreate(
        uart_sensor_send_task,
        "uart_tx",
        STACK_SIZE_UART,
        NULL,
        TASK_PRIORITY_UART_TX,
        NULL
    );
    if (ok != pdPASS) {
        return -1;
    }

    ok = xTaskCreate(
        uart_receive_task,
        "uart_rx",
        STACK_SIZE_UART,
        NULL,
        TASK_PRIORITY_UART_RX,
        NULL
    );
    if (ok != pdPASS) {
        return -1;
    }

    ok = xTaskCreate(
        vAlarmTask,
        "alarm",
        STACK_SIZE_ALARM,
        NULL,
        TASK_PRIORITY_ALARM,
        NULL
    );
    if (ok != pdPASS) {
        return -1;
    }

    return 0;
}
