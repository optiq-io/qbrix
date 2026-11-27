from __future__ import annotations

from proxysvc.core.error import KeyLabelError

MAX_LABEL_LENGTH = 40


def label(value: str, field: str) -> str:
    """a key's app or environment, trimmed, between 1 and 40 characters."""
    cleaned = value.strip()
    if not cleaned:
        raise KeyLabelError(f"a key's {field} can't be empty")
    if len(cleaned) > MAX_LABEL_LENGTH:
        raise KeyLabelError(f"a key's {field} is at most {MAX_LABEL_LENGTH} characters")
    return cleaned
