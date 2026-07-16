from __future__ import annotations

import hashlib
import hmac
import json
import struct
import time
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any, Mapping

MAGIC = b"LBP1"
VERSION = 1
MAX_PACKET_SIZE = 1200
TAG_SIZE = 32

# magic, version, type, flags, session, sequence, sent_at, apply_at, payload length
HEADER = struct.Struct("!4sBBHQIQQH")


class ProtocolError(ValueError):
    """Raised when an incoming LightBeacon packet is invalid."""


class MessageType(IntEnum):
    STATUS = 1
    HEARTBEAT = 2
    TIME_SYNC = 3
    SET_EFFECT = 4
    ACK = 5
    OTA_BEGIN = 6


class EffectMode(StrEnum):
    OFF = "OFF"
    BLINK_RED = "BLINK_RED"
    BLINK_GREEN = "BLINK_GREEN"
    BLINK_BLUE = "BLINK_BLUE"
    SOLID_BLUE = "SOLID_BLUE"

    @property
    def is_blinking(self) -> bool:
        return self.name.startswith("BLINK_")


@dataclass(frozen=True, slots=True)
class Packet:
    message_type: MessageType
    session_id: int
    sequence: int
    sent_at_ms: int
    apply_at_ms: int
    payload: dict[str, Any]
    flags: int = 0


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def canonical_json(payload: Mapping[str, Any] | None) -> bytes:
    return json.dumps(
        dict(payload or {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def encode_packet(packet: Packet, key: bytes) -> bytes:
    if len(key) < 16:
        raise ProtocolError("HMAC key must be at least 16 bytes")
    if not 0 <= packet.session_id <= 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("session_id is out of range")
    if not 0 <= packet.sequence <= 0xFFFFFFFF:
        raise ProtocolError("sequence is out of range")
    payload = canonical_json(packet.payload)
    header = HEADER.pack(
        MAGIC,
        VERSION,
        int(packet.message_type),
        packet.flags,
        packet.session_id,
        packet.sequence,
        packet.sent_at_ms,
        packet.apply_at_ms,
        len(payload),
    )
    body = header + payload
    result = body + hmac.digest(key, body, "sha256")
    if len(result) > MAX_PACKET_SIZE:
        raise ProtocolError(f"packet is {len(result)} bytes; maximum is {MAX_PACKET_SIZE}")
    return result


def decode_packet(data: bytes, key: bytes, *, verify_time: bool = False) -> Packet:
    if len(data) < HEADER.size + TAG_SIZE:
        raise ProtocolError("packet is truncated")
    if len(data) > MAX_PACKET_SIZE:
        raise ProtocolError("packet exceeds maximum size")
    body, received_tag = data[:-TAG_SIZE], data[-TAG_SIZE:]
    expected_tag = hmac.digest(key, body, "sha256")
    if not hmac.compare_digest(received_tag, expected_tag):
        raise ProtocolError("invalid HMAC")
    try:
        (
            magic,
            version,
            message_type,
            flags,
            session_id,
            sequence,
            sent_at_ms,
            apply_at_ms,
            payload_len,
        ) = HEADER.unpack(body[: HEADER.size])
    except struct.error as exc:
        raise ProtocolError("invalid header") from exc
    if magic != MAGIC:
        raise ProtocolError("invalid magic")
    if version != VERSION:
        raise ProtocolError(f"unsupported protocol version {version}")
    if HEADER.size + payload_len != len(body):
        raise ProtocolError("payload length does not match packet")
    try:
        kind = MessageType(message_type)
    except ValueError as exc:
        raise ProtocolError(f"unknown message type {message_type}") from exc
    try:
        raw = body[HEADER.size:]
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("payload is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be a JSON object")
    if verify_time and abs(now_ms() - sent_at_ms) > 30_000:
        raise ProtocolError("packet timestamp is outside the acceptance window")
    return Packet(kind, session_id, sequence, sent_at_ms, apply_at_ms, payload, flags)


def packet_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_effect(mode: str, period_ms: int, brightness: int) -> EffectMode:
    try:
        effect = EffectMode(mode)
    except ValueError as exc:
        raise ProtocolError(f"invalid effect mode: {mode}") from exc
    if not 1 <= brightness <= 100:
        raise ProtocolError("brightness must be between 1 and 100")
    if effect.is_blinking and not 200 <= period_ms <= 10_000:
        raise ProtocolError("blinking period must be between 200 and 10000 ms")
    if not effect.is_blinking and period_ms != 0:
        raise ProtocolError("non-blinking effects must use period_ms=0")
    return effect


class ReplayWindow:
    """Tracks the latest sequence in one host session."""

    def __init__(self) -> None:
        self.session_id: int | None = None
        self.highest_sequence = -1

    def observe(self, session_id: int, sequence: int) -> str:
        if self.session_id != session_id:
            self.session_id = session_id
            self.highest_sequence = sequence
            return "new_session"
        if sequence < self.highest_sequence:
            return "stale"
        if sequence == self.highest_sequence:
            return "duplicate"
        self.highest_sequence = sequence
        return "new"

