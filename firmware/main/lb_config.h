#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#define LB_NODE_ID_MAX 32
#define LB_SSID_MAX 32
#define LB_WIFI_PASSWORD_MAX 64
#define LB_HMAC_KEY_SIZE 32

typedef struct {
    bool provisioned;
    char node_id[LB_NODE_ID_MAX + 1];
    char ssid[LB_SSID_MAX + 1];
    char wifi_password[LB_WIFI_PASSWORD_MAX + 1];
    uint8_t hmac_key[LB_HMAC_KEY_SIZE];
    uint16_t side_led_count;
    uint16_t top_led_count;
    uint8_t brightness_cap;
} lb_config_t;

esp_err_t lb_config_init(void);
esp_err_t lb_config_load(lb_config_t *config);
esp_err_t lb_config_save(const lb_config_t *config);
esp_err_t lb_config_erase(void);
bool lb_config_valid_node_id(const char *node_id);
bool lb_config_hex_to_key(const char *hex, uint8_t key[LB_HMAC_KEY_SIZE]);

