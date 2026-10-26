from __future__ import annotations

from datetime import datetime

from qbrixstore.postgres.models import Connection


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def connection_to_dict(connection: Connection) -> dict:
    user = connection.user
    return {
        "id": connection.id,
        "client": {
            "name": connection.client_name,
            "uri": connection.client_uri,
            "identity": connection.client_identity,
        },
        "user": {"id": user.id, "name": user.name or user.email},
        "created_at": _iso(connection.created_at),
        "last_used_at": _iso(connection.last_used_at),
    }
