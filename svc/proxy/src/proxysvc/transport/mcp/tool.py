from __future__ import annotations

import json
import math
from collections.abc import Awaitable
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Annotated
from zoneinfo import ZoneInfo
from typing import Any
from typing import Literal
from typing import Optional

from mcp.server.mcpserver import Context
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from mcp_types import InputRequiredResult
from mcp_types import TextContent
from mcp_types import ToolAnnotations
from pydantic import BaseModel
from pydantic import Field

from qbrixcore.engine import ENGINES
from qbrixcore.engine import EngineSpec
from qbrixcore.engine.spec import ACCEPTED_FORMS
from qbrixlog import get_logger

from proxysvc.config import ProxySettings
from proxysvc.core import autonomy
from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeAnsweredError
from proxysvc.core.error import ChangeNoLongerAppliesError
from proxysvc.core.error import ChangeWaitingError
from proxysvc.core.error import ConnectionRateLimitedError
from proxysvc.core.error import CycleNotFoundError
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import LoopStateError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.core.targeting import Operator
from proxysvc.mod.auth.scope import ROLE_SCOPES
from proxysvc.mod.change.applied import Applied
from proxysvc.mod.change.note import NOTE_MAX_LENGTH
from proxysvc.mod.change.note import HistoryShow
from proxysvc.mod.change.proposal import DECLINED
from proxysvc.mod.change.proposal import STATUSES
from proxysvc.mod.change.proposal import Waiting
from proxysvc.mod.change.undo import undo_scope
from proxysvc.mod.connection.service import ConnectionPrincipal
from proxysvc.mod.docs.index import Answer
from proxysvc.mod.docs.index import DocsIndex
from proxysvc.mod.docs.index import link
from proxysvc.mod.docs.page import Section
from proxysvc.mod.engine.catalog import engine_catalog
from proxysvc.mod.loop.delivery import delivery_of
from proxysvc.mod.loop.service import DECIDING
from proxysvc.mod.loop.service import starts_cycle
from proxysvc.mod.metric.serialize import window_label
from proxysvc.mod.safety.read import OPEN_LIMIT
from proxysvc.mod.safety.read import RECOVERED_SHOWN
from proxysvc.mod.safety.rule import CALLS_STOPPED
from proxysvc.mod.safety.rule import DECISION_ERRORS
from proxysvc.mod.safety.rule import OUTCOMES_NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED
from proxysvc.service import ProxyService
from proxysvc.transport.http.router.change import ChangePage
from proxysvc.transport.http.router.engine import EngineList
from proxysvc.transport.http.router.milestone import MilestoneList
from proxysvc.transport.http.router.summary import WeekSummary
from proxysvc.transport.mcp import ask
from proxysvc.transport.mcp import error
from proxysvc.transport.mcp.error import Refusal
from proxysvc.transport.mcp.error import refusals
from proxysvc.transport.mcp.link import change_url
from proxysvc.transport.mcp.link import changes_url
from proxysvc.transport.mcp.link import history_url
from proxysvc.transport.mcp.repeat import RepeatGuard
from proxysvc.transport.mcp.repeat import repeat_key
from proxysvc.transport.mcp.schema import ChangeStatus
from proxysvc.transport.mcp.schema import ChangeUndone
from proxysvc.transport.mcp.schema import ChangeView
from proxysvc.transport.mcp.schema import Detail
from proxysvc.transport.mcp.schema import DocsAnswer
from proxysvc.transport.mcp.schema import DocsHeading
from proxysvc.transport.mcp.schema import DocsSection
from proxysvc.transport.mcp.schema import HistoryPage
from proxysvc.transport.mcp.schema import LoopChanged
from proxysvc.transport.mcp.schema import LoopPage
from proxysvc.transport.mcp.schema import LoopView
from proxysvc.transport.mcp.schema import MetricChanged
from proxysvc.transport.mcp.schema import MetricList
from proxysvc.transport.mcp.schema import NoteAdded
from proxysvc.transport.mcp.schema import PreviewView
from proxysvc.transport.mcp.schema import ResultsView
from proxysvc.transport.mcp.verifier import current_principal
from proxysvc.transport.mcp.wire import wiring

logger = get_logger(__name__)

LIMIT_DEFAULT = 20
DECLINES_SHOWN = 3
CHANGES_LISTED = 5
LIMIT_MAX = 100

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_CREATE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
_DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)

LoopRef = Annotated[str, Field(description="The loop's key or its id.")]
Reason = Annotated[
    str,
    Field(
        min_length=1,
        description="Why you are making this change, in a sentence. "
        "It is recorded in the loop's history.",
    ),
]
DetailArg = Annotated[
    Detail,
    Field(
        description="concise leaves out option config and the share series; "
        "full includes them."
    ),
]


class OptionInput(BaseModel):
    name: str = Field(description="What people call this option.")
    key: Optional[str] = Field(
        default=None,
        description="What code reads; generated from the name when left out.",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="What your code renders for this option, as JSON.",
    )


class ConditionInput(BaseModel):
    property: str = Field(description="A context property, such as device.")
    operator: Operator = Field(
        description="in and not_in take a list; the others take one value."
    )
    value: str | int | float | bool | list[str | int | float | bool]


class ContextPropertyInput(BaseModel):
    name: str = Field(description="The property's name, as the app sends it.")
    type: Literal["categorical", "numeric", "boolean"] = Field(
        description="categorical: one of a few values; numeric: a number in a range; boolean: true or false."
    )
    values: Optional[list[str]] = Field(
        default=None,
        description="categorical only: the values worth telling apart. Any other value counts as other.",
    )
    min: Optional[float] = Field(
        default=None, description="numeric only: the lowest value that matters."
    )
    max: Optional[float] = Field(
        default=None, description="numeric only: the highest value that matters."
    )


class HoursInput(BaseModel):
    start: str = Field(description='Like "09:00": the loop decides from then.')
    end: str = Field(description='Like "18:00": the loop stops deciding then.')


class ScheduleInput(BaseModel):
    hours: Optional[HoursInput] = Field(
        default=None,
        description="Daily hours; past midnight if the start is later. All day when left out.",
    )
    starts_on: Optional[str] = Field(
        default=None,
        description='A date like "2026-12-01" the loop starts deciding on.',
    )
    timezone: Optional[str] = Field(
        default=None,
        description='Like "Europe/Amsterdam"; required with hours or a start date.',
    )


class ScoreRange(BaseModel):
    lo: float
    hi: float


def _text(result: CallToolResult) -> str:
    return result.content[0].text


def _result(text: str, model: BaseModel) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=model.model_dump(mode="json"),
    )


def _refused(refusal: Refusal) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=str(refusal))], is_error=True
    )


def _require(principal: ConnectionPrincipal, scope: str, verb: str) -> None:
    if scope not in ROLE_SCOPES.get(principal.role, ()):
        raise error.role(verb)


_LEVEL_PHRASES = {
    "ask": "ask first",
    "notify": "act and notify",
    "own": "act on your own",
}


def _autonomy_line(levels: dict[str, str]) -> str:
    """this connection's levels on a loop, as the tools they apply to."""
    parts = []
    for level, phrase in _LEVEL_PHRASES.items():
        tools = [kind.replace(".", "_") for kind, at in levels.items() if at == level]
        if tools:
            parts.append(f"{phrase}: {', '.join(tools)}")
    return f"Your autonomy here: {'; '.join(parts)}"


def _who(entry: dict | None) -> str:
    if entry is None:
        return ""
    who = entry["who"]
    name = "qbrix" if who["kind"] == "qbrix" else who["name"]
    via = entry.get("via")
    return f"{name} via {via['client']}" if via else name


def _concise(loop: dict, detail: Detail) -> dict:
    if detail == "full":
        return loop
    return {
        **loop,
        "options": [{**option, "config": None} for option in loop["options"]],
    }


def _context_line(loop: dict) -> str:
    context = loop.get("context")
    if not context:
        return "Learns from: no context."
    return f"Learns from: {', '.join(prop['name'] for prop in context)}."


def _engine_hold_line(cycle: dict) -> str:
    spec = EngineSpec.parse(cycle["engine"])
    title = ENGINES.get(spec).title()
    if spec.minor is not None:
        return f"it now stays on {title} {cycle['engine_version']}"
    return f"it now follows {title} {spec.major} and runs {cycle['engine_version']}"


def _arrival_line(read: dict) -> str:
    """what the app must send, against what the loop's decisions carried."""
    parts = []
    for prop in read["properties"]:
        if prop["arrived"] == 0:
            parts.append(f"{prop['name']} not arriving yet")
        elif prop["readable"] < prop["arrived"]:
            parts.append(
                f"{prop['name']} arriving, but {prop['arrived'] - prop['readable']} "
                f"of {prop['arrived']} values aren't {prop['type']} and are learned "
                f"as its default (last: {json.dumps(prop['last_value'])})"
            )
        else:
            parts.append(f"{prop['name']} arriving in {prop['arrived']}")
    line = f"Of {read['decisions']} decisions in the last day: " + (
        "; ".join(parts) or "no properties declared"
    )
    if read["undeclared"]:
        line += ". Sent but not declared: " + ", ".join(
            prop["name"] for prop in read["undeclared"]
        )
    return line + "."


def _loop_line(loop: dict) -> str:
    state = loop["state"]
    if loop.get("committed"):
        state += f" to {loop['committed']}"
    line = f"{loop['key']} · {loop['name']} · {state} · metric {loop['metric']['name']}"
    if loop.get("cycle"):
        line += f" · cycle {loop['cycle']['number']}"
    return line


_OPERATOR_PHRASES = {
    "is": "is",
    "is_not": "is not",
    "in": "in",
    "not_in": "not in",
    "contains": "contains",
    "not_contains": "doesn't contain",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
}


def _value_phrase(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_value_phrase(item) for item in value)
    return json.dumps(value) if isinstance(value, bool) else str(value)


def _delivery_line(loop: dict, now: datetime) -> str:
    """who the loop decides for and what everyone else gets, in one line, with
    why it isn't deciding right now if its schedule says so."""
    delivery = delivery_of(loop["delivery"])
    fallback = f"Everyone else gets {loop['fallback']}."
    if delivery.everyone:
        return f"Decides for: everyone, always. {fallback}"
    parts = [
        " and ".join(
            f"{c.property} {_OPERATOR_PHRASES[c.operator]} {_value_phrase(c.value)}"
            for c in delivery.audience
        )
        or "everyone"
    ]
    if delivery.rollout < 100:
        parts.append(f"{delivery.rollout}% of them")
    schedule = delivery.schedule
    if schedule.hours is not None:
        parts.append(f"{schedule.hours.start}–{schedule.hours.end} {schedule.timezone}")
    if schedule.starts_on is not None:
        parts.append(f"from {schedule.starts_on.isoformat()}")
    line = f"Decides for: {' · '.join(parts)}. {fallback}"
    if loop["state"] in ("live", "committed") and not schedule.open(now):
        local = now.astimezone(ZoneInfo(schedule.timezone))
        waiting = (
            f"it starts on {schedule.starts_on.isoformat()}"
            if schedule.starts_on is not None and local.date() < schedule.starts_on
            else "it is outside its hours"
        )
        line += f" Right now everyone gets {loop['fallback']}: {waiting}."
    return line


