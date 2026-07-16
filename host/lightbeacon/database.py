from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import Layout


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()

    def initialize(self) -> None:
        with self.lock, self.connection:
            self.connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS nodes (
                    mac TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    firmware_version TEXT NOT NULL,
                    rssi INTEGER NOT NULL,
                    last_seen_ms INTEGER NOT NULL,
                    status_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_id ON nodes(node_id);
                CREATE TABLE IF NOT EXISTS layout (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    rows INTEGER NOT NULL,
                    columns_count INTEGER NOT NULL,
                    cells_json TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ota_jobs (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    targets_json TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    token TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_ms INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )
            existing = self.connection.execute("SELECT 1 FROM layout WHERE id=1").fetchone()
            if not existing:
                self.connection.execute(
                    "INSERT INTO layout(id, rows, columns_count, cells_json, updated_at_ms) VALUES(1,4,4,'[]',?)",
                    (int(time.time() * 1000),),
                )

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    def upsert_node(self, status: dict[str, Any]) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO nodes(mac,node_id,ip,firmware_version,rssi,last_seen_ms,status_json)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(mac) DO UPDATE SET
                    node_id=excluded.node_id,
                    ip=excluded.ip,
                    firmware_version=excluded.firmware_version,
                    rssi=excluded.rssi,
                    last_seen_ms=excluded.last_seen_ms,
                    status_json=excluded.status_json
                """,
                (
                    status["mac"],
                    status["node_id"],
                    status["ip"],
                    status["firmware_version"],
                    status["rssi"],
                    status["last_seen_ms"],
                    json.dumps(status, separators=(",", ":")),
                ),
            )

    def get_layout(self) -> Layout:
        with self.lock:
            row = self.connection.execute(
                "SELECT rows, columns_count, cells_json FROM layout WHERE id=1"
            ).fetchone()
        return Layout(rows=row["rows"], columns=row["columns_count"], cells=json.loads(row["cells_json"]))

    def save_layout(self, layout: Layout) -> None:
        cells = [cell.model_dump() for cell in layout.cells]
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE layout SET rows=?, columns_count=?, cells_json=?, updated_at_ms=? WHERE id=1",
                (
                    layout.rows,
                    layout.columns,
                    json.dumps(cells, separators=(",", ":")),
                    int(time.time() * 1000),
                ),
            )

    def create_ota_job(
        self,
        job_id: str,
        image_path: str,
        sha256: str,
        size: int,
        targets: list[str],
        token: str,
    ) -> None:
        now = int(time.time() * 1000)
        results = {node_id: "queued" for node_id in targets}
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO ota_jobs(id,state,image_path,sha256,size,targets_json,results_json,token,created_at_ms,updated_at_ms)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    "queued",
                    image_path,
                    sha256,
                    size,
                    json.dumps(targets),
                    json.dumps(results),
                    token,
                    now,
                    now,
                ),
            )

    def get_ota_job(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute("SELECT * FROM ota_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["targets"] = json.loads(result.pop("targets_json"))
        result["results"] = json.loads(result.pop("results_json"))
        return result

    def update_ota_job(self, job_id: str, state: str, results: dict[str, str]) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE ota_jobs SET state=?, results_json=?, updated_at_ms=? WHERE id=?",
                (state, json.dumps(results), int(time.time() * 1000), job_id),
            )

    def audit(self, event: str, details: dict[str, Any]) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO audit_log(timestamp_ms,event,details_json) VALUES(?,?,?)",
                (int(time.time() * 1000), event, json.dumps(details, separators=(",", ":"))),
            )

