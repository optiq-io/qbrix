from __future__ import annotations

from datetime import datetime

from qbrixstore.postgres.models import Connection

from proxysvc.core import autonomy


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def overrides_of(connection: Connection) -> dict[str, str]:
    return {row.kind: row.level for row in connection.levels}


def levels_snapshot(connection: Connection, overrides: dict[str, str]) -> dict:
    """a connection's levels as a change records them before and after."""
    return {"name": connection.client_name, "levels": overrides}


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
        "levels_changed": autonomy.changed(overrides_of(connection)),
    }
