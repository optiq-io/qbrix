"""the post-sign-in destination a verification link carries back to the console.

it lands in an email sent from our own domain, so only a path on the console's
origin is ever kept; anything else is dropped rather than refused.
"""

from __future__ import annotations

import unicodedata

MAX_REDIRECT_LENGTH = 2048


def safe_redirect(value: str | None) -> str | None:
    if not value or len(value) > MAX_REDIRECT_LENGTH:
        return None
    if not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value:
        return None
    if any(unicodedata.category(char) == "Cc" for char in value):
        return None
    if value == "/":
        return None
    return value
