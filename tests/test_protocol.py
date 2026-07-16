import json
from pathlib import Path

import pytest

from lightbeacon.protocol import (
    EffectMode,
    MessageType,
    Packet,
    ProtocolError,
    ReplayWindow,
    decode_packet,
    encode_packet,
    validate_effect,
)


def test_golden_vectors() -> None:
    document = json.loads(Path("protocol/golden_vectors.json").read_text(encoding="utf-8"))
    for vector in document["vectors"]:
        packet = Packet(
            MessageType[vector["message_type"]],
            vector["session_id"],
            vector["sequence"],
            vector["sent_at_ms"],
            vector["apply_at_ms"],
            vector["payload"],
        )
        encoded = encode_packet(packet, bytes.fromhex(vector["key_hex"]))
        assert encoded.hex() == vector["packet_hex"]
        assert decode_packet(encoded, bytes.fromhex(vector["key_hex"])) == packet


def test_tampering_is_rejected() -> None:
    key = bytes(range(32))
    encoded = bytearray(
        encode_packet(Packet(MessageType.HEARTBEAT, 1, 2, 3, 0, {}), key)
    )
    encoded[20] ^= 1
    with pytest.raises(ProtocolError, match="HMAC"):
        decode_packet(bytes(encoded), key)


def test_replay_window() -> None:
    window = ReplayWindow()
    assert window.observe(10, 4) == "new_session"
    assert window.observe(10, 4) == "duplicate"
    assert window.observe(10, 3) == "stale"
    assert window.observe(10, 5) == "new"
    assert window.observe(11, 1) == "new_session"


@pytest.mark.parametrize(
    ("mode", "period", "brightness"),
    [
        ("OFF", 0, 1),
        ("SOLID_BLUE", 0, 100),
        ("BLINK_RED", 200, 25),
        ("BLINK_GREEN", 10000, 25),
    ],
)
def test_valid_effects(mode: str, period: int, brightness: int) -> None:
    assert validate_effect(mode, period, brightness) == EffectMode(mode)


def test_invalid_blink_period() -> None:
    with pytest.raises(ProtocolError):
        validate_effect("BLINK_BLUE", 199, 25)

