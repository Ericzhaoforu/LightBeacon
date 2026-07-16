#include "lb_ota.h"

#include <stdlib.h>
#include <string.h>

#include "esp_app_desc.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lb_effect.h"
#include "psa/crypto.h"

typedef struct {
    char url[256];
    char token[128];
    char sha256[65];
    char version[64];
} ota_request_t;

static const char *TAG = "lb_ota";
static volatile bool s_in_progress;
static const char *s_state = "idle";

static int hex_value(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

static bool parse_hash(const char *hex, uint8_t output[32])
{
    if (strlen(hex) != 64) return false;
    for (int i = 0; i < 32; ++i) {
        int high = hex_value(hex[i * 2]);
        int low = hex_value(hex[i * 2 + 1]);
        if (high < 0 || low < 0) return false;
        output[i] = (uint8_t)((high << 4) | low);
    }
    return true;
}

static void ota_task(void *argument)
{
    ota_request_t *request = argument;
    esp_http_client_config_t config = {
        .url = request->url,
        .timeout_ms = 10000,
        .keep_alive_enable = true,
        .buffer_size = 4096,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_ota_handle_t ota_handle = 0;
    const esp_partition_t *partition = NULL;
    esp_err_t result = ESP_FAIL;
    uint8_t expected_hash[32];
    uint8_t actual_hash[32];
    size_t actual_hash_length = 0;
    psa_hash_operation_t sha = PSA_HASH_OPERATION_INIT;

    lb_effect_force_off();
    s_state = "downloading";
    if (!client || !parse_hash(request->sha256, expected_hash)) goto cleanup;
    esp_http_client_set_header(client, "X-LightBeacon-OTA-Token", request->token);
    if (esp_http_client_open(client, 0) != ESP_OK) goto cleanup;
    int64_t content_length = esp_http_client_fetch_headers(client);
    if (esp_http_client_get_status_code(client) != 200 || content_length <= 0 || content_length > 8 * 1024 * 1024) {
        goto cleanup;
    }
    partition = esp_ota_get_next_update_partition(NULL);
    if (!partition || esp_ota_begin(partition, OTA_SIZE_UNKNOWN, &ota_handle) != ESP_OK) goto cleanup;
    if (psa_crypto_init() != PSA_SUCCESS ||
        psa_hash_setup(&sha, PSA_ALG_SHA_256) != PSA_SUCCESS) goto cleanup;

    uint8_t *buffer = malloc(4096);
    if (!buffer) goto cleanup;
    int64_t total = 0;
    while (total < content_length) {
        int read = esp_http_client_read(client, (char *)buffer, 4096);
        if (read <= 0) {
            free(buffer);
            goto cleanup;
        }
        if (esp_ota_write(ota_handle, buffer, read) != ESP_OK ||
            psa_hash_update(&sha, buffer, read) != PSA_SUCCESS) {
            free(buffer);
            goto cleanup;
        }
        total += read;
    }
    free(buffer);
    if (total != content_length ||
        psa_hash_finish(&sha, actual_hash, sizeof(actual_hash), &actual_hash_length) != PSA_SUCCESS ||
        actual_hash_length != sizeof(actual_hash) ||
        memcmp(expected_hash, actual_hash, sizeof(actual_hash)) != 0) {
        s_state = "hash_failed";
        goto cleanup;
    }
    s_state = "verifying";
    result = esp_ota_end(ota_handle);
    ota_handle = 0;
    if (result != ESP_OK) {
        s_state = "signature_failed";
        goto cleanup;
    }
    esp_app_desc_t description;
    if (esp_ota_get_partition_description(partition, &description) != ESP_OK ||
        (request->version[0] && strcmp(request->version, description.version) != 0)) {
        s_state = "version_mismatch";
        goto cleanup;
    }
    if (esp_ota_set_boot_partition(partition) != ESP_OK) goto cleanup;
    s_state = "rebooting";
    ESP_LOGI(TAG, "OTA image %s verified; rebooting", description.version);
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();

cleanup:
    if (ota_handle) esp_ota_abort(ota_handle);
    if (client) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
    }
    psa_hash_abort(&sha);
    if (strcmp(s_state, "hash_failed") != 0 && strcmp(s_state, "signature_failed") != 0 &&
        strcmp(s_state, "version_mismatch") != 0) {
        s_state = "failed";
    }
    ESP_LOGE(TAG, "OTA failed in state %s", s_state);
    s_in_progress = false;
    free(request);
    vTaskDelete(NULL);
}

esp_err_t lb_ota_start(const char *url, const char *token, const char *sha256_hex,
                       const char *expected_version)
{
    if (s_in_progress || !url || !token || !sha256_hex || strlen(url) >= 256 ||
        strlen(token) >= 128 || strlen(sha256_hex) != 64 ||
        (expected_version && strlen(expected_version) >= 64)) {
        return ESP_ERR_INVALID_ARG;
    }
    ota_request_t *request = calloc(1, sizeof(*request));
    if (!request) return ESP_ERR_NO_MEM;
    strlcpy(request->url, url, sizeof(request->url));
    strlcpy(request->token, token, sizeof(request->token));
    strlcpy(request->sha256, sha256_hex, sizeof(request->sha256));
    if (expected_version) strlcpy(request->version, expected_version, sizeof(request->version));
    s_in_progress = true;
    s_state = "queued";
    if (xTaskCreate(ota_task, "lb_ota", 8192, request, 5, NULL) != pdPASS) {
        s_in_progress = false;
        free(request);
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

bool lb_ota_in_progress(void)
{
    return s_in_progress;
}

const char *lb_ota_state(void)
{
    return s_state;
}

esp_err_t lb_ota_confirm_running_image(void)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    esp_err_t err = esp_ota_get_state_partition(running, &state);
    if (err == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY) {
        ESP_LOGI(TAG, "Running image self-test passed; cancelling rollback");
        return esp_ota_mark_app_valid_cancel_rollback();
    }
    return err == ESP_ERR_NOT_SUPPORTED ? ESP_OK : err;
}
