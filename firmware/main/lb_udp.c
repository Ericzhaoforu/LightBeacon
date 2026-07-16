#include "lb_udp.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lb_effect.h"
#include "lb_ota.h"
#include "lb_protocol.h"
#include "lb_wifi.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "sdkconfig.h"

static const char *TAG = "lb_udp";
static lb_config_t s_config;
static uint64_t s_session_id;
static uint32_t s_highest_command_sequence;
static bool s_have_command_sequence;
static bool s_last_ack_accepted;
static char s_last_ack_code[32] = "accepted";
static int64_t s_last_heartbeat_us;
static int64_t s_last_sync_us;
static int64_t s_host_offset_ms;
static char s_state[32] = "online";
static int64_t s_last_decode_warning_us;

static uint64_t local_ms(void)
{
    return (uint64_t)(esp_timer_get_time() / 1000);
}

static esp_err_t send_packet(int socket_fd, const struct sockaddr_in *target, lb_packet_t *packet)
{
    uint8_t buffer[LB_PROTOCOL_MAX_PACKET];
    size_t length = 0;
    esp_err_t err = lb_protocol_encode(packet, s_config.hmac_key, buffer, sizeof(buffer), &length);
    if (err != ESP_OK) return err;
    return sendto(socket_fd, buffer, length, 0, (const struct sockaddr *)target, sizeof(*target)) == (int)length
               ? ESP_OK : ESP_FAIL;
}

static char *json_unformatted(cJSON *root, lb_packet_t *packet)
{
    char *json = cJSON_PrintUnformatted(root);
    if (!json) return NULL;
    size_t length = strlen(json);
    if (length > LB_PROTOCOL_MAX_PAYLOAD) {
        free(json);
        return NULL;
    }
    memcpy(packet->payload, json, length + 1);
    packet->payload_len = length;
    return json;
}

static void send_ack(int socket_fd, const struct sockaddr_in *target, const lb_packet_t *command,
                     bool accepted, const char *code)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "node_id", s_config.node_id);
    cJSON_AddBoolToObject(root, "accepted", accepted);
    cJSON_AddStringToObject(root, "code", code);
    cJSON_AddStringToObject(root, "mode", lb_effect_mode_name(lb_effect_snapshot().mode));
    lb_packet_t response = {
        .type = LB_MSG_ACK,
        .session_id = command->session_id,
        .sequence = command->sequence,
        .sent_at_ms = local_ms() + s_host_offset_ms,
    };
    char *json = json_unformatted(root, &response);
    if (json) send_packet(socket_fd, target, &response);
    free(json);
    cJSON_Delete(root);
}

static bool command_sequence_valid(const lb_packet_t *packet, bool *duplicate)
{
    *duplicate = false;
    if (packet->session_id != s_session_id) {
        s_session_id = packet->session_id;
        s_have_command_sequence = false;
        s_highest_command_sequence = 0;
        lb_effect_force_off();
        strlcpy(s_state, "new_session", sizeof(s_state));
    }
    if (!s_have_command_sequence) {
        s_have_command_sequence = true;
        s_highest_command_sequence = packet->sequence;
        return true;
    }
    if (packet->sequence < s_highest_command_sequence) return false;
    if (packet->sequence == s_highest_command_sequence) {
        *duplicate = true;
        return true;
    }
    s_highest_command_sequence = packet->sequence;
    return true;
}

