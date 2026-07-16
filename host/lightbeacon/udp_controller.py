from __future__ import annotations

import asyncio
import logging
import secrets
import socket
from dataclasses import dataclass, replace
from typing import Any

from .config import Settings
from .database import Database
from .events import EventBroker
from .models import CommandResult, EffectRequest, NodeView
from .protocol import EffectMode, MessageType, Packet, ProtocolError, decode_packet, encode_packet, now_ms

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeNode:
    node_id: str
    mac: str
    address: tuple[str, int]
    rssi: int = -127
    firmware_version: str = "unknown"
    uptime_ms: int = 0
    mode: EffectMode = EffectMode.OFF
    period_ms: int = 0
    requested_brightness: int = 1
    actual_brightness: int = 0
    session_id: int = 0
    last_sequence: int = 0
    state: str = "online"
    last_seen_ms: int = 0
    online: bool = True
    id_conflict: bool = False

    def view(self) -> NodeView:
        return NodeView(
            node_id=self.node_id,
            mac=self.mac,
            ip=self.address[0],
            port=self.address[1],
            rssi=self.rssi,
            firmware_version=self.firmware_version,
            uptime_ms=self.uptime_ms,
            mode=self.mode,
            period_ms=self.period_ms,
            requested_brightness=self.requested_brightness,
            actual_brightness=self.actual_brightness,
            session_id=self.session_id,
            last_sequence=self.last_sequence,
            state=self.state,
            last_seen_ms=self.last_seen_ms,
            online=self.online,
            id_conflict=self.id_conflict,
        )


class _DatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, controller: "UdpController") -> None:
        self.controller = controller

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        asyncio.create_task(self.controller.handle_datagram(data, addr))

    def error_received(self, exc: Exception) -> None:
        LOGGER.warning("UDP transport error: %s", exc)


