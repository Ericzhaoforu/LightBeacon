from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _hex_secret(name: str, *, required: bool = True) -> bytes:
    value = os.getenv(name, "").strip()
    if not value and not required:
        return b""
    if value.startswith("CHANGE_ME"):
        raise RuntimeError(f"{name} must be replaced in .env")
    try:
        result = bytes.fromhex(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must contain hexadecimal bytes") from exc
    if len(result) < 32:
        raise RuntimeError(f"{name} must contain at least 32 bytes")
    return result


@dataclass(frozen=True, slots=True)
class Settings:
    bind_host: str
    http_port: int
    udp_port: int
    data_dir: Path
    log_dir: Path
    hmac_key: bytes
    session_secret: bytes
    admin_password_hash: str
    public_base_url: str
    offline_after_seconds: float = 5.0
    heartbeat_interval_seconds: float = 1.0
    time_sync_interval_seconds: float = 2.0

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        _load_dotenv(env_file or Path.cwd() / ".env")
        result = cls(
            bind_host=os.getenv("LIGHTBEACON_BIND_HOST", "0.0.0.0"),
            http_port=int(os.getenv("LIGHTBEACON_HTTP_PORT", "8080")),
            udp_port=int(os.getenv("LIGHTBEACON_UDP_PORT", "40404")),
            data_dir=Path(os.getenv("LIGHTBEACON_DATA_DIR", "./data")).resolve(),
            log_dir=Path(os.getenv("LIGHTBEACON_LOG_DIR", "./logs")).resolve(),
            hmac_key=_hex_secret("LIGHTBEACON_HMAC_KEY"),
            session_secret=_hex_secret("LIGHTBEACON_SESSION_SECRET"),
            admin_password_hash=os.getenv("LIGHTBEACON_ADMIN_PASSWORD_HASH", ""),
            public_base_url=os.getenv(
                "LIGHTBEACON_PUBLIC_BASE_URL", "http://127.0.0.1:8080"
            ).rstrip("/"),
        )
        if not result.admin_password_hash or result.admin_password_hash.startswith("CHANGE_ME"):
            raise RuntimeError("LIGHTBEACON_ADMIN_PASSWORD_HASH must be configured")
        result.data_dir.mkdir(parents=True, exist_ok=True)
        result.log_dir.mkdir(parents=True, exist_ok=True)
        return result

    @classmethod
    def for_test(cls, root: Path, udp_port: int = 0) -> "Settings":
        from .auth import hash_password

        return cls(
            bind_host="127.0.0.1",
            http_port=0,
            udp_port=udp_port,
            data_dir=root / "data",
            log_dir=root / "logs",
            hmac_key=bytes(range(32)),
            session_secret=bytes(reversed(range(32))),
            admin_password_hash=hash_password("test-password"),
            public_base_url="http://127.0.0.1:8080",
        )

