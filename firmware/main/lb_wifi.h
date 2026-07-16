#pragma once

#include <stdbool.h>

#include "esp_err.h"
#include "lb_config.h"

esp_err_t lb_wifi_start_station(const lb_config_t *config, bool wait_for_ip);
esp_err_t lb_wifi_start_provisioning(void);
void lb_wifi_start_factory_reset_monitor(void);
bool lb_wifi_is_connected(void);
int lb_wifi_rssi(void);
void lb_wifi_ip_string(char *buffer, size_t capacity);

