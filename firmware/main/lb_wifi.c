#include "lb_wifi.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define CONNECTED_BIT BIT0
#define RESET_GPIO GPIO_NUM_0

static const char *TAG = "lb_wifi";
static EventGroupHandle_t s_events;
static esp_netif_t *s_station_netif;
static httpd_handle_t s_http_server;

static const char PROVISIONING_HTML[] =
    "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
    "<title>LightBeacon 配网</title><style>body{font-family:system-ui;background:#08111e;color:#eef5ff;max-width:520px;"
    "margin:40px auto;padding:20px}form{display:grid;gap:14px;background:#101e31;padding:24px;border-radius:14px}"
    "label{display:grid;gap:6px}input{padding:10px;border-radius:7px;border:1px solid #38506d;background:#07111d;color:white}"
    "button{padding:12px;background:#52d5ff;border:0;border-radius:8px;font-weight:700}</style>"
    "<h1>LightBeacon 节点配置</h1><form id='f'>"
    "<label>节点 ID<input name='node_id' pattern='[A-Za-z0-9_-]{1,32}' required></label>"
    "<label>现场 Wi-Fi SSID<input name='ssid' maxlength='32' required></label>"
    "<label>Wi-Fi 密码<input name='wifi_password' type='password' maxlength='64'></label>"
    "<label>HMAC 密钥（64 位十六进制）<input name='hmac_key' minlength='64' maxlength='64' required></label>"
    "<label>侧带灯珠数<input name='side_led_count' type='number' min='1' max='1024' value='288'></label>"
    "<label>顶部灯珠数<input name='top_led_count' type='number' min='1' max='256' value='64'></label>"
    "<label>亮度安全上限 %<input name='brightness_cap' type='number' min='1' max='100' value='25'></label>"
    "<button>保存并重启</button><p id='s'></p></form><script>f.onsubmit=async(e)=>{e.preventDefault();"
    "const x=Object.fromEntries(new FormData(f));for(const k of ['side_led_count','top_led_count','brightness_cap'])x[k]=+x[k];"
    "const r=await fetch('/configure',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(x)});"
    "s.textContent=await r.text()}</script></html>";

static void event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_events, CONNECTED_BIT);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_events, CONNECTED_BIT);
    }
}

static esp_err_t initialize_wifi(void)
{
    if (!s_events) s_events = xEventGroupCreate();
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init failed");
    esp_err_t loop_result = esp_event_loop_create_default();
    if (loop_result != ESP_OK && loop_result != ESP_ERR_INVALID_STATE) return loop_result;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init), TAG, "Wi-Fi init failed");
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &event_handler, NULL));
    return ESP_OK;
}

esp_err_t lb_wifi_start_station(const lb_config_t *config, bool wait_for_ip)
{
    ESP_RETURN_ON_ERROR(initialize_wifi(), TAG, "Wi-Fi initialization failed");
    s_station_netif = esp_netif_create_default_wifi_sta();
    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, config->ssid, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, config->wifi_password, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = config->wifi_password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    wifi_config.sta.pmf_cfg.capable = true;
    wifi_config.sta.pmf_cfg.required = false;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "set station mode failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &wifi_config), TAG, "set station config failed");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "start station failed");
    ESP_RETURN_ON_ERROR(esp_wifi_connect(), TAG, "connect failed");
    if (wait_for_ip) {
        EventBits_t bits = xEventGroupWaitBits(s_events, CONNECTED_BIT, pdFALSE, pdTRUE, pdMS_TO_TICKS(30000));
        if (!(bits & CONNECTED_BIT)) return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}

static esp_err_t root_handler(httpd_req_t *request)
{
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    return httpd_resp_send(request, PROVISIONING_HTML, HTTPD_RESP_USE_STRLEN);
}

static bool json_string(cJSON *root, const char *name, char *target, size_t capacity)
{
    cJSON *item = cJSON_GetObjectItemCaseSensitive(root, name);
    if (!cJSON_IsString(item) || !item->valuestring || strlen(item->valuestring) >= capacity) return false;
    strlcpy(target, item->valuestring, capacity);
    return true;
}

static esp_err_t configure_handler(httpd_req_t *request)
{
    if (request->content_len <= 0 || request->content_len > 1024) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "invalid body size");
    }
    char *body = calloc(1, request->content_len + 1);
    if (!body) return httpd_resp_send_500(request);
    int received = httpd_req_recv(request, body, request->content_len);
    if (received <= 0) {
        free(body);
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "body read failed");
    }
    cJSON *root = cJSON_Parse(body);
    free(body);
    lb_config_t config = {0};
    cJSON *side = root ? cJSON_GetObjectItemCaseSensitive(root, "side_led_count") : NULL;
    cJSON *top = root ? cJSON_GetObjectItemCaseSensitive(root, "top_led_count") : NULL;
    cJSON *cap = root ? cJSON_GetObjectItemCaseSensitive(root, "brightness_cap") : NULL;
    char key_hex[65] = {0};
    bool valid = root && json_string(root, "node_id", config.node_id, sizeof(config.node_id)) &&
                 json_string(root, "ssid", config.ssid, sizeof(config.ssid)) &&
                 json_string(root, "wifi_password", config.wifi_password, sizeof(config.wifi_password)) &&
                 json_string(root, "hmac_key", key_hex, sizeof(key_hex)) &&
                 cJSON_IsNumber(side) && cJSON_IsNumber(top) && cJSON_IsNumber(cap) &&
                 lb_config_valid_node_id(config.node_id) && lb_config_hex_to_key(key_hex, config.hmac_key);
    if (valid) {
        config.side_led_count = (uint16_t)side->valueint;
        config.top_led_count = (uint16_t)top->valueint;
        config.brightness_cap = (uint8_t)cap->valueint;
        valid = config.side_led_count >= 1 && config.side_led_count <= 1024 &&
                config.top_led_count >= 1 && config.top_led_count <= 256 &&
                config.brightness_cap >= 1 && config.brightness_cap <= 100 &&
                lb_config_save(&config) == ESP_OK;
    }
    cJSON_Delete(root);
    if (!valid) return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "invalid configuration");
    httpd_resp_sendstr(request, "配置已保存，节点即将重启");
    vTaskDelay(pdMS_TO_TICKS(800));
    esp_restart();
    return ESP_OK;
}