def _decision_errors(entry: dict) -> dict | None:
    evidence = entry.get("evidence") or {}
    return evidence if evidence.get("signal") == DECISION_ERRORS else None


def _failed(evidence: dict) -> str:
    return f"{evidence['rate']:.1%} of {evidence['calls']} calls"


def _paused_line(state: str, entry: dict | None) -> str | None:
    """who paused a paused loop, when and why, from the change that paused it."""
    if state != "paused" or not entry or entry["kind"] != "loop.pause":
        return None
    at = datetime.fromisoformat(entry["at"])
    at = at.astimezone(timezone.utc) if at.tzinfo else at
    line = f"Paused by {_who(entry)} at {at:%Y-%m-%d %H:%M} UTC"
    evidence = _decision_errors(entry)
    if evidence:
        start = datetime.fromisoformat(evidence["window_start"])
        end = datetime.fromisoformat(evidence["window_end"])
        minutes = max(1, math.ceil((end - start).total_seconds() / 60))
        reasons = ", ".join(
            f"{reason} {count}" for reason, count in evidence["reasons"].items()
        )
        line += f": {_failed(evidence)} failed over {minutes} minutes"
        if reasons:
            line += f" ({reasons})"
    elif entry.get("reason"):
        line += f": {entry['reason']}"
    return f"{line}. Everyone gets the fallback until a person resumes it."


def _sentence(entry: dict) -> str:
    words = []
    for piece in entry["pieces"]:
        if piece["kind"] == "actor":
            words.append(piece["actor"].get("name") or "qbrix")
        else:
            words.append(piece.get("text") or piece.get("name") or "")
    return "".join(words)


def waiting_text(entry: dict, url: str) -> str:
    return (
        f"Waiting for approval: {_sentence(entry)} Nothing has changed yet. "
        f"{entry['who']['name']} approves or declines it in qbrix; find its "
        f"answer with change_get. Change {entry['id']}: {url}"
    )


Answered = Callable[
    [ConnectionPrincipal, ChangeStatus, dict, dict], Awaitable[BaseModel]
]


def _difference_line(difference: dict) -> str:
    before = difference["before"]
    after = difference["after"]
    if before is None:
        return f"{difference['field']} + {after}"
    if after is None:
        return f"{difference['field']} - {before}"
    return f"{difference['field']} {before} -> {after}"


def _change_line(entry: dict) -> str:
    parts = [entry["at"], _sentence(entry)]
    if entry["note"] is not None:
        parts.append(f"note {json.dumps(entry['note'], ensure_ascii=False)}")
    if entry["via"]:
        parts.append(_who(entry))
    parts += [_difference_line(difference) for difference in entry["diff"]]
    evidence = _decision_errors(entry)
    if evidence:
        parts.append(f"decision errors {_failed(evidence)}")
    if entry["reason"]:
        parts.append(f'"{entry["reason"]}"')
    decision = entry.get("decision")
    if entry["status"] == "waiting":
        parts.append("waiting for approval")
    elif decision and decision["answer"] == "declined":
        declined = f"declined by {decision['who']['name']} in {decision['where']}"
        if decision["reason"]:
            declined += f': "{decision["reason"]}"'
        parts.append(declined)
    elif decision:
        parts.append(f"approved by {decision['who']['name']} in {decision['where']}")
    if entry["undone_by"]:
        parts.append(f"undone by {_who(entry['undone_by'])}")
    elif entry["undoable"]:
        parts.append("can be undone")
    parts.append(f"change {entry['id']}")
    return " · ".join(parts)


def _mention_line(entry: dict) -> str:
    """a pull request or commit that mentions the loop, as one line."""
    if entry["kind"] == "commit":
        sentence = (
            f"Commit {entry['repository']}@{entry['sha'][:7]} by {entry['author']}"
        )
    elif entry["state"] == "merged":
        sentence = (
            f"Pull request {entry['repository']}#{entry['number']} merged by "
            f"{entry['merged_by'] or entry['author']}"
        )
    elif entry["state"] == "closed":
        sentence = (
            f"Pull request {entry['repository']}#{entry['number']} by "
            f"{entry['author']}, closed"
        )
    else:
        sentence = (
            f"Pull request {entry['repository']}#{entry['number']} opened by "
            f"{entry['author']}"
        )
    return f"{entry['at']} · {sentence}: {entry['title']} · {entry['url']}"


def _merged_line(pull_request: dict, level: str) -> str:
    """a draft's merged pull request, and how its launch goes from here."""
    launch = "Launch it with loop_launch" + (
        "; launching asks your person first." if level == "ask" else "."
    )
    return (
        f"Its pull request {pull_request['repository']}#{pull_request['number']} "
        f"merged at {pull_request['merged_at']}: {pull_request['title']} · "
        f"{pull_request['url']}. {launch}"
    )


def _mention_hint(key: str) -> str:
    return (
        f"Put qbrix:{key} in the title or description of the pull requests you "
        f"open for this loop, or qbrix/{key} in the branch name, so they appear "
        "in its history."
    )


def _history_line(entry: dict) -> str:
    return _mention_line(entry) if entry["type"] == "mention" else _change_line(entry)


def _milestone_line(milestone: dict) -> str:
    sentence = "".join(
        piece.get("text") or piece.get("name") or "" for piece in milestone["pieces"]
    )
    return f"{milestone['at']} · {sentence}"


def _moment(iso: str, *, time: bool = False) -> str:
    at = datetime.fromisoformat(iso)
    at = at.astimezone(timezone.utc) if at.tzinfo else at
    return f"{at.day} {at:%b %H:%M} UTC" if time else f"{at.day} {at:%b}"


def _percent(share: float | None) -> str:
    return "-" if share is None else f"{share:.0%}"


def _wait(seconds: float) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds / size:.3g}{unit}"
    return f"{seconds:.0f}s"


def _arrival(health: dict) -> str:
    """how a metric's outcomes arrive, for its line in the list."""
    rate = f"{health['outcomes_per_minute']:.3g} outcomes a minute"
    if health["median_wait_seconds"] is None:
        return rate
    return (
        f"{rate} · half within {_wait(health['median_wait_seconds'])}"
        f" · {_percent(health['late_share'])} late"
    )


def _shares(options: list[dict]) -> dict[str, float]:
    return {option["key"]: option["share"] or 0.0 for option in options}


def _moved(loop: dict) -> float:
    """the largest change in any option's share between then and now."""
    then, now = loop["share"]["then"], loop["share"]["now"]
    if not then or not now:
        return 0.0
    before, after = _shares(then["options"]), _shares(now["options"])
    return max(
        (abs(after.get(key, 0.0) - before.get(key, 0.0)) for key in before | after),
        default=0.0,
    )


def _open_alert(loop: dict) -> bool:
    return any(alert["resolved_at"] is None for alert in loop["alerts"])


def _options_share(at: dict) -> str:
    if all(o["share"] is None for o in at["options"]):
        return "no decisions in the day before"
    return ", ".join(f"{o['name']} {_percent(o['share'])}" for o in at["options"])


def _week_share(loop: dict, since: str) -> str:
    then, now = loop["share"]["then"], loop["share"]["now"]
    if then and now and then["cycle"] == now["cycle"]:
        before = {o["key"]: o["share"] for o in then["options"]}
        return (
            ", ".join(
                f"{o['name']} {_percent(before.get(o['key']))} → {_percent(o['share'])}"
                for o in now["options"]
            )
            + f" since {_moment(since)}"
        )
    parts = []
    if then:
        parts.append(
            f"cycle {then['cycle']} at {_moment(since)}: {_options_share(then)}"
        )
    if now:
        parts.append(f"cycle {now['cycle']} now: {_options_share(now)}")
    return "; ".join(parts) or "no decisions yet"


_SIGNAL_WORDS = {
    DECISION_ERRORS: "qbrix paused it",
    OUTCOMES_STOPPED: "outcomes stopped",
    OUTCOMES_NOT_LEARNED: "outcomes not learned",
    CALLS_STOPPED: "calls stopped",
}

_CLEARED_WORDS = {
    OUTCOMES_STOPPED: "outcomes arriving again",
    OUTCOMES_NOT_LEARNED: "outcomes learned again",
    CALLS_STOPPED: "calls arriving again",
}


def _signal_words(signal: str) -> str:
    return _SIGNAL_WORDS.get(signal, signal.replace("_", " "))


def _alert_value(alert: dict) -> str:
    """the signal's value from the alert's evidence, in product words."""
    evidence = alert["evidence"] or {}
    signal = alert["signal"]
    if signal == OUTCOMES_STOPPED:
        value = (
            f"{evidence.get('decisions_since_outcome', 0):,} decisions "
            "since the last outcome"
        )
        usual = evidence.get("usual_decisions_per_outcome")
        return value + (
            f"; usually one every {usual:g}" if usual else "; none yet this cycle"
        )
    if signal == OUTCOMES_NOT_LEARNED:
        reasons = ", ".join(
            f"{reason} {count}"
            for reason, count in (evidence.get("reasons") or {}).items()
        )
        return (
            f"{evidence.get('rate', 0):.0%} of the last hour's "
            f"{evidence.get('outcomes', 0):,} outcomes couldn't be learned from"
            + (f" ({reasons})" if reasons else "")
        )
    if signal == CALLS_STOPPED:
        since = evidence.get("silent_since")
        value = f"no calls since {_moment(since, time=True)}" if since else "no calls"
        return (
            f"{value}; {evidence.get('calls_same_hour_yesterday', 0):,} in the same"
            " hour yesterday"
        )
    if signal == DECISION_ERRORS and "calls" in evidence:
        return f"{_failed(evidence)} failed"
    return ""


def _sentence_of(alert: dict) -> str:
    value = _alert_value(alert)
    return f"{_signal_words(alert['signal'])}." + (f" {value}." if value else "")