class UdpController:
    def __init__(self, settings: Settings, database: Database, events: EventBroker) -> None:
        self.settings = settings
        self.database = database
        self.events = events
        self.session_id = secrets.randbits(64) or 1
        self.sequence = secrets.randbelow(0x7FFFFFFF) + 1
        self.transport: asyncio.DatagramTransport | None = None
        self.nodes_by_mac: dict[str, RuntimeNode] = {}
        self.pending: dict[tuple[str, int], asyncio.Future[dict[str, Any]]] = {}
        self.tasks: list[asyncio.Task[None]] = []
        self._closing = False
        self.bound_port = settings.udp_port

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((self.settings.bind_host, self.settings.udp_port))
        self.bound_port = sock.getsockname()[1]
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DatagramProtocol(self), sock=sock
        )
        self.transport = transport
        self.tasks = [
            asyncio.create_task(self._heartbeat_loop(), name="lightbeacon-heartbeat"),
            asyncio.create_task(self._time_sync_loop(), name="lightbeacon-time-sync"),
            asyncio.create_task(self._offline_loop(), name="lightbeacon-offline-monitor"),
        ]
        await self.all_off(reason="host_startup")

    async def close(self) -> None:
        self._closing = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.transport:
            self.transport.close()
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()

    def _next_sequence(self) -> int:
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        if self.sequence == 0:
            self.sequence = 1
        return self.sequence

    def _targets_for_id(self, node_id: str) -> list[RuntimeNode]:
        return [node for node in self.nodes_by_mac.values() if node.node_id == node_id]

    def _mark_conflicts(self) -> None:
        counts: dict[str, int] = {}
        for node in self.nodes_by_mac.values():
            counts[node.node_id] = counts.get(node.node_id, 0) + 1
        for node in self.nodes_by_mac.values():
            node.id_conflict = counts[node.node_id] > 1

    def list_nodes(self) -> list[NodeView]:
        self._mark_conflicts()
        return sorted((node.view() for node in self.nodes_by_mac.values()), key=lambda node: (node.node_id, node.mac))

    async def handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            packet = decode_packet(data, self.settings.hmac_key)
        except ProtocolError as exc:
            LOGGER.debug("Rejected packet from %s: %s", addr, exc)
            return
        if packet.message_type is MessageType.STATUS:
            await self._handle_status(packet, addr)
        elif packet.message_type is MessageType.ACK:
            self._handle_ack(packet)

    async def _handle_status(self, packet: Packet, addr: tuple[str, int]) -> None:
        payload = packet.payload
        try:
            node_id = str(payload["node_id"])
            mac = str(payload["mac"]).upper()
            mode = EffectMode(payload.get("mode", "OFF"))
            if not node_id or len(node_id) > 32 or len(mac) > 32:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            LOGGER.debug("Invalid STATUS payload from %s", addr)
            return
        previous = self.nodes_by_mac.get(mac)
        node = RuntimeNode(
            node_id=node_id,
            mac=mac,
            address=addr,
            rssi=int(payload.get("rssi", -127)),
            firmware_version=str(payload.get("firmware_version", "unknown"))[:64],
            uptime_ms=int(payload.get("uptime_ms", 0)),
            mode=mode,
            period_ms=int(payload.get("period_ms", 0)),
            requested_brightness=int(payload.get("requested_brightness", 1)),
            actual_brightness=int(payload.get("actual_brightness", 0)),
            session_id=int(payload.get("session_id", 0)),
            last_sequence=int(payload.get("last_sequence", 0)),
            state=str(payload.get("state", "online"))[:32],
            last_seen_ms=now_ms(),
            online=True,
        )
        self.nodes_by_mac[mac] = node
        self._mark_conflicts()
        view = node.view().model_dump(mode="json")
        self.database.upsert_node(view)
        event_type = "node.discovered" if previous is None else "node.updated"
        await self.events.publish({"type": event_type, "node": view})

    def _handle_ack(self, packet: Packet) -> None:
        node_id = str(packet.payload.get("node_id", ""))
        future = self.pending.get((node_id, packet.sequence))
        if future and not future.done():
            future.set_result(packet.payload)

    def _send_packet(self, packet: Packet, address: tuple[str, int]) -> None:
        if self.transport is None:
            return
        self.transport.sendto(encode_packet(packet, self.settings.hmac_key), address)

    def _broadcast(self, packet: Packet, *, repeats: int = 1) -> None:
        if self.transport is None:
            return
        encoded = encode_packet(packet, self.settings.hmac_key)
        for _ in range(repeats):
            self.transport.sendto(encoded, ("255.255.255.255", self.bound_port))

    async def _send_reliable(
        self,
        node: RuntimeNode,
        message_type: MessageType,
        payload: dict[str, Any],
        sequence: int,
        apply_at_ms: int,
    ) -> str:
        packet = Packet(message_type, self.session_id, sequence, now_ms(), apply_at_ms, payload)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        key = (node.node_id, sequence)
        self.pending[key] = future
        try:
            for attempt in range(3):
                self._send_packet(replace(packet, sent_at_ms=now_ms()), node.address)
                try:
                    ack = await asyncio.wait_for(asyncio.shield(future), timeout=0.2 * (2**attempt))
                    return "accepted" if bool(ack.get("accepted")) else "error"
                except TimeoutError:
                    continue
            return "timeout"
        finally:
            self.pending.pop(key, None)

    async def set_effect(self, request: EffectRequest) -> CommandResult:
        sequence = self._next_sequence()
        apply_at = now_ms() + 500
        payload = {
            "mode": request.mode.value,
            "period_ms": request.period_ms,
            "brightness": request.brightness,
        }
        results: dict[str, str] = {}
        jobs: list[tuple[str, asyncio.Task[str]]] = []
        self._mark_conflicts()
        for node_id in request.node_ids:
            matches = self._targets_for_id(node_id)
            if len(matches) > 1:
                results[node_id] = "conflict"
            elif not matches or not matches[0].online:
                results[node_id] = "offline"
            else:
                jobs.append(
                    (
                        node_id,
                        asyncio.create_task(
                            self._send_reliable(
                                matches[0], MessageType.SET_EFFECT, payload, sequence, apply_at
                            )
                        ),
                    )
                )
        for node_id, task in jobs:
            results[node_id] = await task
        self.database.audit(
            "set_effect",
            {"sequence": sequence, "apply_at_ms": apply_at, "request": request.model_dump(mode="json"), "results": results},
        )
        await self.events.publish(
            {"type": "command.completed", "sequence": sequence, "apply_at_ms": apply_at, "results": results}
        )
        return CommandResult(sequence=sequence, apply_at_ms=apply_at, results=results)

    async def all_off(self, *, reason: str = "operator") -> CommandResult:
        sequence = self._next_sequence()
        packet = Packet(
            MessageType.SET_EFFECT,
            self.session_id,
            sequence,
            now_ms(),
            0,
            {"mode": "OFF", "period_ms": 0, "brightness": 1, "reason": reason},
        )
        self._broadcast(packet, repeats=3)
        for node in self.nodes_by_mac.values():
            self._send_packet(packet, node.address)
        results = {node.node_id: "accepted" for node in self.nodes_by_mac.values()}
        self.database.audit("all_off", {"sequence": sequence, "reason": reason})
        await self.events.publish({"type": "command.all_off", "sequence": sequence, "reason": reason})
        return CommandResult(sequence=sequence, apply_at_ms=0, results=results)

    async def begin_ota(self, node_id: str, payload: dict[str, Any]) -> str:
        matches = self._targets_for_id(node_id)
        if len(matches) > 1:
            return "conflict"
        if not matches or not matches[0].online:
            return "offline"
        sequence = self._next_sequence()
        return await self._send_reliable(
            matches[0], MessageType.OTA_BEGIN, payload, sequence, 0
        )

    async def _heartbeat_loop(self) -> None:
        while not self._closing:
            sequence = self._next_sequence()
            packet = Packet(
                MessageType.HEARTBEAT,
                self.session_id,
                sequence,
                now_ms(),
                0,
                {"host_session": self.session_id},
            )
            self._broadcast(packet)
            for node in self.nodes_by_mac.values():
                self._send_packet(packet, node.address)
            await asyncio.sleep(self.settings.heartbeat_interval_seconds)

    async def _time_sync_loop(self) -> None:
        while not self._closing:
            sequence = self._next_sequence()
            packet = Packet(
                MessageType.TIME_SYNC,
                self.session_id,
                sequence,
                now_ms(),
                0,
                {"host_time_ms": now_ms()},
            )
            self._broadcast(packet)
            for node in self.nodes_by_mac.values():
                self._send_packet(packet, node.address)
            await asyncio.sleep(self.settings.time_sync_interval_seconds)

    async def _offline_loop(self) -> None:
        threshold_ms = int(self.settings.offline_after_seconds * 1000)
        while not self._closing:
            current = now_ms()
            for mac, node in list(self.nodes_by_mac.items()):
                online = current - node.last_seen_ms <= threshold_ms
                if node.online and not online:
                    node.online = False
                    node.state = "offline"
                    await self.events.publish(
                        {"type": "node.offline", "node": node.view().model_dump(mode="json")}
                    )
            await asyncio.sleep(1.0)

