#ifndef SYSTEM_STATE_H
#define SYSTEM_STATE_H

#include <pthread.h>
#include <stdint.h>
#include <time.h>

/*
 * 系统全局状态。
 *
 * 这个结构体把传感器、视觉、报警、心跳都集中到一起，
 * 方便各线程共享数据时只围绕这一份状态表进行读写。
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
