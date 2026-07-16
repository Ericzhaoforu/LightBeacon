#pragma once

#include <stdbool.h>

#include "esp_err.h"

esp_err_t lb_ota_start(const char *url, const char *token, const char *sha256_hex,
                       const char *expected_version);
bool lb_ota_in_progress(void);
const char *lb_ota_state(void);
esp_err_t lb_ota_confirm_running_image(void);

