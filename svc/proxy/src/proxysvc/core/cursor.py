from __future__ import annotations

import base64
import binascii
from datetime import datetime
from datetime import timezone

from proxysvc.core.error import InvalidCursorError

Position = tuple[datetime, str]


def encode(created_at: datetime, row_id: str) -> str:
    """where a newest-first page ended: the last row's time and id, opaque."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    raw = f"{created_at.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> Position:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, row_id = raw.split("|", 1)
        created_at = datetime.fromisoformat(stamp)
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        raise InvalidCursorError("the cursor isn't one a previous page returned") from e
    if not row_id or created_at.tzinfo is None:
        raise InvalidCursorError("the cursor isn't one a previous page returned")
    return created_at, row_id
