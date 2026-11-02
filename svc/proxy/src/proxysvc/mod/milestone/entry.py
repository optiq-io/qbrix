from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from qbrixstore.event import MilestoneEvent
from qbrixstore.event.milestone import FIRST_SEAL
from qbrixstore.event.milestone import LEADER_CHANGED

FOLD_WITHIN = timedelta(minutes=10)
QBRIX = "qbrix"
ANY_CALLER = "the API"


@dataclass(frozen=True, slots=True)
class LoopName:
    key: str
    name: str


def fold(events: Sequence[MilestoneEvent]) -> list[list[MilestoneEvent]]:
    """consecutive events, newest first, grouped when the same loop reached the
    same kind within the window of the one before."""
    groups: list[list[MilestoneEvent]] = []
    for event in events:
        if groups and _continues(groups[-1][-1], event):
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups


def _continues(newer: MilestoneEvent, older: MilestoneEvent) -> bool:
    return (
        newer.loop_id == older.loop_id
        and newer.kind == older.kind
        and newer.at_ms - older.at_ms <= FOLD_WITHIN.total_seconds() * 1000
    )


def _iso(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, timezone.utc).isoformat()


def _option(options: Sequence[str], index: int | None) -> str | None:
    if index is None or not 0 <= index < len(options):
        return None
    return options[index]


def _leader_pieces(to: str, before: str | None) -> list[dict]:
    pieces: list[dict] = [
        {"kind": "option", "name": to},
        {"kind": "text", "text": " took the lead"},
    ]
    if before:
        pieces += [
            {"kind": "text", "text": " from "},
            {"kind": "option", "name": before},
        ]
    return [*pieces, {"kind": "text", "text": "."}]


def entry(
    group: Sequence[MilestoneEvent], loop: LoopName, options: Sequence[str]
) -> dict | None:
    """one folded group as the sentence the header and agents read, or none
    when it names an option its cycle doesn't have."""
    event = group[0]
    source = QBRIX
    diff: list[dict] = []
    loop_piece = {"kind": "loop", "name": loop.name}

    if event.kind == LEADER_CHANGED:
        to = _option(options, event.payload.get("to"))
        before = _option(options, event.payload.get("from"))
        if to is None:
            return None
        pieces = _leader_pieces(to, before)
        diff = [{"field": "leader", "before": before, "after": to}]
    elif event.kind == FIRST_SEAL:
        pieces = [
            loop_piece,
            {"kind": "text", "text": "'s first window sealed."},
        ]
    else:
        source = event.payload.get("source") or ANY_CALLER
        pieces = [
            {"kind": "text", "text": f"{source} made the first call to "},
            loop_piece,
            {"kind": "text", "text": "."},
        ]

    return {
        "id": event.event_id,
        "kind": event.kind,
        "at": _iso(event.at_ms),
        "first_at": _iso(group[-1].at_ms) if len(group) > 1 else None,
        "count": len(group),
        "loop": {"id": event.loop_id, "key": loop.key, "name": loop.name},
        "cycle_id": event.cycle_id or None,
        "source": source,
        "pieces": pieces,
        "diff": diff,
    }
