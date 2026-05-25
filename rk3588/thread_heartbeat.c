#include "system_state.h"

#include <stdio.h>
#include <time.h>
#include <unistd.h>

/*
 * 线程 4：心跳监控线程。
 *
 * 这个线程相当于“健康检查员”。
 * 它不做业务，只检查别的线程有没有按时活着。
 *
 * 流程：
 * 1. 每 10 秒进入一次检查；
 * 2. 读取 `heartbeat[0..4]`；
 * 3. 如果某个线程超过超时时间没有更新，就打印警告；
 * 4. 自己也更新 `heartbeat[4]` 作为心跳记录；
 * 5. 继续下一轮。
 *
 * 重要参数：
 * - `timeout_sec = 30`：超过 30 秒没更新就报警告
 * - `sleep(10)`：每 10 秒检查一次
 *
 * 原理：
 * - 每个线程都把自己的“最近活跃时间”写进共享数组；
 * - 监控线程对比当前时间和这个时间差；
 * - 这样可以在不重启程序的情况下发现线程卡死。
 */
void *thread_heartbeat(void *arg)
{
    SystemState *state = (SystemState *)arg;

    if (!state) {
        return NULL;
    }

    while (g_running) {
        time_t now = time(NULL);
        const int timeout_sec = 30;

        pthread_mutex_lock(&state->lock);

        for (int i = 0; i < 5; ++i) {
            time_t hb = state->heartbeat[i];
            if (hb == 0) {
                continue;
            }

            if ((now - hb) > timeout_sec) {
                switch (i) {
                    case 0:
                        printf("[HEARTBEAT] 警告：传感器线程超过30秒无响应\n");
                        break;
                    case 1:
                        printf("[HEARTBEAT] 警告：视觉线程超过30秒无响应\n");
                        break;
                    case 2:
                        printf("[HEARTBEAT] 警告：决策线程超过30秒无响应\n");
                        break;
                    case 3:
                        printf("[HEARTBEAT] 警告：报警线程超过30秒无响应\n");
                        break;
                    case 4:
                        printf("[HEARTBEAT] 警告：心跳线程超过30秒无响应\n");
                        break;
                    default:
                        break;
                }
            }
        }

        state->heartbeat[4] = now;
        pthread_mutex_unlock(&state->lock);

        sleep(10);
    }

    printf("[HEARTBEAT] 线程退出\n");
    return NULL;
}
