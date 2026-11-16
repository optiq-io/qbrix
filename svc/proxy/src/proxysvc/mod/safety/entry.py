from __future__ import annotations

from datetime import datetime
from datetime import timezone

from qbrixstore.postgres.models import Alert

from proxysvc.mod.milestone.entry import LoopName
from proxysvc.mod.people import People
from proxysvc.mod.safety.rule import DECISION_ERRORS
from proxysvc.mod.safety.rule import OUTCOMES_NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED

SAFETY_PAUSE = "safety_pause"
WARNING = "warning"


def kind_of(signal: str) -> str:
    """a decision errors alert is a safety pause; every other is a warning."""
    return SAFETY_PAUSE if signal == DECISION_ERRORS else WARNING


def iso(at: datetime | None) -> str | None:
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.isoformat()


def _text(text: str) -> dict:
    return {"kind": "text", "text": text}


def _pieces(alert: Alert, loop: LoopName) -> list[dict]:
    evidence = alert.evidence or {}
    named = {"kind": "loop", "name": loop.name}
    if alert.signal == DECISION_ERRORS:
        return [
            _text("qbrix paused "),
            named,
            _text(f": {evidence.get('rate', 0):.0%} of its decisions failed."),
        ]
    if alert.signal == OUTCOMES_STOPPED:
        since = evidence.get("decisions_since_outcome", 0)
        return [
            named,
            _text(
                f" stopped receiving outcomes: none in its last {since:,} decisions."
            ),
        ]
    if alert.signal == OUTCOMES_NOT_LEARNED:
        return [
            named,
            _text(
                f" couldn't learn from {evidence.get('rate', 0):.0%} of its outcomes"
                " in the last hour."
            ),
        ]
    return [named, _text(f": {alert.signal}.")]


def _resolved_by(alert: Alert, people: People) -> dict | None:
    if alert.resolved_kind is None:
        return None
    by_qbrix = alert.resolved_kind == "qbrix"
    return {
        "kind": alert.resolved_kind,
        "user_id": None if by_qbrix else alert.resolved_user_id,
        "name": None if by_qbrix else people.name(alert.resolved_user_id),
    }


def alert_entry(alert: Alert, loop: LoopName, people: People) -> dict:
    """an alert as people and agents read it: what is wrong with which loop,
    since when, and how it ended."""
    return {
        "id": alert.id,
        "signal": alert.signal,
        "opened_at": iso(alert.opened_at),
        "resolved_at": iso(alert.resolved_at),
        "resolution": alert.resolution,
        "resolved_by": _resolved_by(alert, people),
        "loop": {"id": alert.loop_id, "key": loop.key, "name": loop.name},
        "cycle_id": alert.cycle_id,
        "evidence": alert.evidence,
        "pieces": _pieces(alert, loop),
    }
