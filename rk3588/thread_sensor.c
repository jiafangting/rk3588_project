#include "system_state.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/*
 * 线程 0：传感器线程。
 *
 * 这个线程负责“采集环境数据”，它是 RK3588 端数据流的源头之一。
 * 真实硬件接入后，它会从 STM32 串口读取温度、湿度、电流、烟雾等信息。
 * 现在为了能先跑通项目，它先使用模拟数据。
 *
 * 流程：
 * 1. 尝试进入传感器采集循环；
 * 2. 如果当前是模拟模式，就随机生成一组传感器值；
 * 3. 将数据写入共享状态 `g_state`；
 * 4. 更新心跳 `heartbeat[0]`；
 * 5. 打印一行日志，方便你观察线程是否在正常运行；
 * 6. 睡眠 1 秒后继续下一轮。
 *
 * 重要参数：
 * - temperature：环境温度，单位 °C
 * - humidity：环境湿度，单位 %
 * - temp_device：设备温度，单位 °C
 * - current：工作电流，单位 A
 * - smoke：烟雾标志位，1 表示检测到烟雾
 *
 * 原理：
 * - 线程一直循环采集数据；
 * - 每次采集后用 mutex 保护共享状态写入；
 * - 其他线程读取时也会加锁，避免读到半更新的数据。
 */
void *thread_sensor(void *arg)
{
    SystemState *state = (SystemState *)arg;
    int use_simulation = 1;

    if (!state) {
        return NULL;
    }

    /*
     * 说明：当前先用模拟模式占位。
     * 以后你接入 /dev/ttyS3 时，可以在这里尝试打开串口，
     * 打开失败再回到模拟模式。
     */
    printf("[SENSOR] 串口不可用，使用模拟传感器数据\n");

    while (g_running) {
        if (use_simulation) {
            /*
             * 模拟一组传感器数据。
             *
             * 重要参数说明：
             * - temperature : 环境温度
             * - humidity    : 环境湿度
             * - temp_device : 设备温度
             * - current     : 当前电流
             * - smoke       : 烟雾标志位，1 表示检测到烟雾
             */
            float temperature = 25.0f + (float)(rand() % 100) / 10.0f;
            float humidity = 50.0f + (float)(rand() % 200) / 10.0f;
            float temp_device = 40.0f + (float)(rand() % 50) / 10.0f;
            float current = 3.0f + (float)(rand() % 20) / 10.0f;
            uint8_t smoke = (rand() % 20 == 0) ? 1 : 0;

            pthread_mutex_lock(&state->lock);
            state->temperature = temperature;
            state->humidity = humidity;
            state->temp_device = temp_device;
            state->current = current;
            state->smoke = smoke;
            state->heartbeat[0] = time(NULL);
            pthread_mutex_unlock(&state->lock);

            printf("[SENSOR] T=%.1fC H=%.1f%% Device=%.1fC I=%.2fA Smoke=%u\n",
                   temperature, humidity, temp_device, current, smoke);
            sleep(1);
            continue;
        }

        /*
         * 这里预留真实串口读取逻辑。
         * 由于当前硬件尚未到货，先不强行实现，避免影响整体编译。
         * 后续接入时建议按以下流程：
         * 1. 打开 /dev/ttyS3；
         * 2. 逐字节找 0xAA 帧头；
         * 3. 收满一帧后校验；
         * 4. 校验成功才更新 state；
         * 5. 更新 heartbeat[0]。
         */
        sleep(1);
    }

    printf("[SENSOR] 线程退出\n");
    return NULL;
}