static void handle_effect(int socket_fd, const struct sockaddr_in *source, const lb_packet_t *packet)
{
    bool duplicate;
    if (!command_sequence_valid(packet, &duplicate)) {
        send_ack(socket_fd, source, packet, false, "stale_sequence");
        return;
    }
    if (duplicate) {
        send_ack(socket_fd, source, packet, s_last_ack_accepted, s_last_ack_code);
        return;
    }
    cJSON *root = cJSON_Parse(packet->payload);
    cJSON *mode_item = root ? cJSON_GetObjectItemCaseSensitive(root, "mode") : NULL;
    cJSON *period_item = root ? cJSON_GetObjectItemCaseSensitive(root, "period_ms") : NULL;
    cJSON *brightness_item = root ? cJSON_GetObjectItemCaseSensitive(root, "brightness") : NULL;
    lb_effect_mode_t mode;
    bool valid = cJSON_IsString(mode_item) && cJSON_IsNumber(period_item) &&
                 cJSON_IsNumber(brightness_item) &&
                 lb_effect_mode_from_name(mode_item->valuestring, &mode);
    uint16_t period = valid ? (uint16_t)period_item->valueint : 0;
    uint8_t brightness = valid ? (uint8_t)brightness_item->valueint : 0;
    if (valid && (brightness < 1 || brightness > 100)) valid = false;
    if (valid && mode >= LB_EFFECT_BLINK_RED && mode <= LB_EFFECT_BLINK_BLUE &&
        (period < 200 || period > 10000)) valid = false;
    const char *code = "accepted";
    if (!valid) {
        code = "invalid_effect";
    } else if (mode != LB_EFFECT_OFF && esp_timer_get_time() - s_last_sync_us > 5000000) {
        valid = false;
        code = "time_unsynchronized";
    } else {
        int64_t apply_local_us = packet->apply_at_ms == 0 ? 0 :
                                 ((int64_t)packet->apply_at_ms - s_host_offset_ms) * 1000;
        valid = lb_effect_schedule(mode, period, brightness, apply_local_us) == ESP_OK;
        if (!valid) code = "effect_error";
        if (valid) strlcpy(s_state, "online", sizeof(s_state));
    }
    s_last_ack_accepted = valid;
    strlcpy(s_last_ack_code, code, sizeof(s_last_ack_code));
    send_ack(socket_fd, source, packet, valid, code);
    cJSON_Delete(root);
}

static void handle_ota(int socket_fd, const struct sockaddr_in *source, const lb_packet_t *packet)
{
    bool duplicate;
    if (!command_sequence_valid(packet, &duplicate)) {
        send_ack(socket_fd, source, packet, false, "stale_sequence");
        return;
    }
    if (duplicate) {
        send_ack(socket_fd, source, packet, s_last_ack_accepted, s_last_ack_code);
        return;
    }
    cJSON *root = cJSON_Parse(packet->payload);
    cJSON *url = root ? cJSON_GetObjectItemCaseSensitive(root, "url") : NULL;
    cJSON *token = root ? cJSON_GetObjectItemCaseSensitive(root, "token") : NULL;
    cJSON *sha = root ? cJSON_GetObjectItemCaseSensitive(root, "sha256") : NULL;
    cJSON *version = root ? cJSON_GetObjectItemCaseSensitive(root, "version") : NULL;
    bool valid = cJSON_IsString(url) && cJSON_IsString(token) && cJSON_IsString(sha) &&
                 cJSON_IsString(version) && !lb_ota_in_progress() &&
                 lb_ota_start(url->valuestring, token->valuestring, sha->valuestring,
                              version->valuestring) == ESP_OK;
    s_last_ack_accepted = valid;
    strlcpy(s_last_ack_code, valid ? "accepted" : "ota_rejected", sizeof(s_last_ack_code));
    if (valid) strlcpy(s_state, "ota", sizeof(s_state));
    send_ack(socket_fd, source, packet, valid, s_last_ack_code);
    cJSON_Delete(root);
}

static void handle_packet(int socket_fd, const struct sockaddr_in *source, const lb_packet_t *packet)
{
    int64_t now_us = esp_timer_get_time();
    switch (packet->type) {
        case LB_MSG_HEARTBEAT:
            if (packet->session_id != s_session_id) {
                s_session_id = packet->session_id;
                s_have_command_sequence = false;
                lb_effect_force_off();
                strlcpy(s_state, "new_session", sizeof(s_state));
                ESP_LOGI(TAG, "Accepted new host session %llu",
                         (unsigned long long)s_session_id);
            }
            s_last_heartbeat_us = now_us;
            if (strcmp(s_state, "failsafe") == 0) strlcpy(s_state, "online", sizeof(s_state));
            break;
        case LB_MSG_TIME_SYNC:
            if (packet->session_id != s_session_id) {
                s_session_id = packet->session_id;
                s_have_command_sequence = false;
                lb_effect_force_off();
            }
            s_host_offset_ms = (int64_t)packet->sent_at_ms - (int64_t)local_ms();
            s_last_sync_us = now_us;
            break;
        case LB_MSG_SET_EFFECT:
            handle_effect(socket_fd, source, packet);
            break;
        case LB_MSG_OTA_BEGIN:
            handle_ota(socket_fd, source, packet);
            break;
        default:
            break;
    }
}

