from __future__ import annotations

import argparse
import asyncio
import os
import random
import signal
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import _load_dotenv
from .protocol import (
    EffectMode,
    MessageType,
    Packet,
    ProtocolError,
    ReplayWindow,
    decode_packet,
    encode_packet,
    now_ms,
    validate_effect,
)


@dataclass(slots=True)
class SimulatorOptions:
    host: str
    port: int
    key: bytes
    packet_loss: float
    jitter_ms: int
    brightness_cap: int = 25


class SimulatedNode(asyncio.DatagramProtocol):
    def __init__(self, index: int, options: SimulatorOptions, node_id: str | None = None) -> None:
        self.index = index
        self.options = options
        self.node_id = node_id or f"LB-{index + 1:03d}"
        self.mac = f"02:4C:42:00:{index // 256:02X}:{index % 256:02X}"
        self.transport: asyncio.DatagramTransport | None = None
        self.replay = ReplayWindow()
        self.mode = EffectMode.OFF
        self.period_ms = 0
        self.requested_brightness = 1
        self.actual_brightness = 0
        self.last_heartbeat = time.monotonic()
        self.last_time_sync = 0.0
        self.host_offset_ms = 0
        self.started = time.monotonic()
        self.state = "online"
        self.firmware_version = "sim-0.1.0"
        self.last_ack: dict[int, Packet] = {}
        self.tasks: list[asyncio.Task[None]] = []

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        self.tasks = [
            asyncio.create_task(self._status_loop()),
            asyncio.create_task(self._failsafe_loop()),
        ]

    def connection_lost(self, exc: Exception | None) -> None:
        for task in self.tasks:
            task.cancel()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if random.random() < self.options.packet_loss:
            return
        asyncio.create_task(self._handle(data))

    async def _handle(self, data: bytes) -> None:
        if self.options.jitter_ms:
            await asyncio.sleep(random.uniform(0, self.options.jitter_ms) / 1000)
        try:
            packet = decode_packet(data, self.options.key)
        except ProtocolError:
            return
        if packet.message_type is MessageType.HEARTBEAT:
            if self.replay.session_id != packet.session_id:
                self.replay.session_id = packet.session_id
                self.replay.highest_sequence = -1
                self._apply_off("new_session")
            self.last_heartbeat = time.monotonic()
            if self.state == "failsafe":
                self.state = "online"
            return
        if packet.message_type is MessageType.TIME_SYNC:
            if self.replay.session_id not in (None, packet.session_id):
                self.replay.session_id = packet.session_id
                self.replay.highest_sequence = -1
                self._apply_off("new_session")
            self.host_offset_ms = packet.sent_at_ms - now_ms()
            self.last_time_sync = time.monotonic()
            return
        if packet.message_type not in (MessageType.SET_EFFECT, MessageType.OTA_BEGIN):
            return
        observed = self.replay.observe(packet.session_id, packet.sequence)
        if observed == "new_session":
            self._apply_off("new_session")
        if observed == "stale":
            await self._ack(packet, False, "stale_sequence")
            return
        if observed == "duplicate":
            previous = self.last_ack.get(packet.sequence)
            if previous:
                await self._send(previous)
            return
        if packet.message_type is MessageType.OTA_BEGIN:
            self._apply_off("ota")
            self.state = "ota"
            await self._ack(packet, True, "accepted")
            asyncio.create_task(self._finish_ota(str(packet.payload.get("version", "unknown"))))
            return
        try:
            mode = validate_effect(
                str(packet.payload.get("mode")),
                int(packet.payload.get("period_ms", 0)),
                int(packet.payload.get("brightness", 1)),
            )
        except (ProtocolError, TypeError, ValueError):
            await self._ack(packet, False, "invalid_effect")
            return
        if mode is not EffectMode.OFF and time.monotonic() - self.last_time_sync > 5:
            await self._ack(packet, False, "time_unsynchronized")
            return
        if mode is EffectMode.OFF or packet.apply_at_ms == 0:
            self._apply_effect(mode, packet.payload)
        else:
            host_now = now_ms() + self.host_offset_ms
            delay = max(0.0, (packet.apply_at_ms - host_now) / 1000)
            if delay > 30:
                await self._ack(packet, False, "apply_time_too_far")
                return
            asyncio.get_running_loop().call_later(delay, self._apply_effect, mode, packet.payload)
        await self._ack(packet, True, "accepted")

    def _apply_effect(self, mode: EffectMode, payload: dict[str, Any]) -> None:
        self.mode = mode
        self.period_ms = int(payload.get("period_ms", 0))
        self.requested_brightness = int(payload.get("brightness", 1))
        self.actual_brightness = 0 if mode is EffectMode.OFF else min(
            self.requested_brightness, self.options.brightness_cap
        )
        self.state = "online"

    def _apply_off(self, reason: str) -> None:
        self.mode = EffectMode.OFF
        self.period_ms = 0
        self.requested_brightness = 1
        self.actual_brightness = 0
        self.state = reason

    async def _ack(self, command: Packet, accepted: bool, code: str) -> None:
        packet = Packet(
            MessageType.ACK,
            command.session_id,
            command.sequence,
            now_ms(),
            0,
            {
                "node_id": self.node_id,
                "mac": self.mac,
                "accepted": accepted,
                "code": code,
                "mode": self.mode.value,
            },
        )
        self.last_ack[command.sequence] = packet
        await self._send(packet)

    async def _send(self, packet: Packet) -> None:
        if self.transport is None or random.random() < self.options.packet_loss:
            return
        if self.options.jitter_ms:
            await asyncio.sleep(random.uniform(0, self.options.jitter_ms) / 1000)
        self.transport.sendto(
            encode_packet(packet, self.options.key), (self.options.host, self.options.port)
        )

    async def _status_loop(self) -> None:
        while True:
            address = self.transport.get_extra_info("sockname") if self.transport else ("0.0.0.0", 0)
            packet = Packet(
                MessageType.STATUS,
                self.replay.session_id or 0,
                max(self.replay.highest_sequence, 0),
                now_ms(),
                0,
                {
                    "node_id": self.node_id,
                    "mac": self.mac,
                    "ip": address[0],
                    "rssi": -45 - self.index % 30,
                    "firmware_version": self.firmware_version,
                    "uptime_ms": int((time.monotonic() - self.started) * 1000),
                    "mode": self.mode.value,
                    "period_ms": self.period_ms,
                    "requested_brightness": self.requested_brightness,
                    "actual_brightness": self.actual_brightness,
                    "session_id": self.replay.session_id or 0,
                    "last_sequence": max(self.replay.highest_sequence, 0),
                    "state": self.state,
                },
            )
            await self._send(packet)
            await asyncio.sleep(1)

    async def _failsafe_loop(self) -> None:
        while True:
            if time.monotonic() - self.last_heartbeat > 5 and self.mode is not EffectMode.OFF:
                self._apply_off("failsafe")
            await asyncio.sleep(0.2)

    async def _finish_ota(self, version: str) -> None:
        await asyncio.sleep(2)
        self.firmware_version = version
        self._apply_off("online")


