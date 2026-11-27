from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from proxysvc.core.console import loop_url
from proxysvc.mod.safety.rule import CALLS_STOPPED
from proxysvc.mod.safety.rule import DECISION_ERRORS
from proxysvc.mod.safety.rule import OUTCOMES_NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED
from proxysvc.mod.safety.service import OPENED
from proxysvc.mod.safety.service import RECOVERED
from proxysvc.mod.safety.service import RETIRED

PAUSED_FOR_EVERYONE = "Everyone gets the fallback until a person resumes it."

HEALTHY_AGAIN = {
    OUTCOMES_STOPPED: "is receiving outcomes again.",
    OUTCOMES_NOT_LEARNED: "is learning from its outcomes again.",
    CALLS_STOPPED: "is receiving calls again.",
}


@dataclass(frozen=True, slots=True)
class Notice:
    """an alert as the webhook tells it: its entry (``alert_entry``) and
    whether this is its opening or its ending."""

    entry: dict
    event: str


def duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours = round(seconds / 3600)
    if hours < 48:
        return f"{hours} h"
    return f"{round(seconds / 86400)} days"


def _sentence(pieces: Sequence[dict]) -> str:
    return "".join(p["text"] if p["kind"] == "text" else p["name"] for p in pieces)


def _seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def line(notice: Notice) -> str:
    """one alert in one sentence, in the words people read it in the console."""
    entry = notice.entry
    if notice.event == OPENED:
        found = _sentence(entry["pieces"])
        if entry["signal"] == DECISION_ERRORS:
            found = f"{found} {PAUSED_FOR_EVERYONE}"
        return found

    name = entry["loop"]["name"]
    person = (entry["resolved_by"] or {}).get("name")
    by = f" by {person}" if person else ""
    if entry["signal"] == DECISION_ERRORS:
        verb = "retired" if entry["resolution"] == RETIRED else "resumed"
        took = duration(_seconds(entry["opened_at"], entry["resolved_at"]))
        return f"{name} {verb}{by} after {took} on the fallback."
    if entry["resolution"] == RETIRED:
        return f"{name} was retired{by}, which ends its warning."
    return f"{name} {HEALTHY_AGAIN.get(entry['signal'], 'is healthy again.')}"


def _loops(count: int, verb_one: str, verb_many: str) -> str:
    return f"{count} loop {verb_one}" if count == 1 else f"{count} loops {verb_many}"


def headline(notices: Sequence[Notice], workspace: str) -> str:
    """the first line over several alerts: how many loops each way."""
    opened = {n.entry["loop"]["id"] for n in notices if n.event == OPENED}
    recovered = {n.entry["loop"]["id"] for n in notices if n.event == RECOVERED}
    if not recovered:
        return f"{_loops(len(opened), 'needs a look', 'need a look')} in {workspace}"
    if not opened:
        return (
            f"{_loops(len(recovered), 'is healthy again', 'are healthy again')}"
            f" in {workspace}"
        )
    healthy = "is" if len(recovered) == 1 else "are"
    return (
        f"{workspace}: {_loops(len(opened), 'needs a look', 'need a look')},"
        f" {len(recovered)} {healthy} healthy again"
    )


def _item(notice: Notice, console_origin: str) -> dict:
    entry = notice.entry
    item = {
        "event": notice.event,
        "loop": {"key": entry["loop"]["key"], "name": entry["loop"]["name"]},
        "signal": entry["signal"],
        "value": {k: v for k, v in (entry["evidence"] or {}).items() if k != "signal"},
        "opened_at": entry["opened_at"],
        "url": loop_url(console_origin, entry["loop"]["key"]),
    }
    if notice.event == RECOVERED:
        item["resolved_at"] = entry["resolved_at"]
        item["resolution"] = entry["resolution"]
        item["resolved_by"] = (entry["resolved_by"] or {}).get("name")
    return item


def message(notices: Sequence[Notice], workspace: str, console_origin: str) -> dict:
    """one webhook message for alerts that opened or ended together: a text
    line Slack shows as it is, and the same alerts as data."""
    lines = [
        f"{line(n)} {loop_url(console_origin, n.entry['loop']['key'])}" for n in notices
    ]
    if len(lines) > 1:
        lines.insert(0, headline(notices, workspace))
    return {
        "text": "\n".join(lines),
        "kind": "alert",
        "workspace": {"name": workspace},
        "alerts": [_item(n, console_origin) for n in notices],
    }
