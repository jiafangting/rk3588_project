#include "system_state.h"
#include "threshold_config.h"

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>

#define CONTROL_SOCKET_ENV "INSPECTION_CONTROL_SOCKET_PATH"
#define DEFAULT_CONTROL_SOCKET_PATH "/tmp/inspection_control.sock"
#define CONTROL_CONFIG_PATH "config.json"
#define CONTROL_SOCKET_TIMEOUT_SEC 1

extern ThresholdConfig g_threshold;
extern pthread_mutex_t g_threshold_lock;

static const char *get_control_socket_path(void)
{
    const char *configured_path = getenv(CONTROL_SOCKET_ENV);
    if (configured_path && configured_path[0] != '\0') {
        return configured_path;
    }
    return DEFAULT_CONTROL_SOCKET_PATH;
}

static void send_json(int client_fd, const char *json)
{
    if (client_fd < 0 || !json) {
        return;
    }
    (void)send(client_fd, json, strlen(json), 0);
}

static int is_reload_config_command(const char *command)
{
    if (!command) {
        return 0;
    }
    return strstr(command, "\"cmd\"") != NULL && strstr(command, "reload_config") != NULL;
}

static void handle_control_command(int client_fd, const char *command)
{
    ThresholdConfig new_cfg;
    int load_result;

    if (!is_reload_config_command(command)) {
        send_json(client_fd, "{\"ack\":false,\"message\":\"unknown command\"}\n");
        return;
    }

    load_result = load_threshold(CONTROL_CONFIG_PATH, &new_cfg);

    pthread_mutex_lock(&g_threshold_lock);
    g_threshold = new_cfg;
    pthread_mutex_unlock(&g_threshold_lock);

    if (load_result == 0) {
        send_json(client_fd, "{\"ack\":true,\"message\":\"config reloaded\"}\n");
        printf("[CONTROL] config reloaded\n");
    } else {
        send_json(client_fd, "{\"ack\":false,\"message\":\"config reload failed, defaults applied\"}\n");
        printf("[CONTROL] config reload failed, defaults applied\n");
    }
}

void *thread_control(void *arg)
{
    int server_fd = -1;
    struct sockaddr_un addr;
    const char *socket_path = get_control_socket_path();
    struct timeval timeout;

    (void)arg;

    if (strlen(socket_path) >= sizeof(addr.sun_path)) {
        printf("[CONTROL] socket path too long: %s\n", socket_path);
        return NULL;
    }

    server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd < 0) {
        printf("[CONTROL] create socket failed\n");
        return NULL;
    }

    timeout.tv_sec = CONTROL_SOCKET_TIMEOUT_SEC;
    timeout.tv_usec = 0;
    setsockopt(server_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    unlink(socket_path);
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", socket_path);

    if (bind(server_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        printf("[CONTROL] bind %s failed\n", socket_path);
        close(server_fd);
        return NULL;
    }

    if (listen(server_fd, 4) != 0) {
        printf("[CONTROL] listen failed\n");
        close(server_fd);
        unlink(socket_path);
        return NULL;
    }

    printf("[CONTROL] listening on %s\n", socket_path);

    while (g_running) {
        int client_fd;
        char buffer[1024];
        ssize_t nread;

        client_fd = accept(server_fd, NULL, NULL);
        if (client_fd < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
                continue;
            }
            printf("[CONTROL] accept failed\n");
            continue;
        }

        setsockopt(client_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        nread = read(client_fd, buffer, sizeof(buffer) - 1);
        if (nread <= 0) {
            send_json(client_fd, "{\"ack\":false,\"message\":\"empty command\"}\n");
            close(client_fd);
            continue;
        }

        buffer[nread] = '\0';
        handle_control_command(client_fd, buffer);
        close(client_fd);
    }

    close(server_fd);
    unlink(socket_path);
    printf("[CONTROL] thread exited\n");
    return NULL;
}
