#include "vision_client.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#define VISION_RX_BUFFER_LEN 1024

static void safe_copy(char *dst, size_t dst_len, const char *src)
{
    if (dst == NULL || dst_len == 0) {
        return;
    }
    if (src == NULL) {
        dst[0] = '\0';
        return;
    }
    snprintf(dst, dst_len, "%s", src);
}

static int send_all(int fd, const char *data, size_t len)
{
    size_t sent_total = 0;
    while (sent_total < len) {
        ssize_t sent = send(fd, data + sent_total, len - sent_total, 0);
        if (sent < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("[VISION_CLIENT] send failed");
            return -1;
        }
        if (sent == 0) {
            return -1;
        }
        sent_total += (size_t)sent;
    }
    return 0;
}

static int wait_fd_readable(int fd, int timeout_ms)
{
    fd_set read_set;
    struct timeval timeout;
    struct timeval *timeout_ptr = NULL;

    FD_ZERO(&read_set);
    FD_SET(fd, &read_set);

    if (timeout_ms >= 0) {
        timeout.tv_sec = timeout_ms / 1000;
        timeout.tv_usec = (timeout_ms % 1000) * 1000;
        timeout_ptr = &timeout;
    }

    while (1) {
        int ret = select(fd + 1, &read_set, NULL, NULL, timeout_ptr);
        if (ret < 0 && errno == EINTR) {
            continue;
        }
        return ret;
    }
}

static int read_json_line(VisionClient *client, char *buffer, size_t buffer_len, int timeout_ms)
{
    size_t used = 0;
    if (client == NULL || buffer == NULL || buffer_len == 0 || client->fd < 0) {
        return -1;
    }

    buffer[0] = '\0';
    while (used + 1 < buffer_len) {
        int ready = wait_fd_readable(client->fd, timeout_ms);
        if (ready == 0) {
            fprintf(stderr, "[VISION_CLIENT] read timeout\n");
            return -1;
        }
        if (ready < 0) {
            perror("[VISION_CLIENT] select failed");
            return -1;
        }

        char ch = '\0';
        ssize_t n = recv(client->fd, &ch, 1, 0);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("[VISION_CLIENT] recv failed");
            return -1;
        }
        if (n == 0) {
            return -1;
        }
        if (ch == '\n') {
            break;
        }
        buffer[used++] = ch;
    }

    buffer[used] = '\0';
    return used == 0 ? -1 : 0;
}

static int extract_json_string(const char *json, const char *key, char *out, size_t out_len)
{
    char pattern[64];
    char *key_pos;
    char *colon_pos;
    char *value_start;
    char *value_end;
    size_t len;

    if (json == NULL || key == NULL || out == NULL || out_len == 0) {
        return -1;
    }
    out[0] = '\0';
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    key_pos = strstr(json, pattern);
    if (key_pos == NULL) {
        return -1;
    }
    colon_pos = strchr(key_pos + strlen(pattern), ':');
    if (colon_pos == NULL) {
        return -1;
    }
    value_start = strchr(colon_pos, '"');
    if (value_start == NULL) {
        return -1;
    }
    value_start++;
    value_end = strchr(value_start, '"');
    if (value_end == NULL) {
        return -1;
    }
    len = (size_t)(value_end - value_start);
    if (len >= out_len) {
        len = out_len - 1;
    }
    memcpy(out, value_start, len);
    out[len] = '\0';
    return 0;
}

static int extract_json_int(const char *json, const char *key, int *out)
{
    char pattern[64];
    char *key_pos;
    char *colon_pos;
    char *end_pos;
    long value;

    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    key_pos = strstr(json, pattern);
    if (key_pos == NULL) {
        return -1;
    }
    colon_pos = strchr(key_pos + strlen(pattern), ':');
    if (colon_pos == NULL) {
        return -1;
    }
    value = strtol(colon_pos + 1, &end_pos, 10);
    if (end_pos == colon_pos + 1) {
        return -1;
    }
    *out = (int)value;
    return 0;
}

