from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        raise ValueError("Enter a valid email address")
    return email


def validate_password(value: str) -> None:
    if len(value) < 10:
        raise ValueError("Password must contain at least 10 characters")
    if len(value) > 256:
        raise ValueError("Password is too long")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def issue_secret() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, secret_digest(raw)


def secret_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def expires_at(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

