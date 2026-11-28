from __future__ import annotations

from dataclasses import dataclass

UNDOABLE_KINDS = frozenset(
    {
        "metric.create",
        "metric.update",
        "loop.create",
        "loop.rename",
        "brief.update",
        "loop.commit",
        "loop.reopen",
        "loop.pause",
        "loop.resume",
        "delivery.update",
        "context.update",
        "engine.version",
        "connection.levels",
    }
)

NOT_UNDOABLE = {
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
    "engine.minor": "qbrix moves a cycle to its engine's latest minor as it is "
    "upgraded; start a cycle on an exact minor, such as spinoza:1.0, to stay on one",
}


_CONTEXT_CYCLED = (
    "declaring the context started a new cycle, which begins fresh learning, "
    "so it can't be undone; declare the context again to change it"
)


def _started_cycle(before: dict | None, after: dict | None) -> bool:
    def cycle_id(loop: dict | None) -> str | None:
        return ((loop or {}).get("cycle") or {}).get("id")

    return cycle_id(before) != cycle_id(after)


_METRIC_ON_LOOP = (
    "this is a loop's record of its metric's change; undo the change on the "
    "metric {name!r}, which undoes it for every loop using it"
)

_METRIC_NEW_SEMANTIC = (
    "a new semantic started a new cycle on every loop using the metric, which "
    "begins fresh learning, so it can't be undone; change the semantic again "
    "instead"
)


def _metric_refusal(before: dict | None, after: dict | None) -> str | None:
    """why a metric's change can't be undone: a loop's record of it is undone
    on the metric, and a new major started cycles."""
    after = after or {}
    if "key" in after:
        return _METRIC_ON_LOOP.format(name=after["metric"]["name"])
    major = (after.get("version") or "").split(".")[0]
    if major != ((before or {}).get("version") or "").split(".")[0]:
        return _METRIC_NEW_SEMANTIC
    return None


def is_undoable(
    kind: str, before: dict | None = None, after: dict | None = None
) -> bool:
    """a kind is undoable or not, except a context change, which is undoable
    unless it started a cycle, and a metric's change, undoable on the metric
    unless it started cycles."""
    if kind == "context.update" and _started_cycle(before, after):
        return False
    if kind == "metric.update" and _metric_refusal(before, after) is not None:
        return False
    return kind in UNDOABLE_KINDS


def not_undoable_reason(
    kind: str, before: dict | None = None, after: dict | None = None
) -> str | None:
    if kind == "context.update" and _started_cycle(before, after):
        return _CONTEXT_CYCLED
    if kind == "metric.update":
        return _metric_refusal(before, after)
    return NOT_UNDOABLE.get(kind)


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
