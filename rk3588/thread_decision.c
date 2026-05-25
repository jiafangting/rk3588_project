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
extern pthread_mutex_t g_threshold_lock;

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

static void append_reason(char *reason, size_t reason_size, const char *item)
{
    size_t used;

    if (!reason || !item || reason_size == 0 || item[0] == '\0') {
        return;
    }

    used = strlen(reason);
    if (used == 0) {
        snprintf(reason, reason_size, "%s", item);
        return;
    }

    if (used + 1 >= reason_size) {
        return;
    }

    snprintf(reason + used, reason_size - used, "；%s", item);
}

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

    /*
     * 这一线程就是“报警怎么判断”的核心。
     *
     * 你可以把它理解为：
     * 1. 先把传感器和视觉线程更新好的状态读出来；
     * 2. 再根据阈值做融合判断；
     * 3. 最后决定要不要触发报警。
     */

    if (!state) {
        return NULL;
    }

    while (g_running) {
        float temperature = 0.0f;
        float humidity = 0.0f;
        float temp_device = 0.0f;
        float current = 0.0f;
        uint8_t smoke = 0;
        ThresholdConfig threshold;
        char vision_status[16] = {0};
        int zone_hit = 0;
        char alarm_type[32] = {0};
        char alarm_reason[128] = {0};
        int prev_alarm_active = 0;

        pthread_mutex_lock(&state->lock);
        temperature = state->temperature;
        humidity = state->humidity;
        temp_device = state->temp_device;
        current = state->current;
        smoke = state->smoke;
        snprintf(vision_status, sizeof(vision_status), "%s", state->vision_status);
        zone_hit = state->zone_hit;
        snprintf(alarm_type, sizeof(alarm_type), "%s", state->alarm_type);
        snprintf(alarm_reason, sizeof(alarm_reason), "%s", state->alarm_reason);
        prev_alarm_active = state->alarm_active;
        pthread_mutex_unlock(&state->lock);

        pthread_mutex_lock(&g_threshold_lock);
        threshold = g_threshold;
        pthread_mutex_unlock(&g_threshold_lock);

        alarm_now = 0;
        reason[0] = '\0';

        /*
         * 传感器报警判断。
         *
         * 传感器和视觉原因并列收集，最后统一决定是否报警。
         * 这样多个异常同时发生时，报警原因不会互相覆盖。
         *
         * 重要参数来自 config.json：
         * - temp_max
         * - humidity_min
         * - humidity_max
         * - current_max
         * - temp_device_max
         * - smoke_alarm
         */
        if (temperature > threshold.temp_max) {
            char item[64];
            snprintf(item, sizeof(item), "环境温度过高 %.1f°C", temperature);
            append_reason(reason, sizeof(reason), item);
        }
        if (humidity < threshold.humidity_min) {
            char item[64];
            snprintf(item, sizeof(item), "湿度过低 %.1f%%", humidity);
            append_reason(reason, sizeof(reason), item);
        }
        if (humidity > threshold.humidity_max) {
            char item[64];
            snprintf(item, sizeof(item), "湿度过高 %.1f%%", humidity);
            append_reason(reason, sizeof(reason), item);
        }
        if (current > threshold.current_max) {
            char item[64];
            snprintf(item, sizeof(item), "电流过载 %.2fA", current);
            append_reason(reason, sizeof(reason), item);
        }
        if (temp_device > threshold.temp_device_max) {
            char item[64];
            snprintf(item, sizeof(item), "设备温度过高 %.1f°C", temp_device);
            append_reason(reason, sizeof(reason), item);
        }
        if (threshold.smoke_alarm && smoke != 0) {
            append_reason(reason, sizeof(reason), "检测到烟雾");
        }

        /*
         * 视觉报警判断。
         *
         * 这一段表示：除了传感器，视觉模块也能单独决定报警。
         * 比如有人进入禁区，或者视觉模块直接判定为 ALARM，
         * 那么决策线程也会把它当作报警依据。
         */
        if (strcmp(vision_status, "ALARM") == 0) {
            if (alarm_reason[0] != '\0') {
                append_reason(reason, sizeof(reason), alarm_reason);
            } else if (alarm_type[0] != '\0') {
                append_reason(reason, sizeof(reason), alarm_type);
            } else if (zone_hit) {
                append_reason(reason, sizeof(reason), "人员进入禁区");
            } else {
                append_reason(reason, sizeof(reason), "视觉检测到报警");
            }
        }

        alarm_now = reason[0] != '\0';

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
