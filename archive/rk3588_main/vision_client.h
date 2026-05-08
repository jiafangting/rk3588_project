#ifndef VISION_CLIENT_H
#define VISION_CLIENT_H

#include <stddef.h>

#define VISION_DEFAULT_SOCKET_PATH "/tmp/vision_inspection.sock"
#define VISION_STATUS_LEN 32
#define VISION_REASON_LEN 256
#define VISION_TIMESTAMP_LEN 64
#define VISION_SOCKET_PATH_LEN 108

typedef struct {
    char status[VISION_STATUS_LEN];
    int person_count;
    char reason[VISION_REASON_LEN];
    char timestamp[VISION_TIMESTAMP_LEN];
} VisionResult;

typedef struct {
    int fd;
    char socket_path[VISION_SOCKET_PATH_LEN];
} VisionClient;

void vision_client_init(VisionClient *client, const char *socket_path);
int vision_client_connect(VisionClient *client);
void vision_client_close(VisionClient *client);
int vision_client_is_connected(const VisionClient *client);
int vision_client_get_status(VisionClient *client, VisionResult *result, int timeout_ms);
int vision_client_trigger_inspection(VisionClient *client, VisionResult *result, int timeout_ms);
int vision_client_shutdown_vision(VisionClient *client, int timeout_ms);
int vision_client_wait_result(VisionClient *client, VisionResult *result, int timeout_ms);
void vision_result_print(const VisionResult *result);

#endif
