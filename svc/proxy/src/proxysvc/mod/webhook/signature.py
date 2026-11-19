from __future__ import annotations

import hashlib
import hmac

HEADER = "qbrix-signature"


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """t=<unix seconds>,v1=<hex hmac-sha256 of "<t>.<raw body>">, which the
    receiver recomputes with the same secret to know the message is ours."""
    signed = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"