async def run_simulator(args: argparse.Namespace) -> None:
    _load_dotenv(Path.cwd() / ".env")
    raw_key = args.key_hex or os.getenv("LIGHTBEACON_HMAC_KEY", "")
    try:
        key = bytes.fromhex(raw_key)
    except ValueError as exc:
        raise SystemExit("HMAC key must be hexadecimal") from exc
    if len(key) < 32:
        raise SystemExit("Set LIGHTBEACON_HMAC_KEY to at least 32 bytes")
    options = SimulatorOptions(args.host, args.port, key, args.loss / 100, args.jitter_ms)
    loop = asyncio.get_running_loop()
    transports: list[asyncio.DatagramTransport] = []
    for index in range(args.count):
        node_id = args.duplicate_id if args.duplicate_id and index < 2 else None
        transport, _ = await loop.create_datagram_endpoint(
            lambda index=index, node_id=node_id: SimulatedNode(index, options, node_id),
            local_addr=("0.0.0.0", 0),
            family=socket.AF_INET,
        )
        transports.append(transport)
    print(
        f"Started {args.count} simulated nodes for {args.host}:{args.port} "
        f"(loss={args.loss}%, jitter={args.jitter_ms}ms)"
    )
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except NotImplementedError:
            pass
    try:
        await stopped.wait()
    finally:
        for transport in transports:
            transport.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LightBeacon virtual ESP32 nodes")
    parser.add_argument("--count", type=int, default=10, choices=range(1, 51))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=40404)
    parser.add_argument("--key-hex", default="")
    parser.add_argument("--loss", type=float, default=0, help="bidirectional packet loss percent")
    parser.add_argument("--jitter-ms", type=int, default=0)
    parser.add_argument("--duplicate-id", default="", help="assign this ID to the first two nodes")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 0 <= args.loss <= 100:
        raise SystemExit("--loss must be between 0 and 100")
    asyncio.run(run_simulator(args))


if __name__ == "__main__":
    main()
