#include "lb_protocol.h"

#include <string.h>

#include "psa/crypto.h"

static void put_u16(uint8_t *target, uint16_t value)
{
    target[0] = (uint8_t)(value >> 8);
    target[1] = (uint8_t)value;
}

static void put_u32(uint8_t *target, uint32_t value)
{
    target[0] = (uint8_t)(value >> 24);
    target[1] = (uint8_t)(value >> 16);
    target[2] = (uint8_t)(value >> 8);
    target[3] = (uint8_t)value;
}

static void put_u64(uint8_t *target, uint64_t value)
{
    for (int i = 7; i >= 0; --i) {
        target[i] = (uint8_t)value;
        value >>= 8;
    }
}

static uint16_t get_u16(const uint8_t *source)
{
    return ((uint16_t)source[0] << 8) | source[1];
}

static uint32_t get_u32(const uint8_t *source)
{
    return ((uint32_t)source[0] << 24) | ((uint32_t)source[1] << 16) |
           ((uint32_t)source[2] << 8) | source[3];
}

static uint64_t get_u64(const uint8_t *source)
{
    uint64_t value = 0;
    for (int i = 0; i < 8; ++i) value = (value << 8) | source[i];
    return value;
}

static esp_err_t calculate_hmac(const uint8_t key[32], const uint8_t *data, size_t length,
                                uint8_t output[LB_PROTOCOL_TAG_SIZE])
{
    if (psa_crypto_init() != PSA_SUCCESS) return ESP_FAIL;
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, PSA_KEY_TYPE_HMAC);
    psa_set_key_bits(&attributes, 256);
    psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_SIGN_MESSAGE);
    psa_set_key_algorithm(&attributes, PSA_ALG_HMAC(PSA_ALG_SHA_256));

    psa_key_id_t key_id = 0;
    psa_status_t status = psa_import_key(&attributes, key, 32, &key_id);
    psa_reset_key_attributes(&attributes);
    if (status != PSA_SUCCESS) return ESP_FAIL;

    size_t output_length = 0;
    status = psa_mac_compute(key_id, PSA_ALG_HMAC(PSA_ALG_SHA_256), data, length,
                             output, LB_PROTOCOL_TAG_SIZE, &output_length);
    psa_destroy_key(key_id);
    return status == PSA_SUCCESS && output_length == LB_PROTOCOL_TAG_SIZE ? ESP_OK : ESP_FAIL;
}

esp_err_t lb_protocol_encode(const lb_packet_t *packet, const uint8_t key[32],
                             uint8_t *output, size_t output_capacity, size_t *output_len)
{
    if (!packet || !key || !output || !output_len ||
        packet->payload_len > LB_PROTOCOL_MAX_PAYLOAD ||
        packet->type < LB_MSG_STATUS || packet->type > LB_MSG_OTA_BEGIN) {
        return ESP_ERR_INVALID_ARG;
    }
    size_t body_len = LB_PROTOCOL_HEADER_SIZE + packet->payload_len;
    size_t total_len = body_len + LB_PROTOCOL_TAG_SIZE;
    if (output_capacity < total_len) return ESP_ERR_INVALID_SIZE;
    memcpy(output, "LBP1", 4);
    output[4] = LB_PROTOCOL_VERSION;
    output[5] = (uint8_t)packet->type;
    put_u16(output + 6, packet->flags);
    put_u64(output + 8, packet->session_id);
    put_u32(output + 16, packet->sequence);
    put_u64(output + 20, packet->sent_at_ms);
    put_u64(output + 28, packet->apply_at_ms);
    put_u16(output + 36, (uint16_t)packet->payload_len);
    memcpy(output + LB_PROTOCOL_HEADER_SIZE, packet->payload, packet->payload_len);
    esp_err_t err = calculate_hmac(key, output, body_len, output + body_len);
    if (err != ESP_OK) return err;
    *output_len = total_len;
    return ESP_OK;
}

esp_err_t lb_protocol_decode(const uint8_t *data, size_t data_len, const uint8_t key[32],
                             lb_packet_t *packet)
{
    if (!data || !key || !packet || data_len < LB_PROTOCOL_HEADER_SIZE + LB_PROTOCOL_TAG_SIZE ||
        data_len > LB_PROTOCOL_MAX_PACKET) {
        return ESP_ERR_INVALID_ARG;
    }
    if (memcmp(data, "LBP1", 4) != 0 || data[4] != LB_PROTOCOL_VERSION ||
        data[5] < LB_MSG_STATUS || data[5] > LB_MSG_OTA_BEGIN) {
        return ESP_ERR_INVALID_VERSION;
    }
    uint16_t payload_len = get_u16(data + 36);
    size_t body_len = LB_PROTOCOL_HEADER_SIZE + payload_len;
    if (payload_len > LB_PROTOCOL_MAX_PAYLOAD || body_len + LB_PROTOCOL_TAG_SIZE != data_len) {
        return ESP_ERR_INVALID_SIZE;
    }
    uint8_t expected[LB_PROTOCOL_TAG_SIZE];
    if (calculate_hmac(key, data, body_len, expected) != ESP_OK) return ESP_FAIL;
    uint8_t difference = 0;
    for (size_t i = 0; i < LB_PROTOCOL_TAG_SIZE; ++i) {
        difference |= expected[i] ^ data[body_len + i];
    }
    if (difference != 0) return ESP_ERR_INVALID_CRC;
    memset(packet, 0, sizeof(*packet));
    packet->type = (lb_message_type_t)data[5];
    packet->flags = get_u16(data + 6);
    packet->session_id = get_u64(data + 8);
    packet->sequence = get_u32(data + 16);
    packet->sent_at_ms = get_u64(data + 20);
    packet->apply_at_ms = get_u64(data + 28);
    packet->payload_len = payload_len;
    memcpy(packet->payload, data + LB_PROTOCOL_HEADER_SIZE, payload_len);
    packet->payload[payload_len] = '\0';
    return ESP_OK;
}
