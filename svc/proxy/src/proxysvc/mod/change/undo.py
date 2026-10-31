from __future__ import annotations

from dataclasses import dataclass

UNDOABLE_KINDS = frozenset(
    {
        "experiment.update",
        "experiment.reset",
        "experiment.restore",
        "gate.create",
        "gate.replace",
        "gate.patch",
        "gate.delete",
        "pool.update",
        "metric.create",
        "loop.create",
        "loop.rename",
        "loop.pause",
        "loop.resume",
    }
)

NOT_UNDOABLE = {
    "experiment.create": "creating an experiment cannot be undone",
    "experiment.delete": "deleting an experiment removes its gate and learners, "
    "so it cannot be undone",
    "pool.create": "creating a pool cannot be undone",
    "pool.delete": "deleting a pool removes its arms, so it cannot be undone",
    "metric.delete": "deleting a metric cannot be undone",
    "loop.launch": "launching a loop starts its first cycle, so it cannot be undone",
    "loop.delete": "deleting a loop cannot be undone",
}


def is_undoable(kind: str) -> bool:
    return kind in UNDOABLE_KINDS


def undo_scope(target_type: str) -> str:
    """undoing a change takes what writing to its target takes."""
    return f"{target_type}:write"


@dataclass(frozen=True, slots=True)
class Undoing:
    """the change a write undoes, recorded on the write's own change.

    latest_id is the target's newest change when the undo was checked; a
    different one at write time means a change landed in between.
    """

    change_id: str
    latest_id: str
    reason: str | None = None
