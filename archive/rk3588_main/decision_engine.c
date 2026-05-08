#include "decision_engine.h"

#include <stdio.h>
#include <string.h>

static void decision_safe_copy(char *dst, size_t dst_len, const char *src)
{
    if (dst == NULL || dst_len == 0) {
        return;
    }
    snprintf(dst, dst_len, "%s", src ? src : "");
}

static int status_is(const char *left, const char *right)
{
    return left != NULL && right != NULL && strcmp(left, right) == 0;
}

static SystemDecision make_default_decision(void)
{
    SystemDecision decision;
    memset(&decision, 0, sizeof(decision));
    decision.state = SYSTEM_WARNING;
    decision.need_warning_light = 1;
    decision_safe_copy(decision.reason, sizeof(decision.reason), "Vision result is unavailable");
    return decision;
}

const char *system_state_to_string(SystemState state)
{
    switch (state) {
    case SYSTEM_NORMAL:
        return "NORMAL";
    case SYSTEM_WARNING:
        return "WARNING";
    case SYSTEM_ALARM:
        return "ALARM";
    case SYSTEM_EMERGENCY:
        return "EMERGENCY";
    default:
        return "UNKNOWN";
    }
}

SystemDecision decision_engine_update(const VisionResult *vision)
{
    SystemDecision decision = make_default_decision();

    if (vision == NULL) {
        return decision;
    }

    if (status_is(vision->status, "NORMAL")) {
        decision.state = SYSTEM_NORMAL;
        decision.need_buzzer = 0;
        decision.need_warning_light = 0;
        decision.need_relay_cutoff = 0;
        decision_safe_copy(decision.reason, sizeof(decision.reason), vision->reason);
        return decision;
    }

    if (status_is(vision->status, "ABNORMAL")) {
        decision.state = SYSTEM_WARNING;
        decision.need_buzzer = 0;
        decision.need_warning_light = 1;
        decision.need_relay_cutoff = 0;
        decision_safe_copy(decision.reason, sizeof(decision.reason), vision->reason);
        return decision;
    }

    if (status_is(vision->status, "ALARM")) {
        decision.state = SYSTEM_ALARM;
        decision.need_buzzer = 1;
        decision.need_warning_light = 1;
        decision.need_relay_cutoff = 0;
        decision_safe_copy(decision.reason, sizeof(decision.reason), vision->reason);
        return decision;
    }

    decision.state = SYSTEM_WARNING;
    decision.need_warning_light = 1;
    snprintf(decision.reason, sizeof(decision.reason), "Unknown vision status: %s", vision->status);
    return decision;
}

void decision_engine_print(const SystemDecision *decision)
{
    if (decision == NULL) {
        return;
    }
    printf("--------------- System Decision ------------\n");
    printf("state          : %s\n", system_state_to_string(decision->state));
    printf("reason         : %s\n", decision->reason);
    printf("buzzer         : %s\n", decision->need_buzzer ? "ON" : "OFF");
    printf("warning light  : %s\n", decision->need_warning_light ? "ON" : "OFF");
    printf("relay cutoff   : %s\n", decision->need_relay_cutoff ? "ON" : "OFF");
    printf("---------------------------------------------\n");
}
