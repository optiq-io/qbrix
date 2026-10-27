from __future__ import annotations

import json
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Annotated
from typing import Any
from typing import Literal
from typing import Optional

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from mcp_types import TextContent
from mcp_types import ToolAnnotations
from pydantic import BaseModel
from pydantic import Field

from proxysvc.config import ProxySettings
from proxysvc.core.error import ConnectionRateLimitedError
from proxysvc.core.error import CycleNotFoundError
from proxysvc.core.error import LoopStateError
from proxysvc.mod.auth.scope import ROLE_SCOPES
from proxysvc.mod.change.applied import Applied
from proxysvc.mod.connection.service import ConnectionPrincipal
from proxysvc.service import ProxyService
from proxysvc.transport.mcp import error
from proxysvc.transport.mcp.error import Refusal
from proxysvc.transport.mcp.error import refusals
from proxysvc.transport.mcp.link import change_url
from proxysvc.transport.mcp.repeat import RepeatGuard
from proxysvc.transport.mcp.repeat import repeat_key
from proxysvc.transport.mcp.schema import Detail
from proxysvc.transport.mcp.schema import LoopChanged
from proxysvc.transport.mcp.schema import LoopPage
from proxysvc.transport.mcp.schema import LoopView
from proxysvc.transport.mcp.schema import MetricChanged
from proxysvc.transport.mcp.schema import MetricList
from proxysvc.transport.mcp.schema import ResultsView
from proxysvc.transport.mcp.verifier import current_principal
from proxysvc.transport.mcp.wire import wiring

