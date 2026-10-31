from __future__ import annotations

import json
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from qbrixstore.postgres.models import Change

from proxysvc.mod.change.serialize import history_entry
from proxysvc.mod.change.serialize import who_made
from proxysvc.mod.change.undo import NOT_UNDOABLE
from proxysvc.mod.change.undo import is_undoable
from proxysvc.mod.metric.serialize import window_label
from proxysvc.mod.people import People

FOLD_WITHIN = timedelta(minutes=10)

VERBS = {
    "loop.create": "created",
    "loop.launch": "launched",
    "loop.rename": "renamed",
    "loop.pause": "paused",
    "loop.resume": "resumed",
    "loop.delete": "deleted",
    "metric.create": "created",
    "metric.delete": "deleted",
    "experiment.create": "created",
    "experiment.update": "changed",
    "experiment.reset": "reset",
    "experiment.restore": "restored",
    "experiment.delete": "deleted",
    "pool.create": "created",
    "pool.update": "changed",
    "pool.delete": "deleted",
    "gate.create": "created",
    "gate.replace": "changed",
    "gate.patch": "changed",
    "gate.delete": "deleted",
}
_ANY_KIND = "changed"

_PLAIN_FIELDS = ("name", "key", "state", "audience")


@dataclass(frozen=True, slots=True)
class TargetName:
    """what a target is called now, for a target that still exists."""

    name: str
    key: str | None = None


def fold(changes: Sequence[Change]) -> list[list[Change]]:
    """consecutive changes, newest first, grouped when the same actor made the
    same kind of change to the same target within the window of the one before.
    an undo and what it undid stay rows of their own, or "undone by" is lost."""
    groups: list[list[Change]] = []
    for change in changes:
        if groups and _continues(groups[-1][-1], change):
            groups[-1].append(change)
        else:
            groups.append([change])
    return groups


def _continues(newer: Change, older: Change) -> bool:
    return (
        _foldable(newer)
        and _foldable(older)
        and _burst_key(newer) == _burst_key(older)
        and newer.created_at - older.created_at <= FOLD_WITHIN
    )


def _foldable(change: Change) -> bool:
    return change.status == "applied" and change.undoes_id is None


def _burst_key(change: Change) -> tuple:
    return (
        change.target_type,
        change.target_id,
        change.kind,
        change.actor_kind,
        change.actor_user_id,
        change.connection_id,
    )


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _difference(field: str, before: Any, after: Any) -> dict:
    return {"field": field, "before": _text(before), "after": _text(after)}


def _metric_name(snapshot: dict) -> str | None:
    metric = snapshot.get("metric")
    return metric["name"] if metric else None


def _window(snapshot: dict) -> str | None:
    seconds = snapshot.get("window_seconds")
    return window_label(seconds) if seconds is not None else None


def _option_names(snapshot: dict) -> dict[str, str]:
    return {option["key"]: option["name"] for option in snapshot.get("options") or ()}


def diff(before: dict | None, after: dict | None) -> list[dict]:
    """what changed, field by field. a change with one side, a create or a
    delete, has nothing to compare."""
    if before is None or after is None:
        return []
    pairs = [(field, before.get(field), after.get(field)) for field in _PLAIN_FIELDS]
    pairs.append(("metric", _metric_name(before), _metric_name(after)))
    pairs.append(("window", _window(before), _window(after)))
    changed = [_difference(*pair) for pair in pairs if pair[1] != pair[2]]

    options_before = _option_names(before)
    options_after = _option_names(after)
    changed += [
        _difference("option", None, name)
        for key, name in options_after.items()
        if key not in options_before
    ]
    changed += [
        _difference("option", name, None)
        for key, name in options_before.items()
        if key not in options_after
    ]
    return changed


def _target(change: Change, targets: Mapping[tuple[str, str], TargetName]) -> dict:
    """a target by its name now; one that is gone keeps its last name and key
    from the snapshot."""
    found = targets.get((change.target_type, change.target_id))
    snapshot = change.after or change.before or {}
    return {
        "type": change.target_type,
        "id": change.target_id,
        "key": found.key if found else snapshot.get("key"),
        "name": found.name if found else snapshot.get("name"),
    }


def _actor_piece(change: Change, people: People) -> dict:
    if change.actor_kind == "qbrix":
        actor = {"kind": "qbrix"}
    elif change.connection_id:
        actor = {
            "kind": "connection",
            "name": change.client_name or "a client",
            "on_behalf_of": people.name(change.actor_user_id),
        }
    else:
        actor = {"kind": "member", "name": people.name(change.actor_user_id)}
    return {"kind": "actor", "actor": actor}


def _target_pieces(target: dict) -> list[dict]:
    name = target["name"]
    if target["type"] in ("loop", "metric") and name:
        return [{"kind": target["type"], "name": name}]
    words = f"{target['type']} {name}" if name else f"the {target['type']}"
    return [{"kind": "text", "text": words}]


def pieces(change: Change, target: dict, people: People, count: int = 1) -> list[dict]:
    """the sentence as typed parts: who, one verb per kind, the target. what
    changed stays in the diff, so a value never lands in the sentence."""
    verb = (
        f"made {count} changes to" if count > 1 else VERBS.get(change.kind, _ANY_KIND)
    )
    return [
        _actor_piece(change, people),
        {"kind": "text", "text": f" {verb} "},
        *_target_pieces(target),
        {"kind": "text", "text": "."},
    ]


def workspace_entry(
    changes: Sequence[Change],
    people: People,
    targets: Mapping[tuple[str, str], TargetName],
    undoers: Mapping[str, Change],
) -> dict:
    """one row of the workspace's changes: a change, or a fold of them newest
    first. a fold reads as its newest, and its diff runs from the oldest's
    before to the newest's after."""
    newest = changes[0]
    oldest = changes[-1]
    target = _target(newest, targets)
    undoer = undoers.get(newest.id)
    return {
        **history_entry(newest, people),
        "target": target,
        "before": oldest.before,
        "after": newest.after,
        "pieces": pieces(newest, target, people, len(changes)),
        "diff": diff(oldest.before, newest.after),
        "undoable": is_undoable(newest.kind) and newest.status == "applied",
        "not_undoable_reason": NOT_UNDOABLE.get(newest.kind),
        "undone_by": (
            {
                "id": undoer.id,
                "who": who_made(undoer, people),
                "at": undoer.created_at.isoformat(),
            }
            if undoer
            else None
        ),
        "count": len(changes),
        "first_at": oldest.created_at.isoformat() if oldest.created_at else None,
        "ids": [change.id for change in changes],
    }
