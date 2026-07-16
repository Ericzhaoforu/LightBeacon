# LightBeacon Protocol v1

LightBeacon uses authenticated UDP on port 40404. All integers are unsigned
and encoded in network byte order. Every datagram is at most 1200 bytes.

## Envelope

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | ASCII magic LBP1 |
| 4 | 1 | protocol version (1) |
| 5 | 1 | message type |
| 6 | 2 | flags, currently zero |
| 8 | 8 | host session ID |
| 16 | 4 | sequence |
| 20 | 8 | sender time in milliseconds |
| 28 | 8 | common effect apply time, or zero |
| 36 | 2 | UTF-8 JSON payload length |
| 38 | N | exact JSON payload bytes |
| 38+N | 32 | HMAC-SHA256 |

The HMAC covers the header and exact payload bytes. Receivers authenticate the
packet before parsing JSON. Senders should use compact JSON; the Python
implementation uses sorted keys for reproducible golden vectors.

## Message types

1. STATUS: node-to-host discovery and telemetry, once per second.
2. HEARTBEAT: host-to-node liveness, once per second.
3. TIME_SYNC: host-to-node time reference, once every two seconds.
4. SET_EFFECT: authenticated effect command.
5. ACK: command acceptance, rejection, or duplicate acknowledgement.
6. OTA_BEGIN: authenticated OTA metadata and one-time download token.

## Session and sequence rules

- A host generates a random 64-bit session ID on every start.
- A node that sees a new authenticated session immediately enters OFF.
- Replay ordering applies only to command messages (SET_EFFECT and OTA_BEGIN).
  Heartbeats and time-sync datagrams do not advance the command replay window
  because UDP can reorder them.
- A sequence below the highest command sequence is rejected.
- A duplicate of the highest command sequence returns the previous ACK without
  applying the command twice.
- A normal effect uses one common apply_at_ms, normally host time + 500 ms.
- OFF has apply_at_ms=0 and is valid even when time synchronization is stale.

## Effect payload

    {"brightness":25,"mode":"BLINK_BLUE","period_ms":1000}

mode is one of OFF, BLINK_RED, BLINK_GREEN, BLINK_BLUE, or SOLID_BLUE.
Blinking periods are 200–10000 ms. Non-blinking effects use a zero period.
Brightness is 1–100; the node applies its local safety cap.

## Status payload

The node reports its ID, MAC, IP, RSSI, firmware version, uptime, effect,
requested and actual brightness, host session, last command sequence, and
state. The session is emitted as a decimal string to avoid JSON number
precision loss.

## OTA

OTA_BEGIN includes job_id, target, version, size, sha256, url, and a one-time
HTTP token. The node sends the token as X-LightBeacon-OTA-Token, verifies the
target/image format, SHA-256 and ESP-IDF app signature, writes the inactive OTA
partition, then reboots. OTA always forces OFF.

