#include "lb_config.h"

#include <ctype.h>
#include <string.h>

#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#define LB_NVS_NAMESPACE "lightbeacon"

esp_err_t lb_config_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    return err;
}

static void set_defaults(lb_config_t *config)
{
    memset(config, 0, sizeof(*config));
    config->side_led_count = CONFIG_LB_SIDE_LED_COUNT;
    config->top_led_count = CONFIG_LB_TOP_LED_COUNT;
    config->brightness_cap = CONFIG_LB_BRIGHTNESS_CAP;
}

esp_err_t lb_config_load(lb_config_t *config)
{
    set_defaults(config);
    nvs_handle_t handle;
    esp_err_t err = nvs_open(LB_NVS_NAMESPACE, NVS_READONLY, &handle);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    if (err != ESP_OK) {
        return err;
    }
    uint8_t provisioned = 0;
    size_t node_len = sizeof(config->node_id);
    size_t ssid_len = sizeof(config->ssid);
    size_t password_len = sizeof(config->wifi_password);
    size_t key_len = sizeof(config->hmac_key);
    nvs_get_u8(handle, "provisioned", &provisioned);
    nvs_get_str(handle, "node_id", config->node_id, &node_len);
    nvs_get_str(handle, "ssid", config->ssid, &ssid_len);
    nvs_get_str(handle, "wifi_pass", config->wifi_password, &password_len);
    nvs_get_blob(handle, "hmac_key", config->hmac_key, &key_len);
    nvs_get_u16(handle, "side_count", &config->side_led_count);
    nvs_get_u16(handle, "top_count", &config->top_led_count);
    nvs_get_u8(handle, "bright_cap", &config->brightness_cap);
    nvs_close(handle);
    config->provisioned = provisioned == 1 && key_len == LB_HMAC_KEY_SIZE &&
                          lb_config_valid_node_id(config->node_id) && config->ssid[0] != '\0';
    return ESP_OK;
}

esp_err_t lb_config_save(const lb_config_t *config)
{
    if (!lb_config_valid_node_id(config->node_id) || config->ssid[0] == '\0' ||
        config->side_led_count == 0 || config->top_led_count == 0 ||
        config->brightness_cap < 1 || config->brightness_cap > 100) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle;
    esp_err_t err = nvs_open(LB_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_set_str(handle, "node_id", config->node_id);
    if (err == ESP_OK) err = nvs_set_str(handle, "ssid", config->ssid);
    if (err == ESP_OK) err = nvs_set_str(handle, "wifi_pass", config->wifi_password);
    if (err == ESP_OK) err = nvs_set_blob(handle, "hmac_key", config->hmac_key, LB_HMAC_KEY_SIZE);
    if (err == ESP_OK) err = nvs_set_u16(handle, "side_count", config->side_led_count);
    if (err == ESP_OK) err = nvs_set_u16(handle, "top_count", config->top_led_count);
    if (err == ESP_OK) err = nvs_set_u8(handle, "bright_cap", config->brightness_cap);
    if (err == ESP_OK) err = nvs_set_u8(handle, "provisioned", 1);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t lb_config_erase(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(LB_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_erase_all(handle);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    return err;
}

bool lb_config_valid_node_id(const char *node_id)
{
    size_t length = strlen(node_id);
    if (length < 1 || length > LB_NODE_ID_MAX) return false;
    for (size_t i = 0; i < length; ++i) {
        unsigned char value = (unsigned char)node_id[i];
        if (!(isalnum(value) || value == '_' || value == '-')) return false;
    }
    return true;
}

static int hex_value(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    value = (char)tolower((unsigned char)value);
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    return -1;
}

bool lb_config_hex_to_key(const char *hex, uint8_t key[LB_HMAC_KEY_SIZE])
{
    if (strlen(hex) != LB_HMAC_KEY_SIZE * 2) return false;
    for (size_t i = 0; i < LB_HMAC_KEY_SIZE; ++i) {
        int high = hex_value(hex[i * 2]);
        int low = hex_value(hex[i * 2 + 1]);
        if (high < 0 || low < 0) return false;
        key[i] = (uint8_t)((high << 4) | low);
    }
    return true;
}