def _lasted(alert: dict) -> str:
    opened = datetime.fromisoformat(alert["opened_at"])
    ended = datetime.fromisoformat(alert["resolved_at"])
    minutes = max(0, int((ended - opened).total_seconds() // 60))
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes:02d}m"
    return f"{hours // 24} days"


def _how_it_ended(alert: dict) -> str:
    resolution = alert["resolution"]
    if resolution == "retired":
        return "the loop was retired"
    if resolution == "resumed":
        by = alert["resolved_by"] or {}
        who = by.get("name") or "qbrix"
        if by.get("kind") == "connection":
            who += " through a connection"
        return f"resumed by {who}"
    return _CLEARED_WORDS.get(alert["signal"], "healthy again")


def _needs_a_look_line(alert: dict) -> str:
    """an open alert, first in what an agent reads about its loop."""
    return (
        f"Needs a look since {_moment(alert['opened_at'], time=True)}: "
        f"{_sentence_of(alert)}"
    )


def _recovered_line(alert: dict) -> str:
    """an alert that ended: when, how, and how long it was open."""
    verb = "Ended" if alert["resolution"] == "retired" else "Recovered"
    return (
        f"{verb} {_moment(alert['resolved_at'], time=True)}: "
        f"{_how_it_ended(alert)}, after {_lasted(alert)} "
        f"({_signal_words(alert['signal'])})."
    )


def _alert_line(alert: dict) -> str:
    if alert["resolved_at"] is None:
        return _needs_a_look_line(alert)
    return _recovered_line(alert)


def _list_alerts_line(alerts: list[dict]) -> str:
    return f"needs a look ({', '.join(_signal_words(a['signal']) for a in alerts)})"


def _group_line(group: dict) -> str:
    who = group["who"]["name"] or "qbrix"
    if group["via"]:
        who += f" via {group['via']}"
    shown = []
    for entry in group["changes"][:CHANGES_LISTED]:
        part = f"{entry['kind']} {_moment(entry['at'])}"
        if entry["note"] is not None:
            part += f" {json.dumps(entry['note'], ensure_ascii=False)}"
        elif entry["reason"]:
            part += f' "{entry["reason"]}"'
        shown.append(part)
    more = group["count"] - len(shown)
    return (
        f"{who} ({group['count']}): "
        + "; ".join(shown)
        + (f"; and {more} more" if more > 0 else "")
    )


def _week_lines(week: dict) -> list[str]:
    """the week in product words: a header, then each loop with an open safety
    pause first and the others by how far their share moved."""
    states = {state: 0 for state in ("live", "paused", "committed")}
    for loop in week["loops"]:
        states[loop["state"]] += 1
    drafts = week["drafts"]
    counts = week["changes"]
    header = (
        f"Since {_moment(week['since'], time=True)}: "
        + ", ".join(f"{n} {state}" for state, n in states.items())
        + f" loops; {drafts['count']} drafts"
    )
    if drafts["older_than_7_days"]:
        header += ", created over 7 days ago: " + ", ".join(
            draft["key"] for draft in drafts["older_than_7_days"]
        )
    who = counts["who"]
    header += (
        f". {counts['total']} changes: {who['member']} by people, "
        f"{who['connection']} through connections, {who['qbrix']} by qbrix; "
        f"{counts['undone']} undone."
    )
    lines = [header]
    ordered = sorted(
        week["loops"], key=lambda loop: (not _open_alert(loop), -_moved(loop))
    )
    for loop in ordered:
        state = loop["state"]
        if loop["committed"]:
            state += f" to {loop['committed']}"
        lift = (
            f"lift over an even split {loop['lift']:+.1%}"
            + (" (early)" if loop["early"] else "")
            if loop["lift"] is not None
            else "lift not yet"
        )
        lines.append(
            f"{loop['name']} ({loop['key']}) · {state} · {loop['metric']['name']}: "
            f"{_week_share(loop, week['since'])}; {lift}"
        )
        lines += [f"  {_alert_line(alert)}" for alert in loop["alerts"]]
        lines += [
            f"  {_moment(m['at'])} · "
            + "".join(p.get("text") or p.get("name") or "" for p in m["pieces"])
            for m in loop["milestones"]
        ]
        lines += [f"  {_group_line(group)}" for group in loop["changes"]]
    if not week["loops"]:
        lines.append("No live, paused or committed loops.")
    return lines


_EXCLUDED_BY = {
    "schedule": "it is outside the schedule",
    "rollout": "the unit is outside the rollout",
}

_REASON_LINES = {
    "draft": "A draft: it gets the fallback",
    "paused": "Paused: it gets the fallback",
    "retired": "Retired: it gets the fallback",
}


def _preview_text(preview: dict) -> str:
    reason = preview["reason"]
    option = preview["option"]
    excluded = preview["excluded_by"]
    if excluded is not None:
        condition = excluded["condition"]
        why = (
            f"{condition['property']} {_OPERATOR_PHRASES[condition['operator']]} "
            f"{_value_phrase(condition['value'])} doesn't hold"
            if condition is not None
            else _EXCLUDED_BY[excluded["part"]]
        )
        lines = [f"Outside delivery: {why}. It gets the fallback, {option['key']}."]
    elif reason in _REASON_LINES:
        lines = [f"{_REASON_LINES[reason]}, {option['key']}."]
    elif reason == "committed":
        lines = [f"Committed, inside delivery: it gets {option['key']}."]
    else:
        share = preview["share"]
        shared = _share_line(share["options"]) if share else ""
        lines = [
            "Live, inside delivery: the engine decides.",
            f"Share, last day: {shared or 'no decisions yet'}.",
        ]
    if preview["defaults"]:
        lines.append(
            f"Learned as their default (missing or the wrong type): "
            f"{', '.join(preview['defaults'])}."
        )
    lines.append("Nothing was recorded.")
    return "\n".join(lines)


def _share_line(share: list[dict]) -> str:
    return ", ".join(
        f"{item['key']} {item['share']:.0%}"
        for item in share
        if item.get("share") is not None
    )


def _docs_heading(section: Section) -> str:
    return " › ".join((section.page_title, *section.path[-2:]))


def _docs_lines(answer: Answer) -> list[str]:
    lines = [
        "From this install's docs. Links open the website's version, which may be newer."
    ]
    if answer.outline is not None:
        lines.append("")
        lines.append("Outline:")
        lines.extend(
            f"- {' › '.join(heading.path) or heading.page_title} · {link(heading)}"
            for heading in answer.outline
        )
    for section in answer.sections:
        lines.extend(
            ["", f"## {_docs_heading(section)}", link(section), "", section.text]
        )
    if answer.truncated:
        lines.append("")
        lines.append(
            "More than fits in one answer: search for a section by its heading."
            if answer.outline is not None
            else "More matched than fits in one answer: search with more specific "
            "words, or read a page with page=."
        )
    return lines


def _docs_answer(answer: Answer) -> DocsAnswer:
    return DocsAnswer(
        sections=[
            DocsSection(
                page=section.slug,
                page_title=section.page_title,
                path=list(section.path),
                anchor=section.anchor,
                url=link(section),
                text=section.text,
            )
            for section in answer.sections
        ],
        truncated=answer.truncated,
        outline=(
            None
            if answer.outline is None
            else [
                DocsHeading(
                    path=list(heading.path), anchor=heading.anchor, url=link(heading)
                )
                for heading in answer.outline
            ]
        ),
    )


def register(
    server: MCPServer,
    settings: ProxySettings,
    service: Callable[[], ProxyService],
    docs: DocsIndex,
) -> None:
    """add the tools to the server, in the order tools/list returns them."""

    def repeats() -> RepeatGuard:
        return RepeatGuard(service().redis.client)

    async def refused_loop(principal: ConnectionPrincipal, ref: str) -> Refusal:
        return error.unknown_loop(ref, await service().loop_keys(principal.tenant_id))

    async def refused_metric(principal: ConnectionPrincipal, ref: str) -> Refusal:
        metrics = await service().list_metrics(principal.tenant_id)
        return error.unknown_metric(ref, [metric["name"] for metric in metrics])

    async def once(
        tool: str,
        arguments: dict[str, Any],
        call: Callable[[ConnectionPrincipal], Awaitable[CallToolResult]],
        ctx: Context,
        answered: Answered,
    ) -> CallToolResult | InputRequiredResult:
        """a change call, run once per connection and arguments in the window.
        a repeat counts as a change, so retrying can't get around the cap.

        a change that waits is asked in the chat when the client can ask; the
        call that carries the answer is the same change, so it neither counts
        again nor meets the repeat guard."""
        principal = current_principal()
        key = repeat_key(principal.actor.connection_id, tool, arguments)
        if ctx.request_state is not None:
            try:
                return await answer(principal, ctx, key, answered)
            except Refusal as refusal:
                return _refused(refusal)

        async def first() -> dict[str, Any]:
            result = await call(principal)
            return {"text": _text(result), "structured": result.structured_content}

        try:
            await service().connections.count_change(principal.actor.connection_id)
        except ConnectionRateLimitedError as e:
            return _refused(error.too_many_changes(e.limit, e.retry_after))
        try:
            stored = await repeats().once(key, first)
        except Refusal as refusal:
            return _refused(refusal)
        structured = stored["structured"] or {}
        if structured.get("status") == "waiting" and ask.can_ask(ctx):
            return await question(principal, structured["change"]["id"])
        return CallToolResult(
            content=[TextContent(type="text", text=stored["text"])],
            structured_content=stored["structured"],
        )

    async def question(
        principal: ConnectionPrincipal, change_id: str
    ) -> InputRequiredResult:
        """the waiting change, put to its person on the client's screen."""
        entry = await service().get_change_entry(principal.tenant_id, change_id)
        return InputRequiredResult(
            input_requests=ask.question(_sentence(entry), entry.get("reason")),
            request_state=ask.seal(change_id, principal.actor.connection_id),
        )

    async def answer(
        principal: ConnectionPrincipal, ctx: Context, key: str, answered: Answered
    ) -> CallToolResult:
        """the person's answer to a question this connection was asked."""
        try:
            change_id, connection_id = ask.unseal(ctx.request_state)
        except ValueError as e:
            raise error.not_asked_here() from e
        if connection_id != principal.actor.connection_id:
            raise error.not_asked_here()
        reply = ask.read(ctx.input_responses)
        tenant_id = principal.tenant_id
        if reply.verdict == "closed":
            entry = await service().get_change_entry(tenant_id, change_id)
        else:
            person = Actor.member(
                principal.actor.user_id, request_id=principal.actor.request_id
            )
            where = principal.actor.client_name
            try:
                if reply.verdict == "approve":
                    entry = await service().approve_change(
                        tenant_id,
                        change_id,
                        actor=person,
                        role=principal.role,
                        where=where,
                    )
                else:
                    entry = await service().decline_change(
                        tenant_id,
                        change_id,
                        actor=person,
                        where=where,
                        reason=reply.reason,
                    )
            except ChangeAnsweredError as e:
                found = await service().get_change_entry(tenant_id, change_id)
                raise error.answered(found) from e
            except ChangeNoLongerAppliesError as e:
                raise error.no_longer_applies(e) from e
            await repeats().forget(key)
        if entry is None:
            raise error.unknown_change(change_id)
        return await respond(principal, entry, answered)

    async def respond(
        principal: ConnectionPrincipal, entry: dict, answered: Answered
    ) -> CallToolResult:
        """a change as its person left it: applied, declined, or still waiting."""
        status: ChangeStatus = (
            entry["status"] if entry["status"] in ("waiting", "declined") else "applied"
        )
        target = entry["target"]
        if status == "applied" and target["type"] in ("loop", "metric"):
            url = change_url(
                settings.console_origin,
                target["type"],
                target["key"] or target["name"] or target["id"],
                entry["id"],
            )
        else:
            url = changes_url(settings.console_origin, entry["id"])
        change = {
            "id": entry["id"],
            "kind": entry["kind"],
            "undoable": entry["undoable"],
            "url": url,
        }
        model = await answered(principal, status, change, entry)
        decision = entry.get("decision")
        if status == "waiting":
            return _result(waiting_text(entry, url), model)
        if status == "declined":
            text = (
                f"Declined by {decision['who']['name']} in {decision['where']}"
                + (f': "{decision["reason"]}"' if decision["reason"] else "")
                + f". Nothing changed: {_sentence(entry)} Read the reason before "
                f"proposing this again. Change {entry['id']}: {url}"
            )
            return _result(text, model)
        undo = "can be undone" if entry["undoable"] else "can't be undone"
        return _result(
            f"Approved by {decision['who']['name']} in {decision['where']}: "
            f"{_sentence(entry)} Change {entry['id']}, {undo}: {url}",
            model,
        )

    async def loop_answered(
        principal: ConnectionPrincipal,
        status: ChangeStatus,
        change: dict,
        entry: dict,
    ) -> BaseModel:
        target = entry["target"]
        loop = (
            await service().get_loop(principal.tenant_id, target["id"])
            if target["type"] == "loop"
            else None
        )
        return LoopChanged(status=status, change=change, loop=loop)

    async def metric_answered(
        principal: ConnectionPrincipal,
        status: ChangeStatus,
        change: dict,
        entry: dict,
    ) -> BaseModel:
        target = entry["target"]
        metric = (
            await service().get_metric(principal.tenant_id, target["name"])
            if target["type"] == "metric" and target["name"]
            else None
        )
        return MetricChanged(status=status, change=change, metric=metric)

    async def note_answered(
        principal: ConnectionPrincipal,
        status: ChangeStatus,
        change: dict,
        entry: dict,
    ) -> BaseModel:
        return NoteAdded(status=status, change=change, note=entry)

    async def undo_answered(
        principal: ConnectionPrincipal,
        status: ChangeStatus,
        change: dict,
        entry: dict,
    ) -> BaseModel:
        return ChangeUndone(status=status, change=change, undone=entry)

    async def latest_pause(tenant_id: str, loop: dict) -> dict | None:
        """the change that paused a paused loop, though others came after it."""
        if loop["state"] != "paused":
            return None
        latest = loop.get("latest_change")
        if latest and latest["kind"] == "loop.pause":
            return latest
        page = await service().list_workspace_changes(
            tenant_id, kinds=["loop.pause"], loop=loop["id"], fold=False, limit=1
        )
        return page["changes"][0] if page["changes"] else None

    async def make(
        principal: ConnectionPrincipal,
        kind: str,
        ref: str | None,
        args: dict[str, Any],
        *,
        reason: str | None = None,
        also: tuple[str, ...] = (),
    ) -> Applied | Waiting | None:
        """a change at this connection's level for its kind, or the strictest
        of the kinds it is also."""
        try:
            return await service().act(
                principal.tenant_id,
                kind,
                ref,
                args,
                actor=principal.acting(kind, *also),
                reason=reason,
            )
        except ChangeWaitingError as e:
            raise error.already_waiting(e) from e

    async def asked(
        principal: ConnectionPrincipal,
        waiting: dict,
        result: Callable[[dict, dict], BaseModel],
    ) -> CallToolResult:
        """a change that waits for its person, and where they answer it."""
        url = changes_url(settings.console_origin, waiting["id"])
        change = {**waiting, "url": url}
        entry = await service().get_change_entry(principal.tenant_id, change["id"])
        return _result(waiting_text(entry, url), result(change, entry))

    def changed(applied: Applied, target: Literal["loop", "metric"], ref: str) -> dict:
        return {
            **applied.change,
            "url": change_url(
                settings.console_origin, target, ref, applied.change["id"]
            ),
        }

    async def loops_list(
        state: Annotated[
            Optional[list[Literal["draft", "live", "committed", "paused", "retired"]]],
            Field(description="Only loops in these states; all loops when left out."),
        ] = None,
        cursor: Annotated[
            Optional[str],
            Field(description="next_cursor from the previous page."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
        detail: DetailArg = "concise",
    ) -> Annotated[CallToolResult, LoopPage]:
        """List the workspace's loops, newest first: each loop's key, name, state, metric, whether it needs a look and why (its open alerts), share of decisions now, and its latest change with who made it."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read loops")
            with refusals():
                page = await service().list_loops(
                    principal.tenant_id,
                    states=state or (),
                    cursor=cursor,
                    limit=limit,
                )
        except Refusal as refusal:
            return _refused(refusal)
        loops = [_concise(loop, detail) for loop in page["loops"]]
        lines = []
        for loop in loops:
            line = _loop_line(loop)
            if loop["alerts"]:
                line += f" · {_list_alerts_line(loop['alerts'])}"
            share = _share_line((loop.get("results") or {}).get("share") or [])
            if share:
                line += f" · share {share}"
            latest = loop.get("latest_change")
            if latest:
                line += f" · latest {latest['kind']} by {_who(latest)}"
                evidence = _decision_errors(latest)
                if evidence:
                    line += f" · decision errors {_failed(evidence)}"
            lines.append(line)
        if not lines:
            lines.append("No loops yet. Create one with loop_create.")
        if page["next_cursor"]:
            lines.append(f"More loops: call again with cursor {page['next_cursor']}.")
        return _result(
            "\n".join(lines),
            LoopPage(loops=loops, next_cursor=page["next_cursor"]),
        )

    async def loop_get(
        loop: LoopRef, detail: DetailArg = "concise"
    ) -> Annotated[CallToolResult, LoopView]:
        """Read one loop, leading with what needs a look: each open alert (outcomes stopped, outcomes not learned, or a safety pause) with its value, then alerts that recovered in the last 7 days. Then its purpose, options, metric, owner, who it decides for (its delivery) and what everyone else gets (its fallback), state (and the option it is committed to, if committed) and current cycle, its latest change, who paused it, when and why if it is paused, this connection's autonomy for each change to the loop, its most recent declined changes with the reasons given, on a draft the pull request mentioning it that merged (launch it then), how to mention it in the pull requests you open for it, and how to wire it: the select and outcome calls for this loop in Python and JavaScript."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read loops")
            found = await service().get_loop(principal.tenant_id, loop)
            if found is None:
                raise await refused_loop(principal, loop)
        except Refusal as refusal:
            return _refused(refusal)
        wire = wiring(found, settings.public_origin)
        levels = {kind: principal.level(kind) for kind in autonomy.ON_LOOP}
        declined = await service().list_workspace_changes(
            principal.tenant_id,
            loop=found["id"],
            statuses=[DECLINED],
            fold=False,
            limit=DECLINES_SHOWN,
        )
        declines = declined["changes"]
        lately = await service().list_alerts(
            principal.tenant_id,
            loop=found["id"],
            limit=OPEN_LIMIT,
            since=datetime.now(timezone.utc) - RECOVERED_SHOWN,
        )
        open_alerts = [a for a in lately["alerts"] if a["resolved_at"] is None][::-1]
        recovered = sorted(
            (a for a in lately["alerts"] if a["resolved_at"] is not None),
            key=lambda a: a["resolved_at"],
            reverse=True,
        )
        merged = (
            await service().github.merged_pull_request(principal.tenant_id, found["id"])
            if found["state"] == "draft"
            else None
        )
        view = LoopView(
            **_concise(found, detail),
            alerts=open_alerts,
            recovered=recovered,
            wire=wire,
            autonomy=levels,
            declined=declines,
            merged_pull_request=merged,
        )
        options = "\n".join(
            f"- {option['key']}: {option['name']}"
            + (f" {json.dumps(option['config'])}" if detail == "full" else "")
            for option in found["options"]
        )
        paused = _paused_line(
            found["state"], await latest_pause(principal.tenant_id, found)
        )
        looks = [
            _needs_a_look_line(alert)
            for alert in open_alerts
            if not (paused and alert["signal"] == DECISION_ERRORS)
        ]
        text = (
            "".join(f"{line}\n" for line in looks)
            + f"{_loop_line(found)}\n"
            + (f"{paused}\n" if paused else "")
            + (
                f"{_merged_line(merged, principal.level('loop.launch'))}\n"
                if merged
                else ""
            )
            + "".join(f"{_recovered_line(alert)}\n" for alert in recovered)
            + f"Purpose: {found['purpose'] or '(none)'}\n"
            f"{_delivery_line(found, datetime.now(timezone.utc))}\n"
            f"{_context_line(found)}\n"
            f"Owner: {found['owner']['name']} · engine {found['engine']}\n"
            f"{_autonomy_line(levels)}\n"
            + (
                "Declined recently, read before proposing again:\n"
                + "\n".join(f"- {_change_line(entry)}" for entry in declines)
                + "\n"
                if declines
                else ""
            )
            + (
                f"{_mention_hint(found['key'])}\n"
                if found["state"] != "retired"
                else ""
            )
            + f"Options:\n{options}\n\n"
            f"Wire it in Python:\n```python\n{wire['python']}```\n\n"
            f"Or in JavaScript:\n```javascript\n{wire['javascript']}```"
        )
        return _result(text, view)

    async def loop_results(
        loop: LoopRef,
        cycle: Annotated[
            Optional[int],
            Field(
                ge=1, description="The cycle's number; the current cycle when left out."
            ),
        ] = None,
        range: Annotated[
            Literal["24h", "7d"],
            Field(description="How far back share reaches."),
        ] = "24h",
        detail: DetailArg = "concise",
    ) -> Annotated[CallToolResult, ResultsView]:
        """Read a loop's results for one cycle: each option's share of decisions, lift over an even split (marked early while its range is filling), decisions waiting to seal, calls by state, and health, led by the loop's open alerts."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read loops")
            try:
                with refusals():
                    results = await service().loop_results(
                        principal.tenant_id, loop, cycle_number=cycle, period=range
                    )
            except CycleNotFoundError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                last = found["cycle"]["number"] if found and found["cycle"] else None
                raise error.no_cycle(
                    found["key"] if found else loop, cycle, last
                ) from e
            if results is None:
                raise await refused_loop(principal, loop)
        except Refusal as refusal:
            return _refused(refusal)
        if detail == "concise" and results["share"]:
            results = {**results, "share": {**results["share"], "series": None}}
        lines = [_needs_a_look_line(alert) for alert in results["health"]["alerts"]]
        if results["cycle"] is None:
            lines.append("A draft: no decisions yet. Launch it with loop_launch.")
        else:
            lines.append(
                f"Cycle {results['cycle']['number']} · last {results['range']}"
            )
        share = results["share"]
        if share:
            lines.append(
                f"Share: {_share_line(share['options']) or 'no decisions yet'}"
            )
            waiting = sum(option["waiting"] for option in share["options"])
            lines.append(f"Waiting to seal: {waiting}")
        lift = results["lift"]
        if lift and lift["value"] is not None:
            lines.append(
                f"Lift over an even split: {lift['value']:+.1%}"
                + (" (early)" if lift["early"] else "")
            )
        else:
            lines.append("Lift: not yet")
        health = results["health"]
        lines.append(
            f"Health, last hour: {health['decision_errors']} decision errors, "
            f"{health['outcomes']['learned']} outcomes learned, "
            f"{health['outcomes']['late']} late"
        )
        return _result("\n".join(lines), ResultsView(**results))

    async def loop_preview(
        loop: LoopRef,
        unit: Annotated[
            str,
            Field(
                min_length=1,
                description="Who or what the request is for, as the app sends it to select.",
            ),
        ],
        properties: Annotated[
            Optional[dict[str, Any]],
            Field(
                description='What the app knows about the request, e.g. {"device": "mobile"}.'
            ),
        ] = None,
    ) -> Annotated[CallToolResult, PreviewView]:
        """What select would return for a request, recording no decision: the reason, and the option it gets, or while the engine decides, the loop's share over the last day. Outside delivery it names the part that left the request out: the schedule, an audience condition, or the rollout. Use it to check an edit took effect, or to see what a page shows someone."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read loops")
            try:
                with refusals():
                    preview = await service().preview_loop(
                        principal.tenant_id, loop, unit, properties
                    )
            except LoopNotFoundError:
                raise await refused_loop(principal, loop)
        except Refusal as refusal:
            return _refused(refusal)
        return _result(_preview_text(preview), PreviewView(**preview))

    async def metrics_list() -> Annotated[CallToolResult, MetricList]:
        """List the workspace's metrics: what each stands for, its type and window, the loops that use it, and how its outcomes arrive: outcomes a minute now, the time by which half arrive after their decision, and the share that arrive late."""
        principal = current_principal()
        try:
            _require(principal, "metric:read", "read metrics")
        except Refusal as refusal:
            return _refused(refusal)
        metrics = await service().metrics_with_health(principal.tenant_id)
        lines = [
            f"{metric['name']} · {metric['type']} · window {window_label(metric['window_seconds'])}"
            f" · {metric['semantic']}"
            + (
                f" · used by {', '.join(loop['key'] for loop in metric['loops'])}"
                if metric["loops"]
                else ""
            )
            + f" · {_arrival(metric['health'])}"
            for metric in metrics
        ] or ["No metrics yet. Create one with metric_create."]
        return _result("\n".join(lines), MetricList(metrics=metrics))

    async def engines_list() -> Annotated[CallToolResult, EngineList]:
        """List the engines a cycle can run: what each suits, what it learns from, what it needs, and its versions. Choose one with loop_create, brief_update on a draft, or cycle_start."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read engines")
        except Refusal as refusal:
            return _refused(refusal)
        engines = engine_catalog()
        lines = [
            f"{engine['name']}{' (the default)' if engine['default'] else ''}"
            f" · {engine['title']} {engine['latest']}"
            f" · {engine['suits']} · learns from {engine['learns_from']}"
            f" · needs {engine['needs']}"
            for engine in engines
        ]
        lines.append(
            f"Name one as {ACCEPTED_FORMS}: a name or a major follows its minors "
            f"as qbrix is upgraded, keeping what the loop learned; a minor stays "
            f"exactly there."
        )
        return _result(
            "\n".join(lines), EngineList(engines=engines, forms=ACCEPTED_FORMS)
        )

    async def changes_list(
        who: Annotated[
            Optional[list[Literal["member", "connection", "qbrix"]]],
            Field(
                description="Only changes by people in the console (member), "
                "through a connected client (connection), or by qbrix."
            ),
        ] = None,
        kind: Annotated[
            Optional[list[str]],
            Field(description="Only these kinds of change, such as loop.rename."),
        ] = None,
        loop: Annotated[
            Optional[str],
            Field(description="Only changes to this loop: its key or its id."),
        ] = None,
        metric: Annotated[
            Optional[str],
            Field(description="Only changes to this metric: its name or its id."),
        ] = None,
        undoable: Annotated[
            Optional[bool],
            Field(description="true for changes that can still be undone."),
        ] = None,
        fold: Annotated[
            bool,
            Field(
                description="Bursts of the same change by the same actor come back "
                "as one entry with a count; false returns each change."
            ),
        ] = True,
        cursor: Annotated[
            Optional[str],
            Field(description="next_cursor from the previous page."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
    ) -> Annotated[CallToolResult, ChangePage]:
        """List every change in the workspace, newest first: who made it and through which client, what it touched, each changed field before and after, why, and whether it can be undone. Changes waiting for approval and declined changes are included, with who answered, where and why."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read changes")
            try:
                with refusals():
                    page = await service().list_workspace_changes(
                        principal.tenant_id,
                        who=who or (),
                        kinds=kind or (),
                        loop=loop,
                        metric=metric,
                        undoable=undoable,
                        statuses=STATUSES,
                        fold=fold,
                        cursor=cursor,
                        limit=limit,
                    )
            except LoopNotFoundError as e:
                raise await refused_loop(principal, loop) from e
            except MetricNotFoundError as e:
                raise await refused_metric(principal, metric) from e
        except Refusal as refusal:
            return _refused(refusal)
        lines = [_change_line(entry) for entry in page["changes"]] or [
            "No changes match."
        ]
        if page["next_cursor"]:
            lines.append(f"More changes: call again with cursor {page['next_cursor']}.")
        return _result("\n".join(lines), ChangePage(**page))

    async def change_get(
        change: Annotated[str, Field(description="The change's id.")],
    ) -> Annotated[CallToolResult, ChangeView]:
        """Read one change by its id: who made it and through which client, what it touched, each changed field before and after, why, whether it can be undone, and its status: applied, undone, waiting for approval, or declined, with who answered, where and why. Check a waiting change here."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read changes")
            entry = await service().get_change_entry(principal.tenant_id, change)
            if entry is None:
                raise error.unknown_change(change)
        except Refusal as refusal:
            return _refused(refusal)
        url = changes_url(settings.console_origin, entry["id"])
        return _result(
            f"{_change_line(entry)}\nIn the console: {url}",
            ChangeView(**entry, url=url),
        )

    async def loop_history(
        loop: LoopRef,
        show: Annotated[
            HistoryShow,
            Field(
                description="all: changes, notes, and pull requests and commits "
                "that mention the loop. changes: changes only. notes: notes "
                "only. github: pull requests and commits only."
            ),
        ] = "all",
        cursor: Annotated[
            Optional[str],
            Field(description="next_cursor from the previous page."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
    ) -> Annotated[CallToolResult, HistoryPage]:
        """Read a loop's history, newest first: every change and note, who made it and through which client, each changed field before and after, why, a note's text, and whether it can be undone; and the pull requests and commits that mention the loop, with their state, author and link. Declined changes are included with the reason they were declined: read them before proposing a change again."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read loops")
            with refusals():
                page = await service().loop_history(
                    principal.tenant_id,
                    loop,
                    show=show,
                    statuses=STATUSES,
                    cursor=cursor,
                    limit=limit,
                )
            if page is None:
                raise await refused_loop(principal, loop)
        except Refusal as refusal:
            return _refused(refusal)
        url = history_url(settings.console_origin, page["loop"])
        lines = [_history_line(entry) for entry in page["entries"]] or [
            "Nothing in this loop's history matches."
        ]
        if page["next_cursor"]:
            lines.append(f"More history: call again with cursor {page['next_cursor']}.")
        lines.append(f"In the console: {url}")
        return _result("\n".join(lines), HistoryPage(**page, url=url))

    async def milestones_list(
        loop: Annotated[
            Optional[str],
            Field(description="Only milestones of this loop: its key or its id."),
        ] = None,
        metric: Annotated[
            Optional[str],
            Field(
                description="Only milestones of loops using this metric: its name or id."
            ),
        ] = None,
        kind: Annotated[
            Optional[list[str]],
            Field(
                description="Only these kinds: loop.first_call, loop.first_seal, "
                "loop.leader_changed."
            ),
        ] = None,
        since: Annotated[
            Optional[datetime],
            Field(description="Only milestones at or after this time."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
    ) -> Annotated[CallToolResult, MilestoneList]:
        """List what the workspace's loops reached, newest first: a draft's first call, a cycle's first window sealing, and a new option taking the lead. Leading means the largest share of decisions over the last 24 hours, held for an hour; it says how traffic is shared, not which option is better."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read milestones")
            try:
                with refusals():
                    found = await service().list_milestones(
                        principal.tenant_id,
                        loop=loop,
                        metric=metric,
                        kinds=kind or (),
                        since=since,
                        limit=limit,
                    )
            except LoopNotFoundError as e:
                raise await refused_loop(principal, loop) from e
            except MetricNotFoundError as e:
                raise await refused_metric(principal, metric) from e
        except Refusal as refusal:
            return _refused(refusal)
        lines = [_milestone_line(m) for m in found["milestones"]] or [
            "No milestones match."
        ]
        return _result("\n".join(lines), MilestoneList(**found))

    async def workspace_summary(
        since: Annotated[
            Optional[datetime],
            Field(
                description="Where the range starts, at most 30 days back; "
                "7 days ago when left out."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, WeekSummary]:
        """Read the workspace since a date, 7 days by default, in one call: for each live, paused and committed loop, each option's share of decisions then and now, lift over an even split, its alerts open at any time since then (safety pauses and warnings) and how each ended, milestones, and its changes grouped by who made them and through which client; the drafts; and the workspace's change counts. Facts only: it ranks nothing and calls no option better."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read loops")
            with refusals():
                week = await service().workspace_summary(principal.tenant_id, since)
        except Refusal as refusal:
            return _refused(refusal)
        return _result("\n".join(_week_lines(week)), WeekSummary(**week))

    async def docs_search(
        query: Annotated[
            Optional[str],
            Field(
                description="What you want to know, in words, such as 'report an outcome from the browser'."
            ),
        ] = None,
        page: Annotated[
            Optional[str],
            Field(
                description="A page to read whole, by its slug from a link, such as 'metrics-and-outcomes'."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, DocsAnswer]:
        """Search this qbrix install's own docs, so the code you write matches the API it runs: give a query for the best sections in full, or a page to read one whole with its outline. Use it before writing select, outcome or track calls. The text is this install's version; each link opens the website's, which may be newer."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read the docs")
            if (query is None) == (page is None):
                raise error.docs_ask()
            if page is not None:
                answer = docs.page(page)
                if answer is None:
                    raise error.unknown_docs_page(
                        page, [known.slug for known in docs.pages]
                    )
            else:
                answer = docs.search(query)
        except Refusal as refusal:
            return _refused(refusal)
        if not answer.sections:
            logger.info("docs search found nothing: %r", query)
            titles = [f"{known.title} ({known.slug})" for known in docs.pages]
            return _result(
                f"Nothing in the docs matches {query!r}. Try other words, or read "
                f"a page with page=: {', '.join(titles)}.",
                DocsAnswer(
                    sections=[],
                    truncated=False,
                    pages=[known.slug for known in docs.pages],
                ),
            )
        return _result("\n".join(_docs_lines(answer)), _docs_answer(answer))

    async def loop_create(
        ctx: Context,
        name: Annotated[str, Field(description="What people call the loop.")],
        metric: Annotated[
            str, Field(description="The metric it improves: its name or id.")
        ],
        options: Annotated[
            list[OptionInput],
            Field(min_length=2, description="The options qbrix chooses between."),
        ],
        reason: Reason,
        purpose: Annotated[
            str, Field(description="The product choice it decides, in a sentence.")
        ] = "",
        key: Annotated[
            Optional[str],
            Field(
                description="What code calls it; generated from the name when left out."
            ),
        ] = None,
        fallback: Annotated[
            Optional[str],
            Field(
                description="The option's key served when qbrix can't decide; the first option when left out."
            ),
        ] = None,
        engine: Annotated[
            str,
            Field(
                description="The engine that decides, from engines_list: spinoza (the default), leibniz or buridan. spinoza:1 follows its minors as qbrix is upgraded; spinoza:1.0 stays exactly on that version."
            ),
        ] = ENGINES.DEFAULT,
        context: Annotated[
            Optional[list[ContextPropertyInput]],
            Field(
                description="The properties its engine learns from, as for context_update; leibniz needs one."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Create a draft loop with its options, metric and engine. A draft serves its fallback until it is launched with loop_launch."""
        arguments = {
            "name": name,
            "metric": metric,
            "options": [option.model_dump() for option in options],
            "reason": reason,
            "purpose": purpose,
            "key": key,
            "fallback": fallback,
            "engine": engine,
            "context": (
                [prop.model_dump(exclude_none=True) for prop in context]
                if context is not None
                else None
            ),
        }

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "create loops")
            if await service().get_metric(principal.tenant_id, metric) is None:
                raise await refused_metric(principal, metric)
            with refusals():
                created = await make(
                    principal,
                    "loop.create",
                    None,
                    {
                        "name": name,
                        "key": key,
                        "purpose": purpose,
                        "metric": metric,
                        "options": arguments["options"],
                        "fallback": fallback,
                        "engine": engine,
                        "context": arguments["context"],
                    },
                    reason=reason,
                )
            if isinstance(created, Waiting):
                return await asked(
                    principal,
                    created.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=created.value
                    ),
                )
            loop = created.value
            change = changed(created, "loop", loop["key"])
            return _result(
                f"Created the draft loop {loop['key']} ({loop['name']}) "
                f"on {loop['engine']}. "
                f"Launch it with loop_launch once its select call is in the code. "
                f"Change {change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=loop),
            )

        return await once("loop_create", arguments, call, ctx, loop_answered)

    async def loop_rename(
        ctx: Context,
        loop: LoopRef,
        name: Annotated[
            str, Field(description="What people call the loop from now on.")
        ],
        reason: Reason,
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Rename a loop, in any state. Its key stays, so the code that calls it keeps working."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "rename loops")
            with refusals():
                renamed = await make(
                    principal, "loop.rename", loop, {"name": name}, reason=reason
                )
            if renamed is None:
                raise await refused_loop(principal, loop)
            if isinstance(renamed, Waiting):
                return await asked(
                    principal,
                    renamed.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=renamed.value
                    ),
                )
            value = renamed.value
            change = changed(renamed, "loop", value["key"])
            return _result(
                f"Renamed {value['key']} to {value['name']}; its key stays, so the "
                f"code that calls it keeps working. Change {change['id']}, can be "
                f"undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "loop_rename",
            {"loop": loop, "name": name, "reason": reason},
            call,
            ctx,
            loop_answered,
        )

    async def loop_launch(
        ctx: Context, loop: LoopRef, reason: Reason
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Take a draft loop live: its first cycle starts and qbrix begins choosing between its options. This puts its options in front of users."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "launch loops")
            try:
                with refusals():
                    launched = await make(
                        principal, "loop.launch", loop, {}, reason=reason
                    )
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_draft(found["key"], found["state"]) from e
            if launched is None:
                raise await refused_loop(principal, loop)
            if isinstance(launched, Waiting):
                return await asked(
                    principal,
                    launched.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=launched.value
                    ),
                )
            value = launched.value
            change = changed(launched, "loop", value["key"])
            return _result(
                f"Launched {value['key']}: cycle {value['cycle']['number']} is live. "
                f"Change {change['id']}, can't be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "loop_launch", {"loop": loop, "reason": reason}, call, ctx, loop_answered
        )

    async def loop_commit(
        ctx: Context,
        loop: LoopRef,
        option: Annotated[
            str, Field(description="The key of the option everyone gets from now on.")
        ],
        reason: Reason,
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Commit a live loop to one option: everyone gets it and exploration stops. It still decides, so that option's outcomes keep teaching it, and the others keep what they learned. Reopen with loop_reopen to learn again."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "commit loops")
            try:
                committed = await make(
                    principal, "loop.commit", loop, {"option": option}, reason=reason
                )
            except LoopInvalidError as e:
                raise error.unknown_option(str(e)) from e
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_live(
                    found["key"], found["state"], found["committed"]
                ) from e
            if committed is None:
                raise await refused_loop(principal, loop)
            if isinstance(committed, Waiting):
                return await asked(
                    principal,
                    committed.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=committed.value
                    ),
                )
            value = committed.value
            change = changed(committed, "loop", value["key"])
            return _result(
                f"Committed {value['key']} to {option}: everyone gets it, and its "
                f"outcomes keep teaching it. Reopen with loop_reopen to learn again. "
                f"Change {change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "loop_commit",
            {"loop": loop, "option": option, "reason": reason},
            call,
            ctx,
            loop_answered,
        )

    async def loop_reopen(
        ctx: Context, loop: LoopRef, reason: Reason
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Reopen a committed loop: it is live again in the same cycle, with everything it learned, and qbrix chooses between its options again."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "reopen loops")
            try:
                reopened = await make(principal, "loop.reopen", loop, {}, reason=reason)
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_committed(found["key"], found["state"]) from e
            if reopened is None:
                raise await refused_loop(principal, loop)
            if isinstance(reopened, Waiting):
                return await asked(
                    principal,
                    reopened.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=reopened.value
                    ),
                )
            value = reopened.value
            change = changed(reopened, "loop", value["key"])
            return _result(
                f"Reopened {value['key']}: cycle {value['cycle']['number']} is live "
                f"again and qbrix chooses between its options. "
                f"Change {change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "loop_reopen", {"loop": loop, "reason": reason}, call, ctx, loop_answered
        )

    async def loop_retire(
        ctx: Context, loop: LoopRef, reason: Reason
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Retire a live or committed loop once its choice has left the product: the chosen option is built in and the select call is going away. Apps that still call it get its fallback, its open decisions keep teaching until their windows close, and its history stays readable. This can't be undone; serving the choice again takes a new loop."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "retire loops")
            try:
                retired = await make(principal, "loop.retire", loop, {}, reason=reason)
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_retirable(found["key"], found["state"]) from e
            if retired is None:
                raise await refused_loop(principal, loop)
            if isinstance(retired, Waiting):
                return await asked(
                    principal,
                    retired.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=retired.value
                    ),
                )
            value = retired.value
            change = changed(retired, "loop", value["key"])
            return _result(
                f"Retired {value['key']}: apps that still call it get its fallback, "
                f"and its open decisions keep teaching until their windows close. "
                f"Change {change['id']}, can't be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "loop_retire", {"loop": loop, "reason": reason}, call, ctx, loop_answered
        )

    async def loop_pause(
        ctx: Context, loop: LoopRef, reason: Reason
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Pause a live or committed loop: everyone gets its fallback until it is resumed with loop_resume, which returns it to the state it was paused from. Decisions already made still seal and teach."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "pause loops")
            try:
                paused = await make(principal, "loop.pause", loop, {}, reason=reason)
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_pausable(found["key"], found["state"]) from e
            if paused is None:
                raise await refused_loop(principal, loop)
            if isinstance(paused, Waiting):
                return await asked(
                    principal,
                    paused.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=paused.value
                    ),
                )
            value = paused.value
            change = changed(paused, "loop", value["key"])
            return _result(
                f"Paused {value['key']}: everyone gets its fallback from now on, "
                f"and decisions already made still seal and teach. Resume it "
                f"with loop_resume. Change {change['id']}, can be undone: "
                f"{change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "loop_pause", {"loop": loop, "reason": reason}, call, ctx, loop_answered
        )

    async def cycle_start(
        ctx: Context,
        loop: LoopRef,
        reason: Reason,
        options: Annotated[
            Optional[list[OptionInput]],
            Field(
                min_length=2,
                description="The new cycle's options, all of them; the current ones when left out.",
            ),
        ] = None,
        engine: Annotated[
            Optional[str],
            Field(
                description="The new cycle's engine, such as spinoza or leibniz:1; the current one when left out."
            ),
        ] = None,
        metric: Annotated[
            Optional[str],
            Field(
                description="The metric the loop improves from this cycle on, by name or id, of any type; the current one when left out. The cycle pins its newest version."
            ),
        ] = None,
        context: Annotated[
            Optional[list[ContextPropertyInput]],
            Field(
                description="The properties the new cycle's engine learns from, replacing the whole context; the current one when left out."
            ),
        ] = None,
        fallback: Annotated[
            Optional[str],
            Field(
                description="The option's key everyone the loop isn't deciding for gets; kept when left out, and needed if its option is gone."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Start a new cycle of a live or paused loop with new options, a new engine, a new metric or a new context, all together in one call: one cycle carries every change that needs one. The new cycle learns afresh; the current one ends and its results stay readable, and its open decisions keep teaching it. A paused loop stays paused. This can't be undone."""
        arguments = {
            "loop": loop,
            "reason": reason,
            "options": (
                [option.model_dump() for option in options]
                if options is not None
                else None
            ),
            "engine": engine,
            "metric": metric,
            "context": (
                [prop.model_dump(exclude_none=True) for prop in context]
                if context is not None
                else None
            ),
            "fallback": fallback,
        }

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "start cycles")
            try:
                with refusals():
                    started = await make(
                        principal,
                        "cycle.start",
                        loop,
                        {
                            "options": arguments["options"],
                            "engine": engine,
                            "metric": metric,
                            "fallback": fallback,
                            **(
                                {"context": arguments["context"]}
                                if context is not None
                                else {}
                            ),
                        },
                        reason=reason,
                        also=("context.update",) if context is not None else (),
                    )
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_cyclable(
                    found["key"], found["state"], found["paused_from"]
                ) from e
            if started is None:
                raise await refused_loop(principal, loop)
            if isinstance(started, Waiting):
                return await asked(
                    principal,
                    started.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=started.value
                    ),
                )
            value = started.value
            change = changed(started, "loop", value["key"])
            return _result(
                f"Started cycle {value['cycle']['number']} of {value['key']}: it "
                f"learns afresh, and the earlier cycle stays readable. "
                f"Change {change['id']}, can't be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once("cycle_start", arguments, call, ctx, loop_answered)

    async def cycle_reset(
        ctx: Context, loop: LoopRef, reason: Reason
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Reset the cycle of a live or paused loop: a new cycle with the same options, engine and fallback, learning afresh. The current one ends and its results stay readable, and its open decisions keep teaching it. A paused loop stays paused. This can't be undone."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "reset cycles")
            try:
                with refusals():
                    reset = await make(
                        principal, "cycle.reset", loop, {}, reason=reason
                    )
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_cyclable(
                    found["key"], found["state"], found["paused_from"]
                ) from e
            if reset is None:
                raise await refused_loop(principal, loop)
            if isinstance(reset, Waiting):
                return await asked(
                    principal,
                    reset.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=reset.value
                    ),
                )
            value = reset.value
            change = changed(reset, "loop", value["key"])
            return _result(
                f"Reset {value['key']}: cycle {value['cycle']['number']} learns "
                f"afresh with the same options and engine, and the earlier cycle "
                f"stays readable. Change {change['id']}, can't be undone: "
                f"{change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "cycle_reset", {"loop": loop, "reason": reason}, call, ctx, loop_answered
        )

    async def delivery_update(
        ctx: Context,
        loop: LoopRef,
        reason: Reason,
        audience: Annotated[
            Optional[list[ConditionInput]],
            Field(
                description="Conditions on context properties, all of which must hold, such as device is mobile. A request without the property never holds its condition. An empty list means everyone. Replaces the whole audience; kept when left out."
            ),
        ] = None,
        rollout: Annotated[
            Optional[int],
            Field(
                ge=0,
                le=100,
                description="The share of the audience the loop decides for, 0 to 100. A unit keeps its place, so raising it only adds units. Kept when left out.",
            ),
        ] = None,
        schedule: Annotated[
            Optional[ScheduleInput],
            Field(
                description="When the loop decides: daily hours and a start date, in a timezone. There is no end date: pause or retire the loop instead. Replaces the whole schedule; kept when left out."
            ),
        ] = None,
        fallback: Annotated[
            Optional[str],
            Field(
                description="The option's key everyone the loop isn't deciding for gets. Kept when left out."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Change who a loop decides for: its audience, rollout and schedule, and the fallback everyone else gets. Delivery never picks an option: inside it a live loop's engine chooses and a committed loop serves its committed option; outside it, the fallback, with reason outside_delivery. Any state but retired. This can be undone."""
        arguments = {
            "loop": loop,
            "reason": reason,
            "audience": (
                [condition.model_dump() for condition in audience]
                if audience is not None
                else None
            ),
            "rollout": rollout,
            "schedule": (
                schedule.model_dump(exclude_none=True) if schedule is not None else None
            ),
            "fallback": fallback,
        }

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "change delivery")
            try:
                with refusals():
                    updated = await make(
                        principal,
                        "delivery.update",
                        loop,
                        {
                            name: arguments[name]
                            for name in ("audience", "rollout", "schedule", "fallback")
                        },
                        reason=reason,
                    )
            except LoopStateError as e:
                raise error.retired(loop) from e
            if updated is None:
                raise await refused_loop(principal, loop)
            if isinstance(updated, Waiting):
                return await asked(
                    principal,
                    updated.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=updated.value
                    ),
                )
            value = updated.value
            change = changed(updated, "loop", value["key"])
            return _result(
                f"Changed the delivery of {value['key']}. "
                f"{_delivery_line(value, datetime.now(timezone.utc))} "
                f"Serving moves within {math.ceil(settings.experiment_cache_ttl)} "
                f"seconds. Change {change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once("delivery_update", arguments, call, ctx, loop_answered)

    async def context_update(
        ctx: Context,
        loop: LoopRef,
        reason: Reason,
        context: Annotated[
            Optional[list[ContextPropertyInput]],
            Field(
                description="The properties the engine learns from; replaces the whole context. null clears it, which an engine that learns from context refuses."
            ),
        ],
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Declare which context properties a loop's engine learns from. Wire the app to send them with select first, then declare them: properties not declared are still recorded and usable in the audience, and a value of the wrong type is learned as the property's default, so select never fails over the context. The answer says which declared properties arrived in the last day. On Leibniz, a loop past draft starts a new cycle, which asks first like cycle_start and can't be undone; otherwise this can be undone."""
        arguments = {
            "loop": loop,
            "reason": reason,
            "context": (
                [prop.model_dump(exclude_none=True) for prop in context]
                if context is not None
                else None
            ),
        }

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "change a loop's context")
            found = await service().get_loop(principal.tenant_id, loop)
            if found is None:
                raise await refused_loop(principal, loop)
            cycles = starts_cycle(found["state"], found["engine"])
            try:
                with refusals():
                    updated = await make(
                        principal,
                        "context.update",
                        loop,
                        {"context": arguments["context"]},
                        reason=reason,
                        also=("cycle.start",) if cycles else (),
                    )
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                if found["state"] == "retired":
                    raise error.retired(loop) from e
                raise error.not_cyclable(
                    found["key"], found["state"], found["paused_from"]
                ) from e
            if updated is None:
                raise await refused_loop(principal, loop)
            if isinstance(updated, Waiting):
                return await asked(
                    principal,
                    updated.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=updated.value
                    ),
                )
            value = updated.value
            change = changed(updated, "loop", value["key"])
            read = await service().loop_context(principal.tenant_id, value["id"])
            cycled = not change["undoable"]
            started = (
                f" Started cycle {value['cycle']['number']}, which learns afresh."
                if cycled
                else ""
            )
            undo = "can't be undone" if cycled else "can be undone"
            return _result(
                f"Changed the context of {value['key']}. {_context_line(value)}"
                f"{started} {_arrival_line(read)} "
                f"Serving moves within {math.ceil(settings.experiment_cache_ttl)} "
                f"seconds. Change {change['id']}, {undo}: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once("context_update", arguments, call, ctx, loop_answered)

    async def engine_version(
        ctx: Context,
        loop: LoopRef,
        reason: Reason,
        engine: Annotated[
            str,
            Field(
                description="The cycle's engine with its major, such as spinoza:1 to follow its minors as qbrix is upgraded, or with the minor the cycle runs, such as spinoza:1.3, to stay on it."
            ),
        ],
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Switch a launched loop's cycle between following its engine's major and staying on the minor it runs. The cycle and what it learned stay, and this can be undone. Following again moves the cycle to the newest minor qbrix ships. Another engine, major or minor is a new cycle: use cycle_start."""
        arguments = {"loop": loop, "reason": reason, "engine": engine}

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "change a loop's engine version")
            try:
                with refusals():
                    updated = await make(
                        principal,
                        "engine.version",
                        loop,
                        {"engine": engine},
                        reason=reason,
                    )
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                if found["state"] == "retired":
                    raise error.retired(loop) from e
                raise Refusal(
                    f"The loop {found['key']} is a draft; its engine is part of "
                    f"its brief until it launches. Nothing was changed."
                ) from e
            if updated is None:
                raise await refused_loop(principal, loop)
            if isinstance(updated, Waiting):
                return await asked(
                    principal,
                    updated.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=updated.value
                    ),
                )
            value = updated.value
            change = changed(updated, "loop", value["key"])
            cycle = value["cycle"]
            return _result(
                f"Kept cycle {cycle['number']} of {value['key']} and what it "
                f"learned; {_engine_hold_line(cycle)}. Serving moves within "
                f"{math.ceil(settings.experiment_cache_ttl)} seconds. Change "
                f"{change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once("engine_version", arguments, call, ctx, loop_answered)

    async def brief_update(
        ctx: Context,
        loop: LoopRef,
        reason: Reason,
        purpose: Annotated[
            Optional[str],
            Field(description="What the loop is for; kept when left out."),
        ] = None,
        owner: Annotated[
            Optional[str],
            Field(
                description="The email or id of the workspace member who owns the loop from now on; kept when left out."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Change a loop's brief: what it is for and who owns it, in any state. To change its options, engine or metric, start a new cycle with cycle_start. This can be undone."""
        arguments = {"loop": loop, "reason": reason, "purpose": purpose, "owner": owner}

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "change a loop's brief")
            with refusals():
                updated = await make(
                    principal,
                    "brief.update",
                    loop,
                    {"purpose": purpose, "owner": owner},
                    reason=reason,
                )
            if updated is None:
                raise await refused_loop(principal, loop)
            if isinstance(updated, Waiting):
                return await asked(
                    principal,
                    updated.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=updated.value
                    ),
                )
            value = updated.value
            change = changed(updated, "loop", value["key"])
            return _result(
                f"Changed the brief of {value['key']}. Purpose: "
                f"{value['purpose'] or 'none given'}. Owner: {value['owner']['name']}. "
                f"Change {change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once("brief_update", arguments, call, ctx, loop_answered)

    async def loop_resume(
        ctx: Context, loop: LoopRef, reason: Reason
    ) -> Annotated[CallToolResult, LoopChanged] | InputRequiredResult:
        """Resume a paused loop: it returns to the state it was paused from, live or committed, and decides again from now."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "resume loops")
            try:
                resumed = await make(principal, "loop.resume", loop, {}, reason=reason)
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_paused(found["key"], found["state"]) from e
            if resumed is None:
                raise await refused_loop(principal, loop)
            if isinstance(resumed, Waiting):
                return await asked(
                    principal,
                    resumed.change,
                    lambda change, _: LoopChanged(
                        status="waiting", change=change, loop=resumed.value
                    ),
                )
            value = resumed.value
            change = changed(resumed, "loop", value["key"])
            serving = (
                f"committed to {value['committed']}"
                if value["state"] == "committed"
                else "live"
            )
            return _result(
                f"Resumed {value['key']}: it is {serving} again. "
                f"Change {change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once(
            "loop_resume", {"loop": loop, "reason": reason}, call, ctx, loop_answered
        )

    async def metric_create(
        ctx: Context,
        name: Annotated[
            str,
            Field(
                description="What code sends: lowercase letters, digits, '_', '-' and '.'."
            ),
        ],
        semantic: Annotated[
            str, Field(description="What the metric stands for, in a sentence.")
        ],
        type: Annotated[
            Literal["conversion", "count", "value", "score"],
            Field(
                description="conversion: did it happen (1 or 0). count: how many times. "
                "value: an amount, such as revenue. score: a number within range."
            ),
        ],
        reason: Reason,
        range: Annotated[
            Optional[ScoreRange],
            Field(description="A score's lowest and highest value; only for score."),
        ] = None,
        window_seconds: Annotated[
            int,
            Field(ge=1, description="How long after a decision its outcome counts."),
        ] = 86400,
    ) -> Annotated[CallToolResult, MetricChanged] | InputRequiredResult:
        """Create a metric loops can improve: what it stands for, its type and the window in which an outcome counts."""
        arguments = {
            "name": name,
            "semantic": semantic,
            "type": type,
            "reason": reason,
            "range": range.model_dump() if range else None,
            "window_seconds": window_seconds,
        }

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "metric:write", "create metrics")
            with refusals():
                created = await make(
                    principal,
                    "metric.create",
                    None,
                    {
                        "name": name,
                        "semantic": semantic,
                        "metric_type": type,
                        "score_range": [range.lo, range.hi] if range else None,
                        "window_seconds": window_seconds,
                    },
                    reason=reason,
                )
            if isinstance(created, Waiting):
                return await asked(
                    principal,
                    created.change,
                    lambda change, _: MetricChanged(status="waiting", change=change),
                )
            metric = created.value
            change = changed(created, "metric", metric["name"])
            return _result(
                f"Created the metric {metric['name']} ({metric['type']}, window "
                f"{window_label(metric['window_seconds'])}). "
                f"Change {change['id']}, can be undone: {change['url']}",
                MetricChanged(status="applied", change=change, metric=metric),
            )

        return await once("metric_create", arguments, call, ctx, metric_answered)

    async def metric_update(
        ctx: Context,
        metric: Annotated[str, Field(description="The metric's name or id.")],
        reason: Reason,
        name: Annotated[
            Optional[str],
            Field(
                description="A new name; only while no decision has used the metric, since code sends it."
            ),
        ] = None,
        window_seconds: Annotated[
            Optional[int],
            Field(
                ge=1,
                description="A new window, for decisions made from now on: a minor version.",
            ),
        ] = None,
        semantic: Annotated[
            Optional[str],
            Field(
                description="What the metric stands for now, in a sentence. It may link the pull request that changed what code sends."
            ),
        ] = None,
        semantic_change: Annotated[
            Optional[Literal["reword", "same", "new"]],
            Field(
                description="With semantic. reword: the same meaning in other words, no new version. same: the same meaning, a minor version. new: a new meaning, a major version that starts a new cycle on every loop still deciding, which asks first like cycle_start."
            ),
        ] = None,
    ) -> Annotated[CallToolResult, MetricChanged] | InputRequiredResult:
        """Change a metric's window, semantic or name. Record a change to what code sends for a metric here, with the pull request as the reason. Loops using it follow at once and the change is in each one's history; a new semantic starts a new cycle on each loop still deciding and can't be undone, the rest can."""
        arguments = {
            "metric": metric,
            "reason": reason,
            "name": name,
            "window_seconds": window_seconds,
            "semantic": semantic,
            "semantic_change": semantic_change,
        }

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "metric:write", "change metrics")
            cycles = False
            if semantic_change == "new":
                in_use = await service().metrics_in_use(principal.tenant_id)
                found = next(
                    (m for m in in_use if metric in (m["id"], m["name"])), None
                )
                if found is None:
                    raise await refused_metric(principal, metric)
                cycles = any(loop["state"] in DECIDING for loop in found["loops"])
            with refusals():
                updated = await make(
                    principal,
                    "metric.update",
                    metric,
                    {
                        "name": name,
                        "window_seconds": window_seconds,
                        "semantic": semantic,
                        "semantic_change": semantic_change,
                    },
                    reason=reason,
                    also=("cycle.start",) if cycles else (),
                )
            if updated is None:
                raise await refused_metric(principal, metric)
            if isinstance(updated, Waiting):
                return await asked(
                    principal,
                    updated.change,
                    lambda change, _: MetricChanged(status="waiting", change=change),
                )
            value = updated.value["metric"]
            started = updated.value["cycles"]
            change = changed(updated, "metric", value["name"])
            cycled = (
                " Started "
                + ", ".join(f"cycle {c['cycle']} of {c['loop']}" for c in started)
                + ", which learn afresh."
                if started
                else ""
            )
            undo = "can be undone" if change["undoable"] else "can't be undone"
            return _result(
                f"Changed the metric {value['name']}: version {value['version']}, "
                f"window {window_label(value['window_seconds'])}.{cycled} Serving "
                f"moves within {math.ceil(settings.experiment_cache_ttl)} seconds. "
                f"Change {change['id']}, {undo}: {change['url']}",
                MetricChanged(
                    status="applied", change=change, metric=value, cycles=started
                ),
            )

        return await once("metric_update", arguments, call, ctx, metric_answered)

    async def metric_delete(
        ctx: Context,
        metric: Annotated[str, Field(description="The metric's name or id.")],
        reason: Reason,
    ) -> Annotated[CallToolResult, MetricChanged] | InputRequiredResult:
        """Delete a metric no loop has used. Once a loop has used it, it stays. This can't be undone."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "metric:write", "delete metrics")
            with refusals():
                deleted = await make(
                    principal, "metric.delete", metric, {}, reason=reason
                )
            if deleted is None:
                raise await refused_metric(principal, metric)
            if isinstance(deleted, Waiting):
                return await asked(
                    principal,
                    deleted.change,
                    lambda change, _: MetricChanged(status="waiting", change=change),
                )
            value = deleted.value
            change = changed(deleted, "metric", value["name"])
            return _result(
                f"Deleted the metric {value['name']}. Change {change['id']}, "
                f"can't be undone: {change['url']}",
                MetricChanged(status="applied", change=change),
            )

        return await once(
            "metric_delete",
            {"metric": metric, "reason": reason},
            call,
            ctx,
            metric_answered,
        )

    async def note_add(
        ctx: Context,
        loop: LoopRef,
        text: Annotated[
            str,
            Field(
                min_length=1,
                max_length=NOTE_MAX_LENGTH,
                description="The note, in plain text: what people and agents "
                "reading this loop's history should know.",
            ),
        ],
    ) -> Annotated[CallToolResult, NoteAdded] | InputRequiredResult:
        """Add a note to a loop's history, beside its changes. A note stays: it can't be undone or edited, so a correction is a new note."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "add notes")
            with refusals():
                added = await make(principal, "note.add", loop, {"text": text})
            if added is None:
                raise await refused_loop(principal, loop)
            if isinstance(added, Waiting):
                return await asked(
                    principal,
                    added.change,
                    lambda change, entry: NoteAdded(
                        status="waiting", change=change, note=entry
                    ),
                )
            key = added.value["key"]
            change = changed(added, "loop", key)
            entry = await service().get_change_entry(principal.tenant_id, change["id"])
            return _result(
                f"Added a note to {key}. Change {change['id']}, a note stays in "
                f"history: {change['url']}",
                NoteAdded(status="applied", change=change, note=entry),
            )

        return await once(
            "note_add", {"loop": loop, "text": text}, call, ctx, note_answered
        )

    async def change_undo(
        ctx: Context,
        change: Annotated[str, Field(description="The id of the change to undo.")],
        reason: Reason,
    ) -> Annotated[CallToolResult, ChangeUndone] | InputRequiredResult:
        """Undo an earlier change by writing its inverse as a new change. Refused when its kind can't be undone, it was already undone, or a later change moved what it would restore; the refusal says which and names that later change. It runs at your autonomy for the change it undoes, so it may wait for approval."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            found = await service().get_change(principal.tenant_id, change)
            if found is None:
                raise error.unknown_change(change)
            scope = undo_scope(found["target_type"])
            if scope is not None:
                _require(principal, scope, "undo this change")
            kind = found["kind"]
            with error.undo_refusals():
                undo = await service().undo_change(
                    principal.tenant_id,
                    change,
                    actor=(
                        principal.acting(kind)
                        if kind in autonomy.DEFAULTS
                        else principal.actor
                    ),
                    reason=reason,
                )
            entry = await service().get_change_entry(principal.tenant_id, undo["id"])
            url = changes_url(settings.console_origin, undo["id"])
            if undo["status"] == "waiting":
                return await asked(
                    principal,
                    {"id": undo["id"], "kind": undo["kind"], "undoable": False},
                    lambda ref, waiting: ChangeUndone(
                        status="waiting", change=ref, undone=waiting
                    ),
                )
            return _result(
                f"{_sentence(entry)} This undoes change {change}. "
                f"Change {undo['id']}: {url}",
                ChangeUndone(
                    status="applied",
                    change={
                        "id": undo["id"],
                        "kind": undo["kind"],
                        "undoable": entry["undoable"],
                        "url": url,
                    },
                    undone=entry,
                ),
            )

        return await once(
            "change_undo",
            {"change": change, "reason": reason},
            call,
            ctx,
            undo_answered,
        )

    for fn, hints in (
        (loops_list, _READ),
        (loop_get, _READ),
        (loop_results, _READ),
        (loop_preview, _READ),
        (metrics_list, _READ),
        (engines_list, _READ),
        (changes_list, _READ),
        (change_get, _READ),
        (loop_history, _READ),
        (milestones_list, _READ),
        (workspace_summary, _READ),
        (docs_search, _READ),
        (loop_create, _CREATE),
        (loop_rename, _DESTRUCTIVE),
        (loop_launch, _DESTRUCTIVE),
        (loop_commit, _DESTRUCTIVE),
        (loop_reopen, _DESTRUCTIVE),
        (loop_retire, _DESTRUCTIVE),
        (loop_pause, _DESTRUCTIVE),
        (loop_resume, _DESTRUCTIVE),
        (cycle_start, _DESTRUCTIVE),
        (cycle_reset, _DESTRUCTIVE),
        (delivery_update, _DESTRUCTIVE),
        (context_update, _DESTRUCTIVE),
        (engine_version, _DESTRUCTIVE),
        (brief_update, _DESTRUCTIVE),
        (metric_create, _CREATE),
        (metric_update, _DESTRUCTIVE),
        (metric_delete, _DESTRUCTIVE),
        (note_add, _CREATE),
        (change_undo, _DESTRUCTIVE),
    ):
        server.add_tool(fn, annotations=hints)