LIMIT_DEFAULT = 20
LIMIT_MAX = 100

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_CREATE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
_LAUNCH = ToolAnnotations(
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


def _who(entry: dict | None) -> str:
    if entry is None:
        return ""
    who = entry["who"]
    name = "qbrix" if who["kind"] == "qbrix" else who["name"]
    via = entry.get("via")
    return f"{name} via {via['client']}" if via else name


def _window(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _concise(loop: dict, detail: Detail) -> dict:
    if detail == "full":
        return loop
    return {
        **loop,
        "options": [{**option, "config": None} for option in loop["options"]],
    }


def _loop_line(loop: dict) -> str:
    line = f"{loop['key']} · {loop['name']} · {loop['state']} · metric {loop['metric']['name']}"
    if loop.get("cycle"):
        line += f" · cycle {loop['cycle']['number']}"
    return line


def _share_line(share: list[dict]) -> str:
    return ", ".join(
        f"{item['key']} {item['share']:.0%}"
        for item in share
        if item.get("share") is not None
    )


def register(
    server: MCPServer,
    settings: ProxySettings,
    service: Callable[[], ProxyService],
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
    ) -> CallToolResult:
        """a change call, run once per connection and arguments in the window.
        a repeat counts as a change, so retrying can't get around the cap."""
        principal = current_principal()

        async def first() -> dict[str, Any]:
            result = await call(principal)
            return {"text": _text(result), "structured": result.structured_content}

        try:
            await service().connections.count_change(principal.actor.connection_id)
        except ConnectionRateLimitedError as e:
            return _refused(error.too_many_changes(e.limit, e.retry_after))
        try:
            stored = await repeats().once(
                repeat_key(principal.actor.connection_id, tool, arguments), first
            )
        except Refusal as refusal:
            return _refused(refusal)
        return CallToolResult(
            content=[TextContent(type="text", text=stored["text"])],
            structured_content=stored["structured"],
        )

    def changed(applied: Applied, target: Literal["loop", "metric"], ref: str) -> dict:
        return {
            **applied.change,
            "url": change_url(
                settings.console_origin, target, ref, applied.change["id"]
            ),
        }

    async def loops_list(
        state: Annotated[
            Optional[list[Literal["draft", "live", "paused"]]],
            Field(description="Only loops in these states; all loops when left out."),
        ] = None,
        cursor: Annotated[
            Optional[str],
            Field(description="next_cursor from the previous page."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
        detail: DetailArg = "concise",
    ) -> Annotated[CallToolResult, LoopPage]:
        """List the workspace's loops, newest first: each loop's key, name, state, metric, share of decisions now, and its latest change with who made it."""
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
            share = _share_line((loop.get("results") or {}).get("share") or [])
            if share:
                line += f" · share {share}"
            latest = loop.get("latest_change")
            if latest:
                line += f" · latest {latest['kind']} by {_who(latest)}"
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
        """Read one loop: its purpose, options, metric, owner, fallback, state and current cycle, and how to wire it: the select and outcome calls for this loop in Python and JavaScript."""
        principal = current_principal()
        try:
            _require(principal, "loop:read", "read loops")
            found = await service().get_loop(principal.tenant_id, loop)
            if found is None:
                raise await refused_loop(principal, loop)
        except Refusal as refusal:
            return _refused(refusal)
        wire = wiring(found, settings.public_origin)
        view = LoopView(**_concise(found, detail), wire=wire)
        options = "\n".join(
            f"- {option['key']}: {option['name']}"
            + (f" {json.dumps(option['config'])}" if detail == "full" else "")
            for option in found["options"]
        )
        text = (
            f"{_loop_line(found)}\n"
            f"Purpose: {found['purpose'] or '(none)'}\n"
            f"Owner: {found['owner']['name']} · fallback {found['fallback']} · "
            f"engine {found['engine']}\n"
            f"Options:\n{options}\n\n"
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
        """Read a loop's results for one cycle: each option's share of decisions, lift over an even split (marked early while its range is filling), decisions waiting to seal, calls by state, and health."""
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
        lines = []
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

    async def metrics_list() -> Annotated[CallToolResult, MetricList]:
        """List the workspace's metrics: what each stands for, its type and window, and the loops that use it."""
        principal = current_principal()
        try:
            _require(principal, "metric:read", "read metrics")
        except Refusal as refusal:
            return _refused(refusal)
        metrics = await service().metrics_in_use(principal.tenant_id)
        lines = [
            f"{metric['name']} · {metric['type']} · window {_window(metric['window_seconds'])}"
            f" · {metric['semantic']}"
            + (
                f" · used by {', '.join(loop['key'] for loop in metric['loops'])}"
                if metric["loops"]
                else ""
            )
            for metric in metrics
        ] or ["No metrics yet. Create one with metric_create."]
        return _result("\n".join(lines), MetricList(metrics=metrics))

    async def loop_create(
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
    ) -> Annotated[CallToolResult, LoopChanged]:
        """Create a draft loop with its options and metric. A draft serves its fallback until it is launched with loop_launch."""
        arguments = {
            "name": name,
            "metric": metric,
            "options": [option.model_dump() for option in options],
            "reason": reason,
            "purpose": purpose,
            "key": key,
            "fallback": fallback,
        }

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "create loops")
            if await service().get_metric(principal.tenant_id, metric) is None:
                raise await refused_metric(principal, metric)
            with refusals():
                created = await service().create_loop(
                    principal.tenant_id,
                    name=name,
                    key=key,
                    purpose=purpose,
                    metric=metric,
                    options=arguments["options"],
                    fallback=fallback,
                    actor=principal.actor,
                    reason=reason,
                )
            loop = created.value
            change = changed(created, "loop", loop["key"])
            return _result(
                f"Created the draft loop {loop['key']} ({loop['name']}). "
                f"Launch it with loop_launch once its select call is in the code. "
                f"Change {change['id']}, can be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=loop),
            )

        return await once("loop_create", arguments, call)

    async def loop_launch(
        loop: LoopRef, reason: Reason
    ) -> Annotated[CallToolResult, LoopChanged]:
        """Take a draft loop live: its first cycle starts and qbrix begins choosing between its options. This puts its options in front of users."""

        async def call(principal: ConnectionPrincipal) -> CallToolResult:
            _require(principal, "loop:write", "launch loops")
            try:
                with refusals():
                    launched = await service().launch_loop(
                        principal.tenant_id,
                        loop,
                        actor=principal.actor,
                        reason=reason,
                    )
            except LoopStateError as e:
                found = await service().get_loop(principal.tenant_id, loop)
                raise error.not_draft(found["key"], found["state"]) from e
            if launched is None:
                raise await refused_loop(principal, loop)
            value = launched.value
            change = changed(launched, "loop", value["key"])
            return _result(
                f"Launched {value['key']}: cycle {value['cycle']['number']} is live. "
                f"Change {change['id']}, can't be undone: {change['url']}",
                LoopChanged(status="applied", change=change, loop=value),
            )

        return await once("loop_launch", {"loop": loop, "reason": reason}, call)

    async def metric_create(
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
    ) -> Annotated[CallToolResult, MetricChanged]:
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
                created = await service().create_metric(
                    principal.tenant_id,
                    name=name,
                    semantic=semantic,
                    metric_type=type,
                    score_range=(range.lo, range.hi) if range else None,
                    window_seconds=window_seconds,
                    actor=principal.actor,
                    reason=reason,
                )
            metric = created.value
            change = changed(created, "metric", metric["name"])
            return _result(
                f"Created the metric {metric['name']} ({metric['type']}, window "
                f"{_window(metric['window_seconds'])}). "
                f"Change {change['id']}, can be undone: {change['url']}",
                MetricChanged(status="applied", change=change, metric=metric),
            )

        return await once("metric_create", arguments, call)

    for fn, hints in (
        (loops_list, _READ),
        (loop_get, _READ),
        (loop_results, _READ),
        (metrics_list, _READ),
        (loop_create, _CREATE),
        (loop_launch, _LAUNCH),
        (metric_create, _CREATE),
    ):
        server.add_tool(fn, annotations=hints)
