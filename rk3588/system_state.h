#ifndef SYSTEM_STATE_H
#define SYSTEM_STATE_H

#include <pthread.h>
#include <stdint.h>
#include <time.h>

/*
 * 系统全局状态结构体。
 *
 * 这是 RK3588 多线程程序里最核心的数据容器。
 * 所有线程都围绕这一份状态交换信息：
 * - 传感器线程写温度、湿度、电流、烟雾；
 * - 视觉线程写视觉状态、人数、禁区命中；
 * - 决策线程读前面两类信息并写报警状态；
 * - 报警线程根据报警状态执行蜂鸣器/LED 动作；
 * - 心跳线程监控大家是否还活着。
 *
 * 原理：
 * - 共享结构体 + 互斥锁 = 多线程安全的数据交换方式；
 * - 避免每个线程自己保存一套数据导致状态不一致。
 */
typedef struct {
    /* 传感器数据 */
    float    temperature;
    float    humidity;
    float    temp_device;
    float    current;
    uint8_t  smoke;

    /* 视觉数据 */
    char     vision_status[16];
    int      person_count;
    int      zone_hit;
    char     alarm_type[32];
    char     alarm_reason[128];

    /* 系统状态 */
    int      alarm_active;
    char     last_alarm_reason[128];
    time_t   last_alarm_time;
    int      alarm_count_today;

    /* 线程心跳时间戳 */
    time_t   heartbeat[5];

    pthread_mutex_t lock;
} SystemState;

/* 全局状态实例，由 main.c 定义。 */
extern SystemState g_state;

/* 全局运行开关，由信号处理函数控制。 */
extern volatile int g_running;

#endif
