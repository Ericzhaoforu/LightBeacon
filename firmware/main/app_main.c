#include <inttypes.h>

#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lb_config.h"
#include "lb_effect.h"
#include "lb_ota.h"
#include "lb_udp.h"
#include "lb_wifi.h"

static const char *TAG = "lightbeacon";

static void delayed_ota_confirmation(void *argument)
{
    for (int i = 0; i < 60; ++i) {
        if (lb_wifi_is_connected()) {
            ESP_ERROR_CHECK_WITHOUT_ABORT(lb_ota_confirm_running_image());
            vTaskDelete(NULL);
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    ESP_LOGE(TAG, "New firmware did not reconnect within 60 seconds; leaving image pending for rollback");
    esp_restart();
}

void app_main(void)
{
    esp_chip_info_t chip;
    uint32_t flash_size = 0;
    esp_chip_info(&chip);
    esp_flash_get_size(NULL, &flash_size);
    ESP_LOGI(TAG, "LightBeacon 0.1.0 starting: %d cores, revision %d, flash %" PRIu32 " bytes, reset=%d",
             chip.cores, chip.revision, flash_size, esp_reset_reason());

    ESP_ERROR_CHECK(lb_config_init());
    lb_config_t config;
    ESP_ERROR_CHECK(lb_config_load(&config));
    ESP_ERROR_CHECK(lb_effect_init(&config));
    lb_effect_force_off();
    lb_wifi_start_factory_reset_monitor();

    if (!config.provisioned) {
        ESP_LOGW(TAG, "No valid NVS configuration; entering SoftAP provisioning mode");
        ESP_ERROR_CHECK(lb_wifi_start_provisioning());
        return;
    }

    esp_err_t wifi_result = lb_wifi_start_station(&config, true);
    if (wifi_result != ESP_OK && wifi_result != ESP_ERR_TIMEOUT) {
        ESP_LOGE(TAG, "Wi-Fi station startup failed: %s", esp_err_to_name(wifi_result));
        return;
    }
    ESP_ERROR_CHECK(lb_udp_start(&config));
    if (wifi_result == ESP_OK) {
        ESP_ERROR_CHECK_WITHOUT_ABORT(lb_ota_confirm_running_image());
    } else {
        ESP_LOGW(TAG, "Wi-Fi not connected after 30 seconds; reconnect remains active");
        xTaskCreate(delayed_ota_confirmation, "lb_ota_self_test", 3072, NULL, 3, NULL);
    }
}

