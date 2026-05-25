#include "system_state.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

/*
 * 视觉模块 Unix Socket 路径和查询参数。
 *
 * 这个线程的工作不是做视觉识别，而是“定期问视觉模块现在是什么状态”。
 *
 * 重要参数：
 * - `VISION_SOCKET_ENV`：环境变量名，允许现场部署时改路径；
 * - `DEFAULT_VISION_SOCKET_PATH`：默认 socket 路径；
 * - `VISION_QUERY_INTERVAL_SEC`：每隔多少秒查询一次；
 * - `VISION_SOCKET_TIMEOUT_SEC`：连接和读写超时时间。
 *
 * 原理：
 * - 视觉模块和 RK3588 主控是两个独立进程；
 * - 它们通过 Unix Socket 交换 JSON 数据；
 * - 线程不断查询最新状态，更新到共享状态 `g_state`。
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
 * - alarm_reason
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

static int parse_bool_field(const char *json, const char *key, int default_value)
{
    const char *p = strstr(json, key);
    if (!p) {
        return default_value;
    }

    p = strchr(p, ':');
    if (!p) {
        return default_value;
    }
    p++;

    while (*p == ' ' || *p == '\t' || *p == '"') {
        p++;
    }

    if (strncmp(p, "true", 4) == 0 || strncmp(p, "TRUE", 4) == 0) {
        return 1;
    }
    if (strncmp(p, "false", 5) == 0 || strncmp(p, "FALSE", 5) == 0) {
        return 0;
    }

    return atoi(p) != 0;
}

static void mark_vision_unknown(SystemState *state)
{
    pthread_mutex_lock(&state->lock);
    snprintf(state->vision_status, sizeof(state->vision_status), "UNKNOWN");
    state->person_count = 0;
    state->zone_hit = 0;
    snprintf(state->alarm_type, sizeof(state->alarm_type), "");
    snprintf(state->alarm_reason, sizeof(state->alarm_reason), "");
    pthread_mutex_unlock(&state->lock);
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
    /*
     * 线程入口：视觉查询线程。
     *
     * 参数：
     * - arg：`SystemState *`，共享状态指针
     *
     * 返回值：
     * - `NULL`
     *
     * 流程：
     * 1. 取出共享状态；
     * 2. 连接视觉 socket；
     * 3. 发送 `{"cmd":"get_status"}`；
     * 4. 解析返回 JSON；
     * 5. 更新视觉状态、人数、禁区命中、报警类型；
     * 6. 更新心跳；
     * 7. 睡眠后重试。
     */
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
            mark_vision_unknown(state);
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
            mark_vision_unknown(state);
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
            mark_vision_unknown(state);
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
         * - alarm_reason
         *
         * 这里不使用第三方库，保证 C99 环境下直接可编译。
         */
        char status[16] = {0};
        char alarm_type[32] = {0};
        char alarm_reason[128] = {0};
        int person_count = 0;
        int zone_hit = 0;

        parse_string_field(buffer, "\"status\"", status, sizeof(status));
        parse_string_field(buffer, "\"alarm_type\"", alarm_type, sizeof(alarm_type));
        parse_string_field(buffer, "\"alarm_reason\"", alarm_reason, sizeof(alarm_reason));
        person_count = parse_int_field(buffer, "\"person_count\"", 0);
        zone_hit = parse_bool_field(buffer, "\"zone_hit\"", 0);

        pthread_mutex_lock(&state->lock);
        snprintf(state->vision_status, sizeof(state->vision_status), "%s", status[0] ? status : "UNKNOWN");
        state->person_count = person_count;
        state->zone_hit = zone_hit;
        snprintf(state->alarm_type, sizeof(state->alarm_type), "%s", alarm_type);
        snprintf(state->alarm_reason, sizeof(state->alarm_reason), "%s", alarm_reason);
        state->heartbeat[1] = time(NULL);
        pthread_mutex_unlock(&state->lock);

        printf("[VISION] status=%s person_count=%d zone_hit=%d alarm_type=%s alarm_reason=%s\n",
               status[0] ? status : "UNKNOWN", person_count, zone_hit, alarm_type, alarm_reason);

        sleep(VISION_QUERY_INTERVAL_SEC);
    }

    printf("[VISION] 线程退出\n");
    return NULL;
}
