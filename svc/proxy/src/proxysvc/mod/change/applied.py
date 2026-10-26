from __future__ import annotations

from dataclasses import dataclass

from qbrixstore.postgres.models import Change

from proxysvc.mod.change.undo import is_undoable


@dataclass(frozen=True, slots=True)
class Applied:
    """a write's result beside the change that recorded it."""

    value: dict
    change: dict

    @classmethod
    def of(cls, value: dict, change: Change) -> Applied:
        return cls(
            value=value,
            change={
                "id": change.id,
                "kind": change.kind,
                "undoable": is_undoable(change.kind),
            },
        )
