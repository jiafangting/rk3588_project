#ifndef ACTUATOR_CONTROL_H
#define ACTUATOR_CONTROL_H

#include "decision_engine.h"

void actuator_init(void);
void actuator_apply_decision(const SystemDecision *decision);
void actuator_shutdown(void);

#endif