static void send_status(int socket_fd, const struct sockaddr_in *broadcast)
{
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char mac_string[18];
    snprintf(mac_string, sizeof(mac_string), "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    char ip[16];
    lb_wifi_ip_string(ip, sizeof(ip));
    lb_effect_snapshot_t effect = lb_effect_snapshot();
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "node_id", s_config.node_id);
    cJSON_AddStringToObject(root, "mac", mac_string);
    cJSON_AddStringToObject(root, "ip", ip);
    cJSON_AddNumberToObject(root, "rssi", lb_wifi_rssi());
    cJSON_AddStringToObject(root, "firmware_version", esp_app_get_description()->version);
    cJSON_AddNumberToObject(root, "uptime_ms", local_ms());
    cJSON_AddStringToObject(root, "mode", lb_effect_mode_name(effect.mode));
    cJSON_AddNumberToObject(root, "period_ms", effect.period_ms);
    cJSON_AddNumberToObject(root, "requested_brightness", effect.requested_brightness);
    cJSON_AddNumberToObject(root, "actual_brightness", effect.actual_brightness);
    char session[24];
    snprintf(session, sizeof(session), "%llu", (unsigned long long)s_session_id);
    cJSON_AddStringToObject(root, "session_id", session);
    cJSON_AddNumberToObject(root, "last_sequence", s_have_command_sequence ? s_highest_command_sequence : 0);
    cJSON_AddStringToObject(root, "state", lb_ota_in_progress() ? lb_ota_state() : s_state);
    lb_packet_t packet = {
        .type = LB_MSG_STATUS,
        .session_id = s_session_id,
        .sequence = s_have_command_sequence ? s_highest_command_sequence : 0,
        .sent_at_ms = local_ms() + s_host_offset_ms,
    };
    char *json = json_unformatted(root, &packet);
    if (json) send_packet(socket_fd, broadcast, &packet);
    free(json);
    cJSON_Delete(root);
}

static void udp_task(void *argument)
{
    int socket_fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (socket_fd < 0) vTaskDelete(NULL);
    int enabled = 1;
    setsockopt(socket_fd, SOL_SOCKET, SO_BROADCAST, &enabled, sizeof(enabled));
    struct timeval timeout = {.tv_sec = 0, .tv_usec = 200000};
    setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_in local = {
        .sin_family = AF_INET,
        .sin_port = htons(CONFIG_LB_UDP_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(socket_fd, (struct sockaddr *)&local, sizeof(local)) != 0) {
        ESP_LOGE(TAG, "UDP bind failed: errno=%d", errno);
        close(socket_fd);
        vTaskDelete(NULL);
    }
    struct sockaddr_in broadcast = {
        .sin_family = AF_INET,
        .sin_port = htons(CONFIG_LB_UDP_PORT),
        .sin_addr.s_addr = inet_addr("255.255.255.255"),
    };
    uint8_t buffer[LB_PROTOCOL_MAX_PACKET];
    int64_t last_status_us = 0;
    while (true) {
        struct sockaddr_in source;
        socklen_t source_len = sizeof(source);
        int received = recvfrom(socket_fd, buffer, sizeof(buffer), 0,
                                (struct sockaddr *)&source, &source_len);
        if (received > 0) {
            lb_packet_t packet;
            esp_err_t decode_result = lb_protocol_decode(buffer, received, s_config.hmac_key, &packet);
            if (decode_result == ESP_OK) {
                handle_packet(socket_fd, &source, &packet);
            } else {
                int64_t warning_now_us = esp_timer_get_time();
                if (warning_now_us - s_last_decode_warning_us >= 1000000) {
                    ESP_LOGW(TAG, "Rejected UDP packet from %s:%u len=%d: %s",
                             inet_ntoa(source.sin_addr), ntohs(source.sin_port), received,
                             esp_err_to_name(decode_result));
                    s_last_decode_warning_us = warning_now_us;
                }
            }
        }
        int64_t now_us = esp_timer_get_time();
        if (!lb_wifi_is_connected()) {
            lb_effect_force_off();
            strlcpy(s_state, "wifi_disconnected", sizeof(s_state));
        } else if (s_last_heartbeat_us && now_us - s_last_heartbeat_us > CONFIG_LB_FAILSAFE_MS * 1000LL) {
            lb_effect_force_off();
            strlcpy(s_state, "failsafe", sizeof(s_state));
        }
        if (now_us - last_status_us >= 1000000) {
            send_status(socket_fd, &broadcast);
            last_status_us = now_us;
        }
    }
}

esp_err_t lb_udp_start(const lb_config_t *config)
{
    if (!config || !config->provisioned) return ESP_ERR_INVALID_ARG;
    s_config = *config;
    s_last_heartbeat_us = esp_timer_get_time();
    s_last_sync_us = 0;
    s_host_offset_ms = 0;
    lb_effect_force_off();
    return xTaskCreate(udp_task, "lb_udp", 8192, NULL, 7, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
