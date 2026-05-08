#include "system_state.h"
#include "threshold_config.h"

#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/*
 * 线程入口声明。
 *
 * 每个线程单独放到独立的 .c 文件里，方便后面维护。
 */
void *thread_sensor(void *arg);
void *thread_vision(void *arg);
void *thread_decision(void *arg);
void *thread_alarm(void *arg);
void *thread_heartbeat(void *arg);

/*
 * 全局运行开关。
 * 信号处理函数把它置 0，所有线程看到后自行退出。
 */
volatile int g_running = 1;

/*
 * 全局状态实例。
 * 所有线程都通过这一个结构体交换数据。
 */
SystemState g_state;

/*
 * 阈值配置。
 * 由 config.json 读取，读取失败时自动使用默认值。
 */
ThresholdConfig g_threshold;

/*
 * 外设资源句柄。
 * 这里先用 void* 占位，避免某些平台没装串口库时直接编译失败。
 * 如果后面你接入真正串口模块，可把它改成 int fd 或 struct serial*。
 */
void *g_sensor_port = NULL;
void *g_alarm_port = NULL;
void *g_alarm_queue = NULL;

/*
 * 初始化系统状态。
 *
 * 说明：
 * 1. 把数值清零；
 * 2. 把状态字符串设成 UNKNOWN；
 * 3. 初始化互斥锁。
 */
static void init_system_state(SystemState *state)
{
    if (!state) {
        return;
    }

    memset(state, 0, sizeof(*state));
    snprintf(state->vision_status, sizeof(state->vision_status), "UNKNOWN");
    snprintf(state->alarm_type, sizeof(state->alarm_type), "");
    snprintf(state->last_alarm_reason, sizeof(state->last_alarm_reason), "");
    pthread_mutex_init(&state->lock, NULL);
}

/*
 * 信号处理函数。
 *
 * 收到 Ctrl+C 或系统终止信号时：
 * 1. 关闭全局运行开关；
 * 2. 让各线程自然退出；
 * 3. 主线程再负责收尾。
 */
static void handle_signal(int sig)
{
    (void)sig;
    g_running = 0;
    printf("[MAIN] 收到退出信号，准备关闭系统...\n");
}

/*
 * 主函数。
 *
 * 启动流程：
 * 1. 初始化状态；
 * 2. 加载 config.json；
 * 3. 注册信号；
 * 4. 启动 5 个线程；
 * 5. 等待线程退出；
 * 6. 关闭资源并打印正常退出信息。
 */
int main(void)
{
    pthread_t tid_sensor;
    pthread_t tid_vision;
    pthread_t tid_decision;
    pthread_t tid_alarm;
    pthread_t tid_heartbeat;

    init_system_state(&g_state);

    if (load_threshold("config.json", &g_threshold) != 0) {
        printf("[MAIN] config.json 读取失败，已使用默认阈值\n");
    }

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    srand((unsigned int)time(NULL));

    /*
     * 启动各业务线程。
     * 这里把 g_state 作为共享上下文传给每个线程。
     */
    if (pthread_create(&tid_sensor, NULL, thread_sensor, &g_state) != 0) {
        printf("[MAIN] 启动传感器线程失败\n");
        return 1;
    }
    if (pthread_create(&tid_vision, NULL, thread_vision, &g_state) != 0) {
        printf("[MAIN] 启动视觉线程失败\n");
        g_running = 0;
        pthread_join(tid_sensor, NULL);
        return 1;
    }
    if (pthread_create(&tid_decision, NULL, thread_decision, &g_state) != 0) {
        printf("[MAIN] 启动决策线程失败\n");
        g_running = 0;
        pthread_join(tid_sensor, NULL);
        pthread_join(tid_vision, NULL);
        return 1;
    }
    if (pthread_create(&tid_alarm, NULL, thread_alarm, &g_state) != 0) {
        printf("[MAIN] 启动报警线程失败\n");
        g_running = 0;
        pthread_join(tid_sensor, NULL);
        pthread_join(tid_vision, NULL);
        pthread_join(tid_decision, NULL);
        return 1;
    }
    if (pthread_create(&tid_heartbeat, NULL, thread_heartbeat, &g_state) != 0) {
        printf("[MAIN] 启动心跳线程失败\n");
        g_running = 0;
        pthread_join(tid_sensor, NULL);
        pthread_join(tid_vision, NULL);
        pthread_join(tid_decision, NULL);
        pthread_join(tid_alarm, NULL);
        return 1;
    }

    printf("[MAIN] 系统已启动，按 Ctrl+C 退出\n");

    /*
     * 主线程等待所有子线程结束。
     *
     * 说明：
     * - 这里不主动干预各线程内部逻辑；
     * - 各线程看到 g_running=0 后自己收尾退出；
     * - 最后主线程统一收尾，保证资源释放顺序清晰。
     */
    pthread_join(tid_sensor, NULL);
    pthread_join(tid_vision, NULL);
    pthread_join(tid_decision, NULL);
    pthread_join(tid_alarm, NULL);
    pthread_join(tid_heartbeat, NULL);

    /*
     * 退出前统一关闭外设与队列。
     * 这里先保留打印，后续接入真正句柄时再释放。
     */
    printf("[MAIN] 关闭串口和消息队列...\n");
    g_sensor_port = NULL;
    g_alarm_port = NULL;
    g_alarm_queue = NULL;

    pthread_mutex_destroy(&g_state.lock);
    printf("系统正常退出\n");
    return 0;
}
