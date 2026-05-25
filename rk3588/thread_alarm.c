#include "system_state.h"

#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/*
 * 线程 3：报警执行线程。
 *
 * 这个线程负责“真正执行报警动作”。
 * 它不做判断，判断结果来自 `thread_decision.c`。
 * 它只关心：
 * - 现在是不是报警；
 * - 报警有没有从 0 变成 1；
 * - 报警有没有从 1 变回 0。
 * - 报警持续期间，报警原因有没有变化。
 *
 * 流程：
 * 1. 读取共享状态中的 `alarm_active`；
 * 2. 如果是新报警，给 STM32 发“开启报警”命令；
 * 3. 写报警日志；
 * 4. 更新报警次数；
 * 5. 如果报警解除，给 STM32 发“关闭报警”命令；
 * 6. 如果报警持续但原因变化，补写一条原因更新日志；
 * 7. 更新心跳；
 * 8. 休眠一小段时间后继续轮询。
 *
 * 重要参数：
 * - `msg.level = 2`：严重报警
 * - `msg.level = 0`：报警解除
 * - `usleep(200 * 1000)`：200ms 轮询一次，保证响应快
 */

/* 报警消息结构，和决策线程保持一致。 */
typedef struct {
    int  level;
    char reason[128];
    time_t timestamp;
} AlarmMessage;

static void append_alarm_csv(const AlarmMessage *msg)
{
    FILE *fp = fopen("alarm_log.csv", "a");
    if (!fp) {
        printf("[ALARM] 无法打开 alarm_log.csv\n");
        return;
    }

    /*
     * CSV 字段：时间戳、级别、原因
     * 这里先写最基础的三列，方便后面 Excel 直接打开查看。
     */
    fprintf(fp, "%ld,%d,%s\n", (long)msg->timestamp, msg->level, msg->reason);
    fclose(fp);
}

static void send_alarm_cmd_to_stm32(int enable)
{
    /*
     * 串口指令占位：
     * - 0xBB 0x01 0x55：打开报警
     * - 0xBB 0x00 0x55：关闭报警
     *
     * 当前硬件未接入时，只打印日志，保证程序能跑通。
     */
    if (enable) {
        printf("[ALARM] 发送 STM32 指令：BB 01 55 (开启报警)\n");
    } else {
        printf("[ALARM] 发送 STM32 指令：BB 00 55 (关闭报警)\n");
    }
}

/*
 * 线程 3：报警执行线程。
 *
 * 当前先采用轮询方式查看 g_state.alarm_active：
 * - active=1 时执行报警动作；
 * - active=0 时关闭报警动作；
 *
 * 后续如果接入 POSIX 消息队列，可以直接把这段轮询改成阻塞接收。
 */
void *thread_alarm(void *arg)
{
    SystemState *state = (SystemState *)arg;
    int last_alarm_active = 0;
    char last_logged_reason[128] = {0};

    if (!state) {
        return NULL;
    }

    while (g_running) {
        int alarm_active = 0;
        char reason[128] = {0};
        time_t alarm_time = 0;
        int alarm_count_today = 0;

        pthread_mutex_lock(&state->lock);
        alarm_active = state->alarm_active;
        snprintf(reason, sizeof(reason), "%s", state->last_alarm_reason);
        alarm_time = state->last_alarm_time;
        alarm_count_today = state->alarm_count_today;
        pthread_mutex_unlock(&state->lock);

        if (alarm_active && !last_alarm_active) {
            AlarmMessage msg;
            memset(&msg, 0, sizeof(msg));
            msg.level = 2;
            snprintf(msg.reason, sizeof(msg.reason), "%s", reason[0] ? reason : "报警触发");
            msg.timestamp = alarm_time ? alarm_time : time(NULL);

            send_alarm_cmd_to_stm32(1);
            append_alarm_csv(&msg);

            pthread_mutex_lock(&state->lock);
            state->alarm_count_today = alarm_count_today + 1;
            pthread_mutex_unlock(&state->lock);

            printf("[ALARM] %ld | %s\n", (long)msg.timestamp, msg.reason);
            snprintf(last_logged_reason, sizeof(last_logged_reason), "%s", reason);
        }

        if (alarm_active && last_alarm_active &&
            reason[0] != '\0' &&
            strcmp(reason, last_logged_reason) != 0) {
            AlarmMessage msg;
            memset(&msg, 0, sizeof(msg));
            msg.level = 1;
            snprintf(msg.reason, sizeof(msg.reason), "报警原因更新：%s", reason);
            msg.timestamp = time(NULL);

            append_alarm_csv(&msg);
            snprintf(last_logged_reason, sizeof(last_logged_reason), "%s", reason);
            printf("[ALARM] %ld | %s\n", (long)msg.timestamp, msg.reason);
        }

        if (!alarm_active && last_alarm_active) {
            AlarmMessage msg;
            memset(&msg, 0, sizeof(msg));
            msg.level = 0;
            snprintf(msg.reason, sizeof(msg.reason), "报警解除");
            msg.timestamp = time(NULL);

            send_alarm_cmd_to_stm32(0);
            append_alarm_csv(&msg);
            printf("[ALARM] %ld | %s\n", (long)msg.timestamp, msg.reason);
            last_logged_reason[0] = '\0';
        }

        last_alarm_active = alarm_active;

        pthread_mutex_lock(&state->lock);
        state->heartbeat[3] = time(NULL);
        pthread_mutex_unlock(&state->lock);

        usleep(200 * 1000);
    }

    printf("[ALARM] 线程退出\n");
    return NULL;
}
