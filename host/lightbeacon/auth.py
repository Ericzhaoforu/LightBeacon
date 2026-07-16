from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("administrator password must contain at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


class SessionManager:
    def __init__(self, secret: bytes, ttl_seconds: int = 8 * 60 * 60) -> None:
        self.secret = secret
        self.ttl_seconds = ttl_seconds

    def issue(self, username: str = "admin") -> str:
        payload = json.dumps(
            {"sub": username, "exp": int(time.time()) + self.ttl_seconds, "nonce": _b64(secrets.token_bytes(12))},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = _b64(payload)
        signature = _b64(hmac.digest(self.secret, encoded.encode("ascii"), "sha256"))
        return f"{encoded}.{signature}"

    def verify(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.digest(self.secret, encoded.encode("ascii"), "sha256")
        try:
            if not hmac.compare_digest(_unb64(signature), expected):
                return False
            payload = json.loads(_unb64(encoded))
            return payload.get("sub") == "admin" and int(payload.get("exp", 0)) >= int(time.time())
        except (ValueError, TypeError, json.JSONDecodeError):
            return False

