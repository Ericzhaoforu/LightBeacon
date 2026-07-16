"""Read ESP32 boot logs without depending on the Windows console code page."""

from __future__ import annotations

import argparse
import sys
import time

import serial


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args()

    with serial.Serial(args.port, 115200, timeout=0.2) as device:
        if not args.no_reset:
            # Keep GPIO0 high (DTR inactive), pulse EN low through RTS, then release.
            device.dtr = False
            device.rts = True
            time.sleep(0.1)
            device.rts = False
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            data = device.read(device.in_waiting or 1)
            if data:
                sys.stdout.write(data.decode("utf-8", errors="replace"))
                sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
