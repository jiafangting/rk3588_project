/*
 * 文件名: uart_protocol.c
 * 功能描述: STM32 与 RK3588 的串口通信协议实现。
 * 硬件依赖: USART1 / RK3588 串口。
 * 作者: Cursor
 */

#include "uart_protocol.h"
#include "alarm_task.h"
#include "freertos_config.h"
#include <stdio.h>
#include <string.h>

/* 外设句柄 */
extern UART_HandleTypeDef huart1;

/* 报警队列句柄 */
extern QueueHandle_t gAlarmQueue;

/*
 * @brief 计算校验和。
 * @param buf 待计算数据缓冲区。
 * @param len 数据长度。
 * @return 低 8 位校验和。
 */
uint8_t uart_calc_checksum(uint8_t *buf, uint16_t len)
{
    uint16_t sum = 0;
    if (!buf || len == 0) {
        return 0;
    }

    for (uint16_t i = 0; i < len; ++i) {
        sum += buf[i];
    }
    return (uint8_t)(sum & 0xFFU);
}

/*
 * @brief 打包并发送上行传感器帧。
 * @param data 传感器数据结构体指针。
 * @return 无返回值。
 */
void uart_send_sensor_frame(SensorData_t *data)
{
    if (!data) {
        return;
    }

    /*
     * 上行帧格式：
     * 0xAA | temp_env(float) | humidity(float) | temp_device(float) | current(float) | smoke(u8) | checksum(u8) | 0x55
     * 总长度 22 字节：1 + 4 + 4 + 4 + 4 + 1 + 1 + 1 = 20? 
     * 说明：这里按 C 结构逐项打包，实际串口帧长度建议固定按字节手动拼包。
     * 为避免结构体对齐导致差异，下面采用逐字节拼接方式。
     */
    uint8_t frame[UART_SENSOR_FRAME_LEN] = {0};
    uint8_t payload[1 + 4 + 4 + 4 + 4 + 1] = {0};
    uint16_t idx = 0;
    uint8_t checksum = 0;

    frame[0] = UART_SENSOR_FRAME_HEAD;

    memcpy(&payload[idx], &data->temperature_env, sizeof(float)); idx += 4;
    memcpy(&payload[idx], &data->humidity, sizeof(float)); idx += 4;
    memcpy(&payload[idx], &data->temperature_device, sizeof(float)); idx += 4;
    memcpy(&payload[idx], &data->current, sizeof(float)); idx += 4;
    payload[idx++] = data->smoke_level;

    memcpy(&frame[1], payload, idx);
    checksum = uart_calc_checksum(&frame[1], idx);
    frame[1 + idx] = checksum;
    frame[1 + idx + 1] = UART_SENSOR_FRAME_TAIL;

    /* 注意：这里发送长度按实际拼包长度计算，而不是死盯宏值，避免结构差异造成问题。 */
    if (HAL_UART_Transmit(&huart1, frame, 1 + idx + 2, 100) != HAL_OK) {
        printf("[UART] 上行传感器帧发送失败\n");
    }
}

/*
 * @brief 报警指令帧解析。
 * @param buf 接收到的 3 字节帧。
 * @param cmd_out 解析得到的指令输出。
 * @return 1=解析成功，0=失败。
 */
int uart_parse_alarm_cmd(uint8_t *buf, uint8_t *cmd_out)
{
    if (!buf || !cmd_out) {
        return 0;
    }

    if (buf[0] != UART_ALARM_FRAME_HEAD || buf[2] != UART_ALARM_FRAME_TAIL) {
        return 0;
    }

    if (buf[1] != UART_ALARM_CMD_ON && buf[1] != UART_ALARM_CMD_OFF) {
        return 0;
    }

    *cmd_out = buf[1];
    return 1;
}

/*
 * @brief FreeRTOS 串口接收任务。
 * @param pvParameters 任务参数，通常传入队列句柄。
 * @return 无返回值。
 */
void uart_receive_task(void *pvParameters)
{
    (void)pvParameters;

    uint8_t rxByte = 0;
    uint8_t frame[UART_ALARM_FRAME_LEN] = {0};
    uint8_t index = 0;
    uint8_t cmd = 0;

    printf("[UART] 串口接收任务启动\n");

    while (1) {
        if (HAL_UART_Receive(&huart1, &rxByte, 1, 10) == HAL_OK) {
            if (index == 0) {
                if (rxByte == UART_ALARM_FRAME_HEAD) {
                    frame[index++] = rxByte;
                }
            } else {
                frame[index++] = rxByte;
                if (index >= UART_ALARM_FRAME_LEN) {
                    if (uart_parse_alarm_cmd(frame, &cmd)) {
                        if (gAlarmQueue) {
                            xQueueSend(gAlarmQueue, &cmd, pdMS_TO_TICKS(10));
                        }
                    }
                    index = 0;
                }
            }
        }
    }
}
