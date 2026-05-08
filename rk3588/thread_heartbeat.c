#include "system_state.h"

#include <stdio.h>
#include <time.h>
#include <unistd.h>

/*
 * 线程 4：心跳监控线程。
 *
 * 作用：每 10 秒检查一次所有线程最近一次心跳时间。
 * 如果超过 30 秒没更新，就打印警告。
 *
 * 注意：这里只做监控，不自动重启，避免把问题隐藏掉。
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
