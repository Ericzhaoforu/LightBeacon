from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .protocol import EffectMode


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class EffectRequest(BaseModel):
    node_ids: list[str] = Field(min_length=1, max_length=50)
    mode: EffectMode
    period_ms: int = 0
    brightness: int = Field(default=25, ge=1, le=100)

    @field_validator("node_ids")
    @classmethod
    def validate_node_ids(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not 1 <= len(value) <= 32 or any(
                not (char.isascii() and (char.isalnum() or char in "_-")) for char in value
            ):
                raise ValueError(f"invalid node ID: {value}")
            if value not in seen:
                result.append(value)
                seen.add(value)
        return result

    @model_validator(mode="after")
    def validate_period(self) -> "EffectRequest":
        if self.mode.is_blinking and not 200 <= self.period_ms <= 10_000:
            raise ValueError("blinking effects require period_ms between 200 and 10000")
        if not self.mode.is_blinking:
            self.period_ms = 0
        return self


class LayoutCell(BaseModel):
    row: int = Field(ge=0, le=99)
    column: int = Field(ge=0, le=99)
    node_id: str | None = Field(default=None, max_length=32)


class Layout(BaseModel):
    rows: int = Field(ge=1, le=50)
    columns: int = Field(ge=1, le=50)
    cells: list[LayoutCell] = Field(default_factory=list, max_length=2500)

    @model_validator(mode="after")
    def validate_cells(self) -> "Layout":
        positions: set[tuple[int, int]] = set()
        node_ids: set[str] = set()
        for cell in self.cells:
            if cell.row >= self.rows or cell.column >= self.columns:
                raise ValueError("cell lies outside the configured grid")
            position = (cell.row, cell.column)
            if position in positions:
                raise ValueError("layout contains a duplicate cell position")
            positions.add(position)
            if cell.node_id:
                if cell.node_id in node_ids:
                    raise ValueError("a node ID may only be bound to one cell")
                node_ids.add(cell.node_id)
        return self


class NodeView(BaseModel):
    node_id: str
    mac: str
    ip: str
    port: int
    rssi: int
    firmware_version: str
    uptime_ms: int
    mode: EffectMode
    period_ms: int
    requested_brightness: int
    actual_brightness: int
    session_id: int
    last_sequence: int
    state: str
    last_seen_ms: int
    online: bool
    id_conflict: bool = False


class CommandResult(BaseModel):
    sequence: int
    apply_at_ms: int
    results: dict[str, Literal["accepted", "timeout", "offline", "conflict", "error"]]


class OtaCreateResponse(BaseModel):
    job_id: str
    sha256: str
    size: int
    state: str

