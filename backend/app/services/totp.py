from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code_at(secret_b32: str, step: int) -> str:
    key = base64.b32decode(secret_b32.upper().replace(" ", ""), casefold=True)
    msg = struct.pack(">Q", step)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFF_FFFF
    return f"{code % 1_000_000:06d}"


def verify_code(secret_b32: str, user_code: str, window: int = 1) -> bool:
    normalized = str(user_code or "").strip()
    if len(normalized) != 6 or not normalized.isdigit():
        return False
    step = int(time.time()) // 30
    for delta in range(-window, window + 1):
        if secrets.compare_digest(code_at(secret_b32, step + delta), normalized):
            return True
    return False


def otpauth_uri(secret_b32: str, username: str, issuer: str = "BlueBird Alerts") -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(username)}"
        f"?secret={secret_b32}&issuer={quote(issuer)}"
    )
