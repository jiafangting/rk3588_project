#include "actuator_control.h"

#include <stdio.h>

static void set_buzzer(int on)
{
    printf("[ACTUATOR] buzzer: %s\n", on ? "ON" : "OFF");
}

static void set_warning_light(int on)
{
    printf("[ACTUATOR] warning light: %s\n", on ? "ON" : "OFF");
}

static void set_relay_cutoff(int on)
{
    printf("[ACTUATOR] relay cutoff: %s\n", on ? "ON" : "OFF");
}

void actuator_init(void)
{
    printf("[ACTUATOR] init simulated actuator layer\n");
    set_buzzer(0);
    set_warning_light(0);
    set_relay_cutoff(0);
}

void actuator_apply_decision(const SystemDecision *decision)
{
    if (decision == NULL) {
        return;
    }
    printf("[ACTUATOR] apply system state: %s\n", system_state_to_string(decision->state));
    set_buzzer(decision->need_buzzer);
    set_warning_light(decision->need_warning_light);
    set_relay_cutoff(decision->need_relay_cutoff);
}

void actuator_shutdown(void)
{
    printf("[ACTUATOR] shutdown simulated actuator layer\n");
    set_buzzer(0);
    set_warning_light(0);
    set_relay_cutoff(0);
}
