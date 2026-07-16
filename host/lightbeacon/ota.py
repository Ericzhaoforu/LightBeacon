from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from .config import Settings
from .database import Database
from .events import EventBroker
from .udp_controller import UdpController

MAX_FIRMWARE_SIZE = 8 * 1024 * 1024


class OtaError(ValueError):
    pass


class OtaManager:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        events: EventBroker,
        udp: UdpController,
    ) -> None:
        self.settings = settings
        self.database = database
        self.events = events
        self.udp = udp
        self.firmware_dir = settings.data_dir / "firmware"
        self.firmware_dir.mkdir(parents=True, exist_ok=True)

    async def create_job(
        self, upload: UploadFile, targets: list[str], version: str
    ) -> dict[str, Any]:
        if not targets or len(targets) > 50:
            raise OtaError("OTA requires between 1 and 50 target nodes")
        data = await upload.read(MAX_FIRMWARE_SIZE + 1)
        if len(data) > MAX_FIRMWARE_SIZE:
            raise OtaError("firmware image exceeds 8 MiB")
        if len(data) < 256 or data[0] != 0xE9:
            raise OtaError("file is not an ESP32 application image")
        job_id = uuid.uuid4().hex
        path = self.firmware_dir / f"{job_id}.bin"
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        token = secrets.token_urlsafe(32)
        self.database.create_ota_job(job_id, str(path), digest, len(data), targets, token)
        asyncio.create_task(self._dispatch(job_id, version), name=f"ota-{job_id}")
        return {"job_id": job_id, "sha256": digest, "size": len(data), "state": "queued"}

    async def _dispatch(self, job_id: str, version: str) -> None:
        job = self.database.get_ota_job(job_id)
        if job is None:
            return
        results: dict[str, str] = job["results"]
        self.database.update_ota_job(job_id, "dispatching", results)
        for start in range(0, len(job["targets"]), 5):
            batch = job["targets"][start : start + 5]
            tasks = []
            for node_id in batch:
                results[node_id] = "dispatching"
                payload = {
                    "job_id": job_id,
                    "version": version,
                    "size": job["size"],
                    "sha256": job["sha256"],
                    "url": f"{self.settings.public_base_url}/api/v1/firmware/{job_id}",
                    "token": job["token"],
                    "target": "esp32",
                }
                tasks.append((node_id, asyncio.create_task(self.udp.begin_ota(node_id, payload))))
            self.database.update_ota_job(job_id, "dispatching", results)
            await self.events.publish(
                {"type": "ota.updated", "job_id": job_id, "state": "dispatching", "results": results}
            )
            for node_id, task in tasks:
                results[node_id] = await task
            self.database.update_ota_job(job_id, "dispatching", results)
        state = "dispatched" if all(value == "accepted" for value in results.values()) else "partial"
        self.database.update_ota_job(job_id, state, results)
        await self.events.publish(
            {"type": "ota.updated", "job_id": job_id, "state": state, "results": results}
        )

