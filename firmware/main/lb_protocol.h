#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#define LB_PROTOCOL_VERSION 1
#define LB_PROTOCOL_MAX_PACKET 1200
#define LB_PROTOCOL_HEADER_SIZE 38
#define LB_PROTOCOL_TAG_SIZE 32
#define LB_PROTOCOL_MAX_PAYLOAD (LB_PROTOCOL_MAX_PACKET - LB_PROTOCOL_HEADER_SIZE - LB_PROTOCOL_TAG_SIZE)

typedef enum {
    LB_MSG_STATUS = 1,
    LB_MSG_HEARTBEAT = 2,
    LB_MSG_TIME_SYNC = 3,
    LB_MSG_SET_EFFECT = 4,
    LB_MSG_ACK = 5,
    LB_MSG_OTA_BEGIN = 6,
} lb_message_type_t;

typedef struct {
    lb_message_type_t type;
    uint16_t flags;
    uint64_t session_id;
    uint32_t sequence;
    uint64_t sent_at_ms;
    uint64_t apply_at_ms;
    size_t payload_len;
    char payload[LB_PROTOCOL_MAX_PAYLOAD + 1];
} lb_packet_t;

esp_err_t lb_protocol_encode(const lb_packet_t *packet, const uint8_t key[32],
                             uint8_t *output, size_t output_capacity, size_t *output_len);
esp_err_t lb_protocol_decode(const uint8_t *data, size_t data_len, const uint8_t key[32],
                             lb_packet_t *packet);

