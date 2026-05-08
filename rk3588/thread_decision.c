#include "system_state.h"
#include "threshold_config.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/*
 * 来自 main.c 的全局阈值配置。
 *
 * 这里直接引用，避免每个线程再重复加载配置文件。
 */
extern ThresholdConfig g_threshold;

/*
 * 来自 main.c 的全局消息队列句柄占位。
 *
 * 当前版本先保留接口，后续你接入 mq_open 后，
 * 这里就可以直接改成真正的 mqd_t。
 */
extern void *g_alarm_queue;

/*
 * 报警消息结构。
 *
 * 说明：
 * - level = 1：警告
 * - level = 2：严重
 * - level = 0：解除报警
 */
typedef struct {
    int  level;
    char reason[128];
    time_t timestamp;
} AlarmMessage;

/*
 * 线程 2：决策融合线程。
 *
 * 作用：
 * - 每 500ms 读取一次系统状态；
 * - 根据传感器和视觉结果做融合判断；
 * - 如果触发报警，就写入消息队列；
 * - 报警解除时也发 level=0 通知。
 */
void *thread_decision(void *arg)
{
    SystemState *state = (SystemState *)arg;
    int alarm_now = 0;
    char reason[128] = {0};

    if (!state) {
        return NULL;
    }

    while (g_running) {
        float temperature = 0.0f;
        float humidity = 0.0f;
        float temp_device = 0.0f;
        float current = 0.0f;
        uint8_t smoke = 0;
        char vision_status[16] = {0};
        int person_count = 0;
        int zone_hit = 0;
        char alarm_type[32] = {0};
        int prev_alarm_active = 0;

        pthread_mutex_lock(&state->lock);
        temperature = state->temperature;
        humidity = state->humidity;
        temp_device = state->temp_device;
        current = state->current;
        smoke = state->smoke;
        snprintf(vision_status, sizeof(vision_status), "%s", state->vision_status);
        person_count = state->person_count;
        zone_hit = state->zone_hit;
        snprintf(alarm_type, sizeof(alarm_type), "%s", state->alarm_type);
        prev_alarm_active = state->alarm_active;
        pthread_mutex_unlock(&state->lock);

        alarm_now = 0;
        reason[0] = '\0';

        /*
         * 传感器报警判断。
         *
         * 重要参数来自 config.json：
         * - temp_max
         * - humidity_min
         * - humidity_max
         * - current_max
         * - temp_device_max
         * - smoke_alarm
         */
        if (temperature > g_threshold.temp_max) {
            alarm_now = 1;
            snprintf(reason, sizeof(reason), "环境温度过高 %.1f°C", temperature);
        } else if (humidity < g_threshold.humidity_min) {
            alarm_now = 1;
            snprintf(reason, sizeof(reason), "湿度过低 %.1f%%", humidity);
        } else if (humidity > g_threshold.humidity_max) {
            alarm_now = 1;
            snprintf(reason, sizeof(reason), "湿度过高 %.1f%%", humidity);
        } else if (current > g_threshold.current_max) {
            alarm_now = 1;
            snprintf(reason, sizeof(reason), "电流过载 %.2fA", current);
        } else if (temp_device > g_threshold.temp_device_max) {
            alarm_now = 1;
            snprintf(reason, sizeof(reason), "设备温度过高 %.1f°C", temp_device);
        } else if (g_threshold.smoke_alarm && smoke == 1) {
            alarm_now = 1;
            snprintf(reason, sizeof(reason), "检测到烟雾");
        }

        /*
         * 视觉报警判断。
         *
         * 说明：视觉模块如果处于 ALARM，并且命中禁区或报警类别，
         * 那就直接参与融合报警。
         */
        if (!alarm_now) {
            if (strcmp(vision_status, "ALARM") == 0 && zone_hit) {
                alarm_now = 1;
                snprintf(reason, sizeof(reason), "人员进入禁区");
            } else if (strcmp(vision_status, "ALARM") == 0 && alarm_type[0] != '\0') {
                alarm_now = 1;
                snprintf(reason, sizeof(reason), "%s", alarm_type);
            }
        }

        /*
         * 报警解除判断。
         *
         * 如果上轮是报警，这轮变成正常，则发一条 level=0 消息，
         * 让报警线程关闭蜂鸣器 / LED。
         */
        if (!alarm_now && prev_alarm_active) {
            AlarmMessage msg;
            memset(&msg, 0, sizeof(msg));
            msg.level = 0;
            snprintf(msg.reason, sizeof(msg.reason), "报警解除");
            msg.timestamp = time(NULL);

            /*
             * 当前先保留消息发送接口。
             * 如果你后面把 g_alarm_queue 改成真正的 mqd_t，
             * 这里就可以直接 mq_send。
             */
            printf("[DECISION] 报警解除，准备通知报警线程关闭硬件报警\n");
        }

        pthread_mutex_lock(&state->lock);
        state->alarm_active = alarm_now;
        if (alarm_now) {
            snprintf(state->last_alarm_reason, sizeof(state->last_alarm_reason), "%s", reason);
            state->last_alarm_time = time(NULL);
        }
        pthread_mutex_unlock(&state->lock);

        if (alarm_now) {
            printf("[DECISION] 报警触发：%s\n", reason);
        }

        pthread_mutex_lock(&state->lock);
        state->heartbeat[2] = time(NULL);
        pthread_mutex_unlock(&state->lock);

        usleep(500 * 1000);
    }

    printf("[DECISION] 线程退出\n");
    return NULL;
}
