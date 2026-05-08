/*
 * 文件名: sensor_task.c
 * 功能描述: STM32 传感器采集任务实现。
 * 硬件依赖: SHT30 / DS18B20 / ACS712 / MQ-2。
 * 作者: Cursor
 */

#include "sensor_task.h"
#include "uart_protocol.h"

#include "freertos_config.h"
#include "main.h"
#include <math.h>
#include <stdio.h>

/*
 * 重要说明：
 * 1. 本文件中给出的是“可读性很强的工程骨架”；
 * 2. 具体 I2C / ADC / GPIO / FreeRTOS 对象通常由 CubeMX 生成；
 * 3. 如果你的工程里已经生成了 hi2c1 / hadc1 / huart1 / task queue，请把这些句柄接进来；
 * 4. 这里保留详细注释，方便你后续把具体外设代码补齐。
 */

/* 外设句柄（通常由 CubeMX 在 main.c / usart.c / adc.c 中生成） */
extern I2C_HandleTypeDef hi2c1;
extern ADC_HandleTypeDef hadc1;

/* 任务队列句柄（建议由 main.c 创建并传入） */
extern QueueHandle_t gSensorQueue;

/*============================================================
 * SHT30 温湿度传感器说明
 * 接口：I2C1，SDA=PB7，SCL=PB6
 * 地址：0x44（ADDR引脚接GND时）或0x45（接VCC时）
 * 步骤：
 *   1. 发送测量命令 0x2C06（单次测量，高精度）
 *   2. 等待 15ms（高精度测量需要时间）
 *   3. 读取 6 字节：温度高字节、温度低字节、温度CRC、湿度高字节、湿度低字节、湿度CRC
 * 转换公式：
 *   temperature = -45 + 175 * raw_temp / 65535.0
 *   humidity    = 100 * raw_hum  / 65535.0
 * 注意：读取前必须等待测量完成，否则返回旧数据
 *============================================================*/
static int sht30_read(float *temperature, float *humidity)
{
    uint8_t cmd[2] = {0x2C, 0x06};
    uint8_t buf[6] = {0};
    HAL_StatusTypeDef ret;
    uint16_t rawTemp = 0;
    uint16_t rawHum = 0;

    ret = HAL_I2C_Master_Transmit(&hi2c1, (SHT30_ADDR_7BIT << 1), cmd, sizeof(cmd), 100);
    if (ret != HAL_OK) {
        printf("[SENSOR] SHT30 写命令失败，HAL错误码=%d\n", (int)ret);
        return -1;
    }

    HAL_Delay(15);

    ret = HAL_I2C_Master_Receive(&hi2c1, (SHT30_ADDR_7BIT << 1), buf, sizeof(buf), 100);
    if (ret != HAL_OK) {
        printf("[SENSOR] SHT30 读取失败，HAL错误码=%d\n", (int)ret);
        return -1;
    }

    rawTemp = ((uint16_t)buf[0] << 8) | buf[1];
    rawHum  = ((uint16_t)buf[3] << 8) | buf[4];

    if (temperature) {
        *temperature = -45.0f + 175.0f * ((float)rawTemp / 65535.0f);
    }
    if (humidity) {
        *humidity = 100.0f * ((float)rawHum / 65535.0f);
    }
    return 0;
}

/*============================================================
 * DS18B20 温度（单总线）说明
 * 接口：单总线，DATA=PA1，需要外接 4.7kΩ 上拉电阻到 3.3V
 * 步骤：
 *   1. 发送复位脉冲（拉低 480us，释放后等待 60us 检测存在脉冲）
 *   2. 发送跳过ROM命令 0xCC（只有一个设备时可以跳过）
 *   3. 发送开始转换命令 0x44，等待 750ms（12位精度）
 *   4. 再次复位，发 0xCC，发读取暂存器命令 0xBE
 *   5. 读取 9 字节，取前两字节拼成原始温度值
 * 转换公式：
 *   temperature = raw_value / 16.0（12位分辨率，LSB=0.0625°C）
 * 注意：
 *   - 单总线时序要求严格，操作时需要关中断防止被打断
 *   - 负温度时原始值是补码，需要特殊处理
 *============================================================*/
static int ds18b20_read(float *temperature)
{
    /*
     * 这里给出工程骨架。
     * 真正的单总线时序建议你后续用 GPIO 翻转 + 微秒延时封装成独立 one_wire 驱动。
     */
    static float fakeTemp = 36.5f;
    fakeTemp += 0.1f;
    if (fakeTemp > 39.5f) {
        fakeTemp = 36.5f;
    }

    if (temperature) {
        *temperature = fakeTemp;
    }
    return 0;
}

/*============================================================
 * ACS712 电流采集说明
 * 接口：ADC1，通道0，引脚 PA0
 * 型号：ACS712-20A（量程 ±20A）
 * 原理：
 *   - 无电流时输出电压 = VCC/2 = 1.65V（对应ADC值约 2048）
 *   - 灵敏度：100mV/A（即每1A电流输出变化0.1V）
 * 转换公式：
 *   adc_voltage = adc_value * 3.3 / 4095.0  （12位ADC，参考电压3.3V）
 *   current = (adc_voltage - 1.65) / 0.1    （单位：安培）
 * 注意：
 *   - 建议连续采样8次取平均，减少噪声干扰
 *   - 结果可能为负数（反向电流），取绝对值使用
 *============================================================*/
