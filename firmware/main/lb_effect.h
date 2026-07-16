#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "lb_config.h"

typedef enum {
    LB_EFFECT_OFF = 0,
    LB_EFFECT_BLINK_RED,
    LB_EFFECT_BLINK_GREEN,
    LB_EFFECT_BLINK_BLUE,
    LB_EFFECT_SOLID_BLUE,
} lb_effect_mode_t;

typedef struct {
    lb_effect_mode_t mode;
    uint16_t period_ms;
    uint8_t requested_brightness;
    uint8_t actual_brightness;
    bool illuminated;
} lb_effect_snapshot_t;

esp_err_t lb_effect_init(const lb_config_t *config);
esp_err_t lb_effect_schedule(lb_effect_mode_t mode, uint16_t period_ms,
                             uint8_t brightness, int64_t apply_local_us);
void lb_effect_force_off(void);
lb_effect_snapshot_t lb_effect_snapshot(void);
const char *lb_effect_mode_name(lb_effect_mode_t mode);
bool lb_effect_mode_from_name(const char *name, lb_effect_mode_t *mode);