esp_err_t lb_wifi_start_provisioning(void)
{
    ESP_RETURN_ON_ERROR(initialize_wifi(), TAG, "Wi-Fi initialization failed");
    esp_netif_create_default_wifi_ap();
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    wifi_config_t ap = {0};
    snprintf((char *)ap.ap.ssid, sizeof(ap.ap.ssid), "LightBeacon-%02X%02X%02X", mac[3], mac[4], mac[5]);
    strlcpy((char *)ap.ap.password, CONFIG_LB_PROVISIONING_PASSWORD, sizeof(ap.ap.password));
    ap.ap.ssid_len = strlen((char *)ap.ap.ssid);
    ap.ap.max_connection = 4;
    ap.ap.authmode = strlen(CONFIG_LB_PROVISIONING_PASSWORD) >= 8 ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_AP), TAG, "set AP mode failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &ap), TAG, "set AP config failed");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "start AP failed");
    httpd_config_t http_config = HTTPD_DEFAULT_CONFIG();
    ESP_RETURN_ON_ERROR(httpd_start(&s_http_server, &http_config), TAG, "HTTP server failed");
    httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = root_handler};
    httpd_uri_t configure = {.uri = "/configure", .method = HTTP_POST, .handler = configure_handler};
    httpd_register_uri_handler(s_http_server, &root);
    httpd_register_uri_handler(s_http_server, &configure);
    ESP_LOGI(TAG, "Provisioning AP ready: %s, open http://192.168.4.1", ap.ap.ssid);
    return ESP_OK;
}

bool lb_wifi_is_connected(void)
{
    return s_events && (xEventGroupGetBits(s_events) & CONNECTED_BIT);
}

int lb_wifi_rssi(void)
{
    wifi_ap_record_t record;
    return esp_wifi_sta_get_ap_info(&record) == ESP_OK ? record.rssi : -127;
}

void lb_wifi_ip_string(char *buffer, size_t capacity)
{
    esp_netif_ip_info_t info;
    if (s_station_netif && esp_netif_get_ip_info(s_station_netif, &info) == ESP_OK) {
        snprintf(buffer, capacity, IPSTR, IP2STR(&info.ip));
    } else {
        strlcpy(buffer, "0.0.0.0", capacity);
    }
}

static void factory_reset_task(void *argument)
{
    gpio_config_t config = {
        .pin_bit_mask = 1ULL << RESET_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&config);
    int held_ms = 0;
    while (true) {
        if (gpio_get_level(RESET_GPIO) == 0) {
            held_ms += 100;
            if (held_ms >= 5000) {
                ESP_LOGW(TAG, "BOOT held for 5 seconds; erasing LightBeacon configuration");
                lb_config_erase();
                vTaskDelay(pdMS_TO_TICKS(300));
                esp_restart();
            }
        } else {
            held_ms = 0;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void lb_wifi_start_factory_reset_monitor(void)
{
    xTaskCreate(factory_reset_task, "lb_factory_reset", 2048, NULL, 2, NULL);
}
