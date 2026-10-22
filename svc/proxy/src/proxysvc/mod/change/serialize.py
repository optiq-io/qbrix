from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from qbrixstore.postgres.models import Change
from qbrixstore.redis import Learning


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
        "undoes_id": change.undoes_id,
        "created_at": change.created_at.isoformat() if change.created_at else None,
    }
