from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from qbrixstore.postgres.models import Change
from qbrixstore.redis import Learning

from proxysvc.mod.people import People
from proxysvc.mod.change.undo import is_undoable


def snapshot(value: Any) -> Any:
    """a json-safe copy of a serialized object, for a change's before and after."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [snapshot(item) for item in value]
    return value


def learning_snapshot(learnings: dict[str, Learning]) -> dict:
    """what each experiment had learned, keyed by experiment id."""
    return {
        experiment_id: {
            "params": learning.params,
            "applied": learning.applied,
            "last_id": learning.last_id,
        }
        for experiment_id, learning in learnings.items()
    }


def history_entry(change: Change, people: People) -> dict:
    """a change as history reads it: what, when, who and through what, why.

    a connection acts for its person, so it reads as that person via the
    client; a change by qbrix has no person.
    """
    by_qbrix = change.actor_kind == "qbrix"
    return {
        "id": change.id,
        "kind": change.kind,
        "at": change.created_at.isoformat() if change.created_at else None,
        "status": change.status,
        "who": {
            "kind": change.actor_kind,
            "user_id": None if by_qbrix else change.actor_user_id,
            "name": None if by_qbrix else people.name(change.actor_user_id),
        },
        "via": (
            {"connection_id": change.connection_id, "client": change.client_name}
            if change.connection_id
            else None
        ),
        "reason": change.reason,
        "evidence": change.evidence,
        "request_id": change.request_id,
        "undoes_id": change.undoes_id,
    }


def change_to_dict(change: Change) -> dict:
    return {
        "id": change.id,
        "kind": change.kind,
        "target_type": change.target_type,
        "target_id": change.target_id,
        "actor": {
            "kind": change.actor_kind,
            "user_id": change.actor_user_id,
            "connection_id": change.connection_id,
            "client_name": change.client_name,
            "api_key_id": change.api_key_id,
        },
        "request_id": change.request_id,
        "reason": change.reason,
        "evidence": change.evidence,
        "before": change.before,
        "after": change.after,
        "learning": change.learning,
        "status": change.status,
        "undoable": is_undoable(change.kind),
        "undoes_id": change.undoes_id,
        "created_at": change.created_at.isoformat() if change.created_at else None,
    }