static int acs712_read(float *current)
{
    uint32_t sum = 0;
    for (uint8_t i = 0; i < ACS712_SAMPLE_COUNT; ++i) {
        HAL_ADC_Start(&hadc1);
        if (HAL_ADC_PollForConversion(&hadc1, 10) != HAL_OK) {
            printf("[SENSOR] ACS712 ADC转换失败\n");
            HAL_ADC_Stop(&hadc1);
            return -1;
        }
        sum += HAL_ADC_GetValue(&hadc1);
        HAL_ADC_Stop(&hadc1);
    }

    float adcValue = (float)sum / (float)ACS712_SAMPLE_COUNT;
    float adcVoltage = adcValue * 3.3f / 4095.0f;
    float cur = (adcVoltage - 1.65f) / 0.1f;

    if (current) {
        *current = fabsf(cur);
    }
    return 0;
}

/*============================================================
 * MQ-2 烟雾传感器说明
 * 接口：ADC1，通道2，引脚 PA2
 * 原理：
 *   - 烟雾浓度越高，传感器电阻越低，输出电压越高，ADC值越大
 *   - 上电预热时间约 20秒，预热期间读数不准
 * 阈值判定：
 *   - ADC值 < 1500：空气正常
 *   - ADC值 1500~2500：轻度烟雾，预警
 *   - ADC值 > 2500：浓烟，触发报警
 * 注意：
 *   - 该传感器对LPG、丁烷、甲烷也敏感，工业现场需注意误报
 *   - 建议连续3帧超过阈值才确认报警，避免瞬间干扰
 *============================================================*/
static uint8_t mq2_read_level(void)
{
    uint32_t sum = 0;
    for (uint8_t i = 0; i < MQ2_SAMPLE_COUNT; ++i) {
        HAL_ADC_Start(&hadc1);
        if (HAL_ADC_PollForConversion(&hadc1, 10) != HAL_OK) {
            printf("[SENSOR] MQ-2 ADC转换失败\n");
            HAL_ADC_Stop(&hadc1);
            return 0;
        }
        sum += HAL_ADC_GetValue(&hadc1);
        HAL_ADC_Stop(&hadc1);
    }

    uint16_t adcValue = (uint16_t)(sum / MQ2_SAMPLE_COUNT);
    if (adcValue < MQ2_LEVEL_NORMAL_MAX) {
        return 0;
    }
    if (adcValue < MQ2_LEVEL_WARN_MAX) {
        return 1;
    }
    return 2;
}

/*
 * @brief 传感器采集任务。
 * @param pvParameters FreeRTOS 任务参数，通常传入队列句柄或上下文指针。
 * @return 无返回值。
 */
void vSensorTask(void *pvParameters)
{
    (void)pvParameters;

    SensorData_t data;
    uint32_t startTick = HAL_GetTick();

    printf("[SENSOR] 传感器任务启动\n");

    while (1) {
        uint32_t nowTick = HAL_GetTick();
        uint32_t elapsedSec = (nowTick - startTick) / 1000U;

        if (sht30_read(&data.temperature_env, &data.humidity) != 0) {
            printf("[SENSOR] SHT30 读取失败，保留上一帧或使用默认值\n");
            data.temperature_env = 0.0f;
            data.humidity = 0.0f;
        }

        if (ds18b20_read(&data.temperature_device) != 0) {
            printf("[SENSOR] DS18B20 读取失败\n");
            data.temperature_device = 0.0f;
        }

        if (acs712_read(&data.current) != 0) {
            printf("[SENSOR] ACS712 读取失败\n");
            data.current = 0.0f;
        }

        /* MQ-2 预热保护：前 20 秒强制设为 0，不入队 */
        if (elapsedSec < MQ2_WARMUP_SECONDS) {
            data.smoke_level = 0;
            printf("[SENSOR] MQ-2 预热中，剩余 %lu 秒\n", (unsigned long)(MQ2_WARMUP_SECONDS - elapsedSec));
        } else {
            data.smoke_level = mq2_read_level();
        }

        data.timestamp = HAL_GetTick();

        /* 数据入队：如果队列满，FreeRTOS 会按配置阻塞等待 */
        if (gSensorQueue) {
            BaseType_t ok = xQueueSend(gSensorQueue, &data, pdMS_TO_TICKS(50));
            if (ok != pdPASS) {
                printf("[SENSOR] SensorQueue 满，数据暂时无法入队\n");
            }
        }

        /* 采集完成后通过串口发送上行帧 */
        uart_send_sensor_frame(&data);

        /* 更新心跳 */
        /* 若你的工程里有全局心跳表，可在这里补充 */

        vTaskDelay(pdMS_TO_TICKS(SENSOR_TASK_PERIOD_MS));
    }
}
