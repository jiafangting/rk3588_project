#include "vision_client.h"
#include "decision_engine.h"
#include "actuator_control.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define CONNECT_RETRY_SECONDS 1
#define COMMAND_TIMEOUT_MS 8000
#define PASSIVE_WAIT_TIMEOUT_MS 1000

static void print_menu(void)
{
    printf("\n");
    printf("========== RK3588 Main Process ==========\n");
    printf("g  - get vision status\n");
    printf("t  - trigger inspection snapshot\n");
    printf("w  - wait one pushed vision result\n");
    printf("a  - auto monitor vision status 10 times\n");
    printf("s  - ask Python vision module to shutdown\n");
    printf("q  - quit C main process only\n");
    printf("h  - show menu\n");
    printf("=========================================\n");
    printf("input command > ");
    fflush(stdout);
}

static int connect_with_retry(VisionClient *client, int max_retry_count)
{
    int retry = 0;
    while (max_retry_count < 0 || retry < max_retry_count) {
        if (vision_client_connect(client) == 0) {
            return 0;
        }
        retry++;
        printf("[MAIN] Python vision socket not ready, retry %d...\n", retry);
        sleep(CONNECT_RETRY_SECONDS);
    }
    return -1;
}

static int reconnect_if_needed(VisionClient *client)
{
    if (vision_client_is_connected(client)) {
        return 0;
    }
    printf("[MAIN] vision socket disconnected, reconnecting...\n");
    return connect_with_retry(client, 3);
}

static void handle_vision_result(const VisionResult *result)
{
    SystemDecision decision;
    if (result == NULL) {
        return;
    }
    vision_result_print(result);
    decision = decision_engine_update(result);
    decision_engine_print(&decision);
    actuator_apply_decision(&decision);
}

static void handle_get_status(VisionClient *client)
{
    VisionResult result;
    if (reconnect_if_needed(client) != 0) {
        printf("[MAIN] cannot connect vision module\n");
        return;
    }
    if (vision_client_get_status(client, &result, COMMAND_TIMEOUT_MS) != 0) {
        printf("[MAIN] get_status failed\n");
        vision_client_close(client);
        return;
    }
    handle_vision_result(&result);
}

static void handle_trigger_inspection(VisionClient *client)
{
    VisionResult result;
    if (reconnect_if_needed(client) != 0) {
        printf("[MAIN] cannot connect vision module\n");
        return;
    }
    if (vision_client_trigger_inspection(client, &result, COMMAND_TIMEOUT_MS) != 0) {
        printf("[MAIN] trigger_inspection failed\n");
        vision_client_close(client);
        return;
    }
    handle_vision_result(&result);
}

static void handle_wait_result(VisionClient *client)
{
    VisionResult result;
    if (reconnect_if_needed(client) != 0) {
        printf("[MAIN] cannot connect vision module\n");
        return;
    }
    printf("[MAIN] waiting pushed result from Python vision module...\n");
    if (vision_client_wait_result(client, &result, PASSIVE_WAIT_TIMEOUT_MS) != 0) {
        printf("[MAIN] no pushed result in this wait window\n");
        return;
    }
    handle_vision_result(&result);
}

static void handle_auto_monitor(VisionClient *client)
{
    const int monitor_count = 10;
    int i;
    if (reconnect_if_needed(client) != 0) {
        printf("[MAIN] cannot connect vision module\n");
        return;
    }
    printf("[MAIN] auto monitor started, count=%d, interval=1s\n", monitor_count);
    for (i = 0; i < monitor_count; i++) {
        VisionResult result;
        printf("[MAIN] auto monitor cycle %d/%d\n", i + 1, monitor_count);
        if (vision_client_get_status(client, &result, COMMAND_TIMEOUT_MS) != 0) {
            printf("[MAIN] auto monitor get_status failed\n");
            vision_client_close(client);
            return;
        }
        handle_vision_result(&result);
        sleep(1);
    }
}

static void handle_shutdown_vision(VisionClient *client)
{
    if (reconnect_if_needed(client) != 0) {
        printf("[MAIN] cannot connect vision module\n");
        return;
    }
    if (vision_client_shutdown_vision(client, COMMAND_TIMEOUT_MS) != 0) {
        printf("[MAIN] shutdown vision command failed\n");
        vision_client_close(client);
        return;
    }
    printf("[MAIN] shutdown command sent to Python vision module\n");
}

int main(int argc, char *argv[])
{
    VisionClient vision_client;
    const char *socket_path = VISION_DEFAULT_SOCKET_PATH;
    int running = 1;

    if (argc >= 2) {
        socket_path = argv[1];
    }

    printf("[MAIN] RK3588 industrial inspection main process starting\n");
    printf("[MAIN] vision socket path: %s\n", socket_path);

    vision_client_init(&vision_client, socket_path);
    actuator_init();

    if (connect_with_retry(&vision_client, 3) != 0) {
        printf("[MAIN] vision module not connected yet, you can still use menu to retry\n");
    }

    print_menu();
    while (running) {
        char input[32];
        if (fgets(input, sizeof(input), stdin) == NULL) {
            break;
        }

        switch (input[0]) {
        case 'g':
        case 'G':
            handle_get_status(&vision_client);
            break;
        case 't':
        case 'T':
            handle_trigger_inspection(&vision_client);
            break;
        case 'w':
        case 'W':
            handle_wait_result(&vision_client);
            break;
        case 'a':
        case 'A':
            handle_auto_monitor(&vision_client);
            break;
        case 's':
        case 'S':
            handle_shutdown_vision(&vision_client);
            break;
        case 'q':
        case 'Q':
            running = 0;
            break;
        case 'h':
        case 'H':
        case '\n':
            break;
        default:
            printf("[MAIN] unknown command: %c\n", input[0]);
            break;
        }

        if (running) {
            print_menu();
        }
    }

    vision_client_close(&vision_client);
    actuator_shutdown();
    printf("[MAIN] C main process exited\n");
    return 0;
}
