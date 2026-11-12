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
        "loop.commit",
        "loop.reopen",
        "loop.pause",
        "loop.resume",
        "delivery.update",
        "connection.levels",
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
    "loop.retire": "retiring a loop says the choice has left the product, so it "
    "can't be undone; create a new loop to serve it again",
    "cycle.start": "starting a cycle begins fresh learning, so it can't be undone; "
    "the earlier cycle stays readable",
    "cycle.reset": "resetting a cycle begins fresh learning, so it can't be undone; "
    "the earlier cycle stays readable",
    "note.add": "a note stays in history; add another note to correct it",
}


def is_undoable(kind: str) -> bool:
    return kind in UNDOABLE_KINDS


def undo_scope(target_type: str) -> str | None:
    """undoing a change takes what writing to its target takes. a connection's
    levels take no role scope: only its own person sets them, whatever the role."""
    if target_type == "connection":
        return None
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
