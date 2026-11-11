from __future__ import annotations

from collections.abc import Sequence

from qbrixstore.postgres.models import Change

from proxysvc.mod.change.serialize import history_entry
from proxysvc.mod.change.serialize import who_made
from proxysvc.mod.people import People

PAUSE = "loop.pause"
RESUME = "loop.resume"
ALERT_KINDS = (PAUSE, RESUME)
SAFETY_PAUSE = "safety_pause"
CHANGES_SHOWN = 20


def _safety_pause(change: Change | None) -> bool:
    return change is not None and change.kind == PAUSE and change.actor_kind == "qbrix"


def _via(change: Change) -> str | None:
    return (change.client_name or "a client") if change.connection_id else None


def _opened(change: Change) -> dict:
    evidence = change.evidence or {}
    return {
        "kind": SAFETY_PAUSE,
        "signal": evidence.get("signal"),
        "opened_at": change.created_at.isoformat(),
        "evidence": change.evidence,
        "change_id": change.id,
        "recovered": None,
    }


def alerts(
    at_since: Change | None, changes: Sequence[Change], people: People
) -> list[dict]:
    """a loop's safety pauses in the range: one already open at since, and
    each qbrix opened in it. a person resuming the loop is its recovery.
    changes run oldest first."""
    found: list[dict] = []
    current = _opened(at_since) if _safety_pause(at_since) else None
    if current:
        found.append(current)
    for change in changes:
        if _safety_pause(change):
            current = _opened(change)
            found.append(current)
        elif change.kind == RESUME and current is not None:
            current["recovered"] = {
                "at": change.created_at.isoformat(),
                "who": who_made(change, people),
                "via": _via(change),
                "change_id": change.id,
            }
            current = None
    return found


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
