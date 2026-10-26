from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

ACCESS = "access"
REFRESH = "refresh"

ACCESS_PREFIX = "qbx_at_"
REFRESH_PREFIX = "qbx_rt_"

ACCESS_TTL = timedelta(hours=8)
REFRESH_TTL = timedelta(days=90)
UNUSED_LIMIT = timedelta(days=90)


def mint(prefix: str) -> tuple[str, str]:
    """a new opaque token and the hash it is stored under."""
    token = prefix + secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
