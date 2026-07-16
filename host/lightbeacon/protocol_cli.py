from __future__ import annotations

import argparse
import json
from pathlib import Path

from .protocol import decode_packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode and authenticate a LightBeacon packet")
    parser.add_argument("packet", help="hex packet or path to a binary packet")
    parser.add_argument("--key-hex", required=True)
    args = parser.parse_args()
    source = Path(args.packet)
    data = source.read_bytes() if source.exists() else bytes.fromhex(args.packet)
    packet = decode_packet(data, bytes.fromhex(args.key_hex))
    print(
        json.dumps(
            {
                "message_type": packet.message_type.name,
                "session_id": packet.session_id,
                "sequence": packet.sequence,
                "sent_at_ms": packet.sent_at_ms,
                "apply_at_ms": packet.apply_at_ms,
                "flags": packet.flags,
                "payload": packet.payload,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

