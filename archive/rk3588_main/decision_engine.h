#ifndef DECISION_ENGINE_H
#define DECISION_ENGINE_H

#include "vision_client.h"

#define DECISION_REASON_LEN 256

typedef enum {
    SYSTEM_NORMAL = 0,
    SYSTEM_WARNING,
    SYSTEM_ALARM,
    SYSTEM_EMERGENCY
} SystemState;

typedef struct {
    SystemState state;
    char reason[DECISION_REASON_LEN];
    int need_buzzer;
    int need_warning_light;
    int need_relay_cutoff;
} SystemDecision;

const char *system_state_to_string(SystemState state);
SystemDecision decision_engine_update(const VisionResult *vision);
void decision_engine_print(const SystemDecision *decision);

#endif
