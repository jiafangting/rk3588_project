/*
 * 文件名: uart_protocol.h
 * 功能描述: STM32 与 RK3588 的串口通信协议定义。
 * 硬件依赖: USART1 / RK3588 串口。
 * 作者: Cursor
 */

#ifndef UART_PROTOCOL_H
#define UART_PROTOCOL_H

#include "stm32f1xx_hal.h"
#include "sensor_task.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
}
#endif

/* ============================================================
 * 串口通信帧格式说明
 * 串口参数：USART1，波特率115200，8N1，TX=PA9，RX=PA10
 *
 * 上行帧（STM32 → RK3588，传感器数据）：
 * | 帧头  | 环境温 | 环境湿 | 设备温 | 电流  | 烟雾 | 校验和 | 帧尾  |
 * | 0xAA | float | float | float | float | u8  |  u8  | 0x55 |
 * 总长度：22字节
 *
 * 下行帧（RK3588 → STM32，报警指令）：
 * | 帧头  | 指令  | 帧尾  |
 * | 0xBB |  u8  | 0x55 |
 * 指令字节：0x01=开启报警  0x00=关闭报警
 * 总长度：3字节
 *
 * 校验和计算：帧头之后、帧尾之前所有字节相加，取低8位
 * ============================================================ */

#define UART_SENSOR_FRAME_HEAD      0xAAU
#define UART_SENSOR_FRAME_TAIL      0x55U
#define UART_ALARM_FRAME_HEAD       0xBBU
#define UART_ALARM_FRAME_TAIL       0x55U
#define UART_ALARM_CMD_ON           0x01U
#define UART_ALARM_CMD_OFF          0x00U
#define UART_SENSOR_FRAME_LEN       22U
#define UART_ALARM_FRAME_LEN        3U
#define UART_RX_BUFFER_SIZE         64U

/*
 * @brief 计算校验和。
 * @param buf 待计算数据缓冲区。
 * @param len 数据长度。
 * @return 低 8 位校验和。
 */
uint8_t uart_calc_checksum(uint8_t *buf, uint16_t len);

/*
 * @brief 打包并发送上行传感器帧。
 * @param data 传感器数据结构体指针。
 * @return 无返回值。
 */
void uart_send_sensor_frame(SensorData_t *data);

/*
 * @brief 报警指令帧解析。
 * @param buf 接收到的 3 字节帧。
 * @param cmd_out 解析得到的指令输出。
 * @return 1=解析成功，0=失败。
 */
int uart_parse_alarm_cmd(uint8_t *buf, uint8_t *cmd_out);

/*
 * @brief FreeRTOS 串口接收任务。
 * @param pvParameters 任务参数，通常传入队列句柄。
 * @return 无返回值。
 */
void uart_receive_task(void *pvParameters);

#ifdef __cplusplus
}
#endif

#endif /* UART_PROTOCOL_H */
