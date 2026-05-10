#include "system_state.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

/*
 * 视觉模块 Unix Socket 路径。
 *
 * 重要参数：
 * - 必须和 Python 视觉模块一致；
 * - 连接失败不能崩溃，只能等下次重试；
 * - 查询频率默认 2 秒一次。
 */
#define VISION_SOCKET_ENV "VISION_SOCKET_PATH"
#define DEFAULT_VISION_SOCKET_PATH "/tmp/vision_inspection.sock"
#define VISION_QUERY_INTERVAL_SEC 2
#define VISION_SOCKET_TIMEOUT_SEC 2

/*
 * 返回当前进程要连接的视觉 Unix Socket 路径。
 *
 * 统一规则：
 * - 默认值使用 /tmp/vision_inspection.sock，和 Python 视觉服务端、语音模块、
 *   UI、健康检查脚本保持一致；
 * - 现场部署如果要改路径，只设置环境变量 VISION_SOCKET_PATH，不再分散修改代码；
 * - 环境变量为空字符串时视为未配置，避免 connect("") 这种难排查的问题。
 */
static const char *get_vision_socket_path(void)
{
    const char *configured_path = getenv(VISION_SOCKET_ENV);
    if (configured_path && configured_path[0] != '\0') {
        return configured_path;
    }
    return DEFAULT_VISION_SOCKET_PATH;
}

/*
 * 手工解析 JSON 字段的小工具。
 *
 * 这里只提取几个最关键字段：
 * - status
 * - person_count
 * - zone_hit
 * - alarm_type
 *
 * 不依赖第三方库，只做字符串查找和基础解析。
 */
static void parse_string_field(const char *json, const char *key, char *out, size_t out_size)
{
    const char *p = strstr(json, key);
    if (!p || !out || out_size == 0) {
        return;
    }

    p = strchr(p, ':');
    if (!p) {
        return;
    }
    p++;

    while (*p == ' ' || *p == '"') {
        p++;
    }

    size_t i = 0;
    while (*p && *p != '"' && *p != ',' && *p != '}' && i + 1 < out_size) {
        out[i++] = *p++;
    }
    out[i] = '\0';
}

static int parse_int_field(const char *json, const char *key, int default_value)
{
    const char *p = strstr(json, key);
    if (!p) {
        return default_value;
    }

    p = strchr(p, ':');
    if (!p) {
        return default_value;
    }

    return atoi(p + 1);
}

/*
 * 线程 1：视觉查询线程。
 *
 * 作用：
 * - 每 2 秒向视觉模块发一次 get_status；
 * - 解析返回 JSON；
 * - 更新 g_state 里的视觉字段；
 * - 连接失败时不退出，只打印警告。
 */
void *thread_vision(void *arg)
{
    SystemState *state = (SystemState *)arg;

    if (!state) {
        return NULL;
    }

    while (g_running) {
        int sockfd = -1;
        struct sockaddr_un addr;
        char buffer[4096];
        ssize_t nread;
        const char *socket_path = get_vision_socket_path();
        const char *request = "{\"cmd\":\"get_status\"}\n";

        memset(&addr, 0, sizeof(addr));
        addr.sun_family = AF_UNIX;
        snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", socket_path);

        sockfd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (sockfd < 0) {
            printf("[VISION] 创建 socket 失败\n");
            pthread_mutex_lock(&state->lock);
            snprintf(state->vision_status, sizeof(state->vision_status), "UNKNOWN");
            pthread_mutex_unlock(&state->lock);
            sleep(VISION_QUERY_INTERVAL_SEC);
            continue;
        }

        struct timeval tv;
        tv.tv_sec = VISION_SOCKET_TIMEOUT_SEC;
        tv.tv_usec = 0;
        setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        setsockopt(sockfd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

        if (connect(sockfd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
            printf("[VISION] connect %s failed, wait for next retry\n", socket_path);
            pthread_mutex_lock(&state->lock);
            snprintf(state->vision_status, sizeof(state->vision_status), "UNKNOWN");
            pthread_mutex_unlock(&state->lock);
            close(sockfd);
            sleep(VISION_QUERY_INTERVAL_SEC);
            continue;
        }

        if (write(sockfd, request, strlen(request)) < 0) {
            printf("[VISION] 发送查询请求失败\n");
            close(sockfd);
            sleep(VISION_QUERY_INTERVAL_SEC);
            continue;
        }

        nread = read(sockfd, buffer, sizeof(buffer) - 1);
        close(sockfd);
        if (nread <= 0) {
            printf("[VISION] 未收到视觉模块返回\n");
            pthread_mutex_lock(&state->lock);
            snprintf(state->vision_status, sizeof(state->vision_status), "UNKNOWN");
            pthread_mutex_unlock(&state->lock);
            sleep(VISION_QUERY_INTERVAL_SEC);
            continue;
        }

        buffer[nread] = '\0';

        /*
         * 手工解析 JSON：
         * - status
         * - person_count
         * - zone_hit
         * - alarm_type
         *
         * 这里不使用第三方库，保证 C99 环境下直接可编译。
         */
        char status[16] = {0};
        char alarm_type[32] = {0};
        int person_count = 0;
        int zone_hit = 0;

        parse_string_field(buffer, "\"status\"", status, sizeof(status));
        parse_string_field(buffer, "\"alarm_type\"", alarm_type, sizeof(alarm_type));
        person_count = parse_int_field(buffer, "\"person_count\"", 0);
        zone_hit = parse_int_field(buffer, "\"zone_hit\"", 0);

        pthread_mutex_lock(&state->lock);
        snprintf(state->vision_status, sizeof(state->vision_status), "%s", status[0] ? status : "UNKNOWN");
        state->person_count = person_count;
        state->zone_hit = zone_hit;
        snprintf(state->alarm_type, sizeof(state->alarm_type), "%s", alarm_type);
        state->heartbeat[1] = time(NULL);
        pthread_mutex_unlock(&state->lock);

        printf("[VISION] status=%s person_count=%d zone_hit=%d alarm_type=%s\n",
               status[0] ? status : "UNKNOWN", person_count, zone_hit, alarm_type);

        sleep(VISION_QUERY_INTERVAL_SEC);
    }

    printf("[VISION] 线程退出\n");
    return NULL;
}
