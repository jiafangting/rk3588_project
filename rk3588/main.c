#include "system_state.h"
#include "threshold_config.h"

#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/*
 * main.c 是 RK3588 端程序的总入口。
 *
 * 这一层只负责“组织各线程、组织共享状态、组织退出流程”，
 * 不负责具体传感器采集、视觉识别或报警动作。
 *
 * 整体结构可以理解成：
 * - main.c：总指挥
 * - thread_sensor.c：传感器采集
 * - thread_vision.c：视觉识别
 * - thread_decision.c：报警决策
 * - thread_alarm.c：报警执行
 * - thread_heartbeat.c：心跳/在线状态
 */

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
void *thread_control(void *arg);

/*
 * 全局运行开关。
 * 信号处理函数把它置 0，所有线程看到后自行退出。
 *
 * 重要说明：
 * - 这是一个“全局停止标志”；
 * - 所有线程都要轮询它；
 * - 这样按 Ctrl+C 时，系统能按统一流程退出。
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
pthread_mutex_t g_threshold_lock = PTHREAD_MUTEX_INITIALIZER;

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
 * 参数：
 * - state：要初始化的共享状态结构体
 *
 * 返回值：
 * - 无
 *
 * 流程：
 * 1. 检查指针是否为空；
 * 2. 清空整个结构体；
 * 3. 把几个关键字符串初始化成 UNKNOWN 或空字符串；
 * 4. 初始化互斥锁，保证多线程读写安全。
 *
 * 原理：
 * - 多线程同时读写同一个结构体，如果没有锁，可能出现“读到一半”的脏数据；
 * - 所以这个共享状态必须配合 mutex 使用。
 */
static void init_system_state(SystemState *state)
{
    if (!state) {
        return;
    }

    memset(state, 0, sizeof(*state));
    snprintf(state->vision_status, sizeof(state->vision_status), "UNKNOWN");
    snprintf(state->alarm_type, sizeof(state->alarm_type), "");
    snprintf(state->alarm_reason, sizeof(state->alarm_reason), "");
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
    /*
     * 信号处理函数。
     *
     * 参数：
     * - sig：信号编号，比如 SIGINT（Ctrl+C）或 SIGTERM
     *
     * 原理：
     * - 进程收到退出信号后，不要立刻粗暴结束所有线程；
     * - 而是先把 g_running 设为 0；
     * - 各个线程在自己的循环里看到这个标志后，自己退出；
     * - 这样能保证资源释放顺序更安全。
     */
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
    /*
     * main() 是 RK3588 主程序入口。
     *
     * 入口参数：
     * - 无
     *
     * 返回值：
     * - 0：正常退出
     * - 1：线程启动失败或初始化失败
     *
     * 总流程：
     * 1. 初始化共享状态；
     * 2. 读取阈值配置；
     * 3. 注册信号处理；
     * 4. 启动各业务线程；
     * 5. 等待线程退出；
     * 6. 清理资源并返回。
     */
    pthread_t tid_sensor;
    pthread_t tid_vision;
    pthread_t tid_decision;
    pthread_t tid_alarm;
    pthread_t tid_heartbeat;
    pthread_t tid_control;

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
    if (pthread_create(&tid_control, NULL, thread_control, &g_state) != 0) {
        printf("[MAIN] 启动控制命令线程失败\n");
        g_running = 0;
        pthread_join(tid_sensor, NULL);
        pthread_join(tid_vision, NULL);
        pthread_join(tid_decision, NULL);
        pthread_join(tid_alarm, NULL);
        pthread_join(tid_heartbeat, NULL);
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
    pthread_join(tid_control, NULL);

    /*
     * 退出前统一关闭外设与队列。
     * 这里先保留打印，后续接入真正句柄时再释放。
     */
    printf("[MAIN] 关闭串口和消息队列...\n");
    g_sensor_port = NULL;
    g_alarm_port = NULL;
    g_alarm_queue = NULL;

    pthread_mutex_destroy(&g_state.lock);
    pthread_mutex_destroy(&g_threshold_lock);
    printf("系统正常退出\n");
    return 0;
}
