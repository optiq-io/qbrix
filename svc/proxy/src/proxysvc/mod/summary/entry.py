from __future__ import annotations

from collections.abc import Sequence

from qbrixstore.postgres.models import Change

from proxysvc.mod.change.serialize import history_entry
from proxysvc.mod.change.serialize import who_made
from proxysvc.mod.people import People

CHANGES_SHOWN = 20


def _via(change: Change) -> str | None:
    return (change.client_name or "a client") if change.connection_id else None


def by_who(changes: Sequence[Change], people: People) -> list[dict]:
    """changes grouped by who made them and through which client, each group
    newest first and showing its latest few. changes run newest first."""
    groups: dict[tuple, dict] = {}
    for change in changes:
        key = (change.actor_kind, change.actor_user_id, _via(change))
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "who": who_made(change, people),
                "via": _via(change),
                "count": 0,
                "changes": [],
            }
        group["count"] += 1
        if len(group["changes"]) < CHANGES_SHOWN:
            group["changes"].append(history_entry(change, people))
    return list(groups.values())
