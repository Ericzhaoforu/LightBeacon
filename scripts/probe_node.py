"""Send a minimal authenticated command sequence directly to one node."""

from __future__ import annotations

import argparse
import secrets
import socket
from dataclasses import replace

from lightbeacon.config import Settings
from lightbeacon.protocol import MessageType, Packet, decode_packet, encode_packet, now_ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("address")
    parser.add_argument("--port", type=int, default=40404)
    args = parser.parse_args()
    settings = Settings.from_env()
    session = secrets.randbits(64) or 1
    packets = [
        Packet(MessageType.HEARTBEAT, session, 1, now_ms(), 0, {"host_session": session}),
        Packet(MessageType.TIME_SYNC, session, 2, now_ms(), 0, {"host_time_ms": now_ms()}),
        Packet(
            MessageType.SET_EFFECT,
            session,
            3,
            now_ms(),
            0,
            {"mode": "OFF", "period_ms": 0, "brightness": 1, "reason": "probe"},
        ),
    ]
    target = (args.address, args.port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(2.0)
        for packet in packets:
            client.sendto(
                encode_packet(replace(packet, sent_at_ms=now_ms()), settings.hmac_key),
                target,
            )
        try:
            data, source = client.recvfrom(1200)
        except TimeoutError:
            print("No ACK received")
            return 1
    response = decode_packet(data, settings.hmac_key)
    print(f"ACK from {source[0]}:{source[1]}: {response.payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