static int parse_vision_result(const char *json, VisionResult *result)
{
    if (json == NULL || result == NULL) {
        return -1;
    }
    memset(result, 0, sizeof(*result));
    safe_copy(result->status, sizeof(result->status), "UNKNOWN");
    extract_json_string(json, "status", result->status, sizeof(result->status));
    extract_json_int(json, "person_count", &result->person_count);
    extract_json_string(json, "reason", result->reason, sizeof(result->reason));
    extract_json_string(json, "timestamp", result->timestamp, sizeof(result->timestamp));
    return 0;
}

static int read_until_result(VisionClient *client, VisionResult *result, int timeout_ms)
{
    char buffer[VISION_RX_BUFFER_LEN];
    while (1) {
        if (read_json_line(client, buffer, sizeof(buffer), timeout_ms) != 0) {
            return -1;
        }
        printf("[VISION_CLIENT] recv: %s\n", buffer);
        if (strstr(buffer, "\"status\"") != NULL) {
            return parse_vision_result(buffer, result);
        }
    }
}

static int send_command(VisionClient *client, const char *command_json)
{
    if (client == NULL || command_json == NULL || client->fd < 0) {
        return -1;
    }
    printf("[VISION_CLIENT] send: %s", command_json);
    return send_all(client->fd, command_json, strlen(command_json));
}

void vision_client_init(VisionClient *client, const char *socket_path)
{
    if (client == NULL) {
        return;
    }
    memset(client, 0, sizeof(*client));
    client->fd = -1;
    safe_copy(client->socket_path, sizeof(client->socket_path), socket_path ? socket_path : VISION_DEFAULT_SOCKET_PATH);
}

int vision_client_connect(VisionClient *client)
{
    struct sockaddr_un addr;
    int fd;
    if (client == NULL) {
        return -1;
    }
    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        perror("[VISION_CLIENT] socket failed");
        return -1;
    }
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    safe_copy(addr.sun_path, sizeof(addr.sun_path), client->socket_path);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("[VISION_CLIENT] connect failed");
        close(fd);
        client->fd = -1;
        return -1;
    }
    client->fd = fd;
    printf("[VISION_CLIENT] connected: %s\n", client->socket_path);
    return 0;
}

void vision_client_close(VisionClient *client)
{
    if (client != NULL && client->fd >= 0) {
        close(client->fd);
        client->fd = -1;
    }
}

int vision_client_is_connected(const VisionClient *client)
{
    return client != NULL && client->fd >= 0;
}

int vision_client_get_status(VisionClient *client, VisionResult *result, int timeout_ms)
{
    if (send_command(client, "{\"cmd\":\"get_status\"}\n") != 0) {
        return -1;
    }
    return read_until_result(client, result, timeout_ms);
}

int vision_client_trigger_inspection(VisionClient *client, VisionResult *result, int timeout_ms)
{
    if (send_command(client, "{\"cmd\":\"trigger_inspection\"}\n") != 0) {
        return -1;
    }
    return read_until_result(client, result, timeout_ms);
}

int vision_client_shutdown_vision(VisionClient *client, int timeout_ms)
{
    char buffer[VISION_RX_BUFFER_LEN];
    if (send_command(client, "{\"cmd\":\"shutdown\"}\n") != 0) {
        return -1;
    }
    if (read_json_line(client, buffer, sizeof(buffer), timeout_ms) != 0) {
        return -1;
    }
    printf("[VISION_CLIENT] recv: %s\n", buffer);
    return 0;
}

int vision_client_wait_result(VisionClient *client, VisionResult *result, int timeout_ms)
{
    return read_until_result(client, result, timeout_ms);
}

void vision_result_print(const VisionResult *result)
{
    if (result == NULL) {
        return;
    }
    printf("--------------- Vision Result ---------------\n");
    printf("status       : %s\n", result->status);
    printf("person_count : %d\n", result->person_count);
    printf("reason       : %s\n", result->reason);
    printf("timestamp    : %s\n", result->timestamp);
    printf("---------------------------------------------\n");
}
