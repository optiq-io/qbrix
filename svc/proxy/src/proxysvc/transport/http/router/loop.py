from __future__ import annotations

import logging
import math
from typing import Any
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import status
from pydantic import BaseModel
from pydantic import Field

from qbrixcore.engine import ENGINES

from proxysvc.config import settings
from proxysvc.core.actor import Actor
from proxysvc.core.error import CycleNotFoundError
from proxysvc.core.error import InvalidCursorError
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopKeyTakenError
from proxysvc.core.error import LoopRetiredError
from proxysvc.core.error import LoopStateError
from proxysvc.mod.change.note import NOTE_MAX_LENGTH
from proxysvc.mod.change.note import HistoryShow
from proxysvc.mod.loop.delivery import Delivery
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_actor
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import CycleNotFoundException
from proxysvc.transport.http.exception import InvalidCursorException
from proxysvc.transport.http.exception import InvalidLoopException
from proxysvc.transport.http.exception import LoopKeyTakenException
from proxysvc.transport.http.exception import LoopNotCommittedException
from proxysvc.transport.http.exception import LoopNotCyclableException
from proxysvc.transport.http.exception import LoopNotDraftException
from proxysvc.transport.http.exception import LoopNotFoundException
from proxysvc.transport.http.exception import LoopNotLiveException
from proxysvc.transport.http.exception import LoopNotPausableException
from proxysvc.transport.http.exception import LoopNotPausedException
from proxysvc.transport.http.exception import LoopNotRetirableException
from proxysvc.transport.http.exception import LoopRetiredException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loops", tags=["loops"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class OptionBody(BaseModel):
    name: str
    key: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class LoopCreateRequest(BaseModel):
    name: str
    key: Optional[str] = None
    purpose: str = ""
    metric: Optional[str] = None
    engine: str = ENGINES.DEFAULT
    options: list[OptionBody]
    fallback: Optional[str] = None


class LoopRenameRequest(BaseModel):
    name: Optional[str] = None
    key: Optional[str] = None


class LoopResumeRequest(BaseModel):
    reason: Optional[str] = None


class LoopPauseRequest(BaseModel):
    reason: Optional[str] = None


class LoopCommitRequest(BaseModel):
    option: str = Field(description="The key of the option everyone gets.")
    reason: Optional[str] = None


class LoopReopenRequest(BaseModel):
    reason: Optional[str] = None


class LoopRetireRequest(BaseModel):
    reason: Optional[str] = None


class CycleStartRequest(BaseModel):
    options: Optional[list[OptionBody]] = Field(
        default=None, description="The new cycle's options, as at create."
    )
    engine: Optional[str] = Field(
        default=None, description="The new cycle's engine, such as spinoza:1."
    )
    fallback: Optional[str] = Field(
        default=None,
        description="Kept if its option stays; needed when it doesn't.",
    )
    reason: Optional[str] = None


class CycleResetRequest(BaseModel):
    reason: Optional[str] = None


class ContextRequest(BaseModel):
    context: Optional[list[dict[str, Any]]] = Field(
        ...,
        description=(
            "The properties the engine learns from, each with a name and a type: "
            '[{"name": "plan", "type": "categorical", "values": ["free", "pro"]}, '
            '{"name": "seats", "type": "numeric", "min": 1, "max": 500}, '
            '{"name": "returning", "type": "boolean"}]. Properties not declared '
            "are still recorded and usable in the audience; a value of the wrong "
            "type is learned as the property's default. null clears it."
        ),
    )
    reason: Optional[str] = None


class PropertyArrival(BaseModel):
    name: str
    type: str
    arrived: int
    readable: int
    last_value: Any = None


class UndeclaredArrival(BaseModel):
    name: str
    arrived: int


class ContextResponse(BaseModel):
    context: Optional[list[dict[str, Any]]] = None
    learns_from_context: bool
    since: str
    decisions: int
    properties: list[PropertyArrival]
    undeclared: list[UndeclaredArrival]


class DeliveryRequest(BaseModel):
    audience: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description=(
            "Conditions on context properties, all of which must hold: "
            '[{"property": "device", "operator": "is", "value": "mobile"}]. '
            "Operators: is, is_not, in, not_in, contains, not_contains, gt, gte, "
            "lt, lte. A request without the property never holds its condition. "
            "An empty list means everyone. Replaces the whole audience."
        ),
    )
    rollout: Optional[int] = Field(
        default=None,
        description=(
            "The share of the audience the loop decides for, 0 to 100. A unit "
            "keeps its place, so raising it only adds units."
        ),
    )
    schedule: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            'When the loop decides: {"hours": {"start": "09:00", "end": "18:00"}, '
            '"starts_on": "2026-12-01", "timezone": "Europe/Amsterdam"}. Hours run '
            "from start until end, past midnight if the start is later. The "
            "timezone is required with hours or a start date. Replaces the "
            "whole schedule."
        ),
    )
    fallback: Optional[str] = Field(
        default=None,
        description="The option everyone the loop isn't deciding for gets.",
    )
    reason: Optional[str] = None


class NoteRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=NOTE_MAX_LENGTH,
        description="Plain text. A note stays; a correction is a new note.",
    )


class LoopMetric(BaseModel):
    id: str
    name: str
    type: str
    window_seconds: int


class Person(BaseModel):
    id: str
    name: str


class OptionSummary(BaseModel):
    id: str
    key: str
    name: str


class OptionResponse(OptionSummary):
    config: dict[str, Any]


class CycleSummary(BaseModel):
    id: str
    number: int
    engine: str
    engine_version: str
    metric_version: str
    context: Optional[list[dict[str, Any]]] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


class CycleResponse(CycleSummary):
    options: list[OptionResponse]


class Who(BaseModel):
    kind: str
    user_id: Optional[str] = None
    name: Optional[str] = None


class Via(BaseModel):
    connection_id: str
    client: Optional[str] = None


class Decision(BaseModel):
    answer: Literal["approved", "declined"]
    who: Who
    at: Optional[str] = None
    where: Optional[str] = None
    reason: Optional[str] = None


class HistoryEntry(BaseModel):
    id: str
    kind: str
    verb: str
    at: Optional[str] = None
    status: Literal["applied", "undone", "waiting", "declined"]
    who: Who
    via: Optional[Via] = None
    reason: Optional[str] = None
    evidence: Optional[dict[str, Any]] = None
    note: Optional[str] = None
    request_id: Optional[str] = None
    undoes_id: Optional[str] = None
    level: Optional[Literal["own", "notify", "ask"]] = None
    asked_at: Optional[str] = None
    decision: Optional[Decision] = None


class LoopSummary(BaseModel):
    id: str
    key: str
    name: str
    purpose: str
    metric: LoopMetric
    engine: str
    state: str
    paused_from: Optional[str] = None
    committed: Optional[str] = None
    live_since: Optional[str] = None
    owner: Person
    fallback: str
    delivery: Delivery
    context: Optional[list[dict[str, Any]]] = None
    options: list[OptionSummary]
    cycle: Optional[CycleSummary] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LoopResponse(LoopSummary):
    options: list[OptionResponse]


class LoopDetail(LoopResponse):
    latest_change: Optional[HistoryEntry] = None


class OptionShare(BaseModel):
    key: str
    share: Optional[float] = None


class LoopResults(BaseModel):
    share: list[OptionShare]
    lift: Optional[float] = None
    early: bool
    decisions_per_second: float


class ServingResponse(BaseModel):
    loop: LoopResponse
    serving_within_seconds: int


class LoopListItem(LoopSummary):
    latest_change: Optional[HistoryEntry] = None
    results: Optional[LoopResults] = None


class LoopListResponse(BaseModel):
    loops: list[LoopListItem]
    next_cursor: Optional[str] = None


class CycleListResponse(BaseModel):
    cycles: list[CycleResponse]


class HistoryResponse(BaseModel):
    changes: list[HistoryEntry]
    next_cursor: Optional[str] = None


class ShareOption(BaseModel):
    key: str
    name: str
    decisions: int
    share: Optional[float] = None
    sealed: int
    waiting: int


class SeriesPoint(BaseModel):
    at: str
    decisions: list[int]


class Share(BaseModel):
    since: str
    until: str
    step_seconds: int
    options: list[ShareOption]
    series: list[SeriesPoint]


class LiftOption(BaseModel):
    key: str
    name: str
    sealed: int
    mean: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None


class Lift(BaseModel):
    value: Optional[float] = None
    early: bool
    since: str
    until: str
    options: list[LiftOption]


class Calls(BaseModel):
    live: int
    committed: int
    outside_delivery: int
    draft: int
    paused: int
    retired: int


class Outcomes(BaseModel):
    learned: int
    late: int
    duplicate: int
    earlier_cycle: int


class Health(BaseModel):
    decision_errors: int
    outcomes: Outcomes
    last_outcome_at: Optional[str] = None
    last_learned_at: Optional[str] = None
    ledger_lag_ms: Optional[int] = None


class ResultsResponse(BaseModel):
    cycle: Optional[CycleSummary] = None
    range: str
    share: Optional[Share] = None
    lift: Optional[Lift] = None
    calls: Calls
    decisions_per_second: float
    health: Health


LoopState = Literal["draft", "live", "committed", "paused", "retired"]
ResultsPeriod = Literal["24h", "7d", "cycle"]
PAGE_LIMIT = 50
PAGE_LIMIT_MAX = 200


def _serving(loop: dict) -> ServingResponse:
    return ServingResponse(
        loop=LoopResponse(**loop),
        serving_within_seconds=math.ceil(settings.experiment_cache_ttl),
    )


def _not_found(loop: str) -> LoopNotFoundException:
    return LoopNotFoundException(f"no loop with the key or id {loop!r}")


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=LoopListResponse,
)
async def list_loops(
    state: Optional[list[LoopState]] = Query(default=None),
    cursor: Optional[str] = None,
    limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT_MAX),
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """the workspace's loops, newest first, each with its latest change."""
    try:
        page = await get_proxy_service().list_loops(
            tenant_id, states=state or (), cursor=cursor, limit=limit
        )
    except InvalidCursorError as e:
        raise InvalidCursorException(str(e))
    return LoopListResponse(**page)


@router.get(
    "/{loop}",
    status_code=status.HTTP_200_OK,
    response_model=LoopDetail,
)
async def get_loop(
    loop: str,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """a loop by its key or its id."""
    found = await get_proxy_service().get_loop(tenant_id, loop)
    if found is None:
        raise _not_found(loop)
    return LoopDetail(**found)


@router.get(
    "/{loop}/cycles",
    status_code=status.HTTP_200_OK,
    response_model=CycleListResponse,
)
async def list_cycles(
    loop: str,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """a loop's cycles, newest first, each with its options as they were."""
    cycles = await get_proxy_service().list_cycles(tenant_id, loop)
    if cycles is None:
        raise _not_found(loop)
    return CycleListResponse(cycles=cycles)


@router.get(
    "/{loop}/history",
    status_code=status.HTTP_200_OK,
    response_model=HistoryResponse,
)
async def loop_history(
    loop: str,
    show: HistoryShow = "all",
    cursor: Optional[str] = None,
    limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT_MAX),
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """a loop's changes and notes, newest first: what, when, who, via and
    why. show narrows it to changes or to notes."""
    try:
        history = await get_proxy_service().loop_history(
            tenant_id, loop, show=show, cursor=cursor, limit=limit
        )
    except InvalidCursorError as e:
        raise InvalidCursorException(str(e))
    if history is None:
        raise _not_found(loop)
    return HistoryResponse(**history)


@router.post(
    "/{loop}/notes",
    status_code=status.HTTP_201_CREATED,
    response_model=HistoryEntry,
)
async def add_note(
    loop: str,
    body: NoteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """add a note to a loop's history, returned as its history reads it. it
    can't be undone or edited."""
    service = get_proxy_service()
    try:
        added = await service.add_note(tenant_id, loop, text=body.text, actor=actor)
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    if added is None:
        raise _not_found(loop)
    logger.info(f"note added: {added.change['id']} by user {actor.user_id}")
    return HistoryEntry(**await service.get_change_entry(tenant_id, added.change["id"]))


@router.get(
    "/{loop}/results",
    status_code=status.HTTP_200_OK,
    response_model=ResultsResponse,
)
async def loop_results(
    loop: str,
    cycle: Optional[int] = Query(default=None, ge=1),
    period: ResultsPeriod = Query(default="24h", alias="range"),
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """a cycle's results, the current one unless a number is given: how
    decisions are shared, what is waiting to seal, lift over an even split,
    the last hour's calls by reason, and its health counters."""
    try:
        results = await get_proxy_service().loop_results(
            tenant_id, loop, cycle_number=cycle, period=period
        )
    except CycleNotFoundError as e:
        raise CycleNotFoundException(str(e))
    if results is None:
        raise _not_found(loop)
    return ResultsResponse(**results)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=LoopResponse,
)
async def create_loop(
    body: LoopCreateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """create a draft loop with its options, metric and engine."""
    try:
        created = await get_proxy_service().create_loop(
            tenant_id,
            name=body.name,
            key=body.key,
            purpose=body.purpose,
            metric=body.metric,
            engine=body.engine,
            options=[option.model_dump() for option in body.options],
            fallback=body.fallback,
            actor=actor,
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopKeyTakenError as e:
        raise LoopKeyTakenException(str(e))
    logger.info(f"loop created: {created.value['id']} by user {actor.user_id}")
    return LoopResponse(**created.value)


@router.post(
    "/{loop}/launch",
    status_code=status.HTTP_200_OK,
    response_model=LoopResponse,
)
async def launch_loop(
    loop: str,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """launch a draft: its first cycle starts and it goes live."""
    try:
        launched = await get_proxy_service().launch_loop(tenant_id, loop, actor=actor)
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopStateError as e:
        raise LoopNotDraftException(str(e))
    if launched is None:
        raise _not_found(loop)
    logger.info(f"loop launched: {launched.value['id']} by user {actor.user_id}")
    return LoopResponse(**launched.value)


@router.delete(
    "/{loop}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_loop(
    loop: str,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """delete a draft; a loop that has launched is retired, never deleted."""
    try:
        deleted = await get_proxy_service().delete_loop(tenant_id, loop, actor=actor)
    except LoopStateError as e:
        raise LoopNotDraftException(str(e))
    if not deleted:
        raise _not_found(loop)
    logger.info(f"loop deleted: {loop} by user {actor.user_id}")


@router.patch(
    "/{loop}",
    status_code=status.HTTP_200_OK,
    response_model=LoopResponse,
)
async def rename_loop(
    loop: str,
    body: LoopRenameRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """rename a loop at any time; change its key only while it is a draft."""
    try:
        renamed = await get_proxy_service().rename_loop(
            tenant_id, loop, name=body.name, key=body.key, actor=actor
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopKeyTakenError as e:
        raise LoopKeyTakenException(str(e))
    except LoopStateError as e:
        raise LoopNotDraftException(str(e))
    if renamed is None:
        raise _not_found(loop)
    return LoopResponse(**renamed.value)


@router.post(
    "/{loop}/commit",
    status_code=status.HTTP_200_OK,
    response_model=LoopResponse,
)
async def commit_loop(
    loop: str,
    body: LoopCommitRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """commit a live loop to one option for everyone. it still decides, so
    that option keeps learning; reopen returns it to live."""
    try:
        committed = await get_proxy_service().commit_loop(
            tenant_id, loop, option=body.option, actor=actor, reason=body.reason
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopStateError as e:
        raise LoopNotLiveException(str(e))
    if committed is None:
        raise _not_found(loop)
    logger.info(f"loop committed: {committed.value['id']} by user {actor.user_id}")
    return LoopResponse(**committed.value)


@router.post(
    "/{loop}/reopen",
    status_code=status.HTTP_200_OK,
    response_model=LoopResponse,
)
async def reopen_loop(
    loop: str,
    body: Optional[LoopReopenRequest] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """reopen a committed loop: live again in the same cycle."""
    try:
        reopened = await get_proxy_service().reopen_loop(
            tenant_id, loop, actor=actor, reason=body.reason if body else None
        )
    except LoopStateError as e:
        raise LoopNotCommittedException(str(e))
    if reopened is None:
        raise _not_found(loop)
    logger.info(f"loop reopened: {reopened.value['id']} by user {actor.user_id}")
    return LoopResponse(**reopened.value)


@router.post(
    "/{loop}/retire",
    status_code=status.HTTP_200_OK,
    response_model=LoopResponse,
)
async def retire_loop(
    loop: str,
    body: Optional[LoopRetireRequest] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """retire a live or committed loop when its choice has left the product.
    apps that still call it get its fallback; it can't be undone."""
    try:
        retired = await get_proxy_service().retire_loop(
            tenant_id, loop, actor=actor, reason=body.reason if body else None
        )
    except LoopStateError as e:
        raise LoopNotRetirableException(str(e))
    if retired is None:
        raise _not_found(loop)
    logger.info(f"loop retired: {retired.value['id']} by user {actor.user_id}")
    return LoopResponse(**retired.value)


@router.post(
    "/{loop}/cycles",
    status_code=status.HTTP_200_OK,
    response_model=ServingResponse,
)
async def start_cycle(
    loop: str,
    body: CycleStartRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """start a new cycle with new options, a new engine or both, on a live or
    paused loop. the earlier cycle ends and stays readable; it can't be
    undone. serving moves on every replica within serving_within_seconds."""
    try:
        started = await get_proxy_service().start_cycle(
            tenant_id,
            loop,
            options=(
                [option.model_dump() for option in body.options]
                if body.options is not None
                else None
            ),
            engine=body.engine,
            fallback=body.fallback,
            actor=actor,
            reason=body.reason,
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopStateError as e:
        raise LoopNotCyclableException(str(e))
    if started is None:
        raise _not_found(loop)
    logger.info(f"cycle started: {started.value['id']} by user {actor.user_id}")
    return _serving(started.value)


@router.post(
    "/{loop}/cycles/reset",
    status_code=status.HTTP_200_OK,
    response_model=ServingResponse,
)
async def reset_cycle(
    loop: str,
    body: Optional[CycleResetRequest] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """start learning afresh: a new cycle with the same options, engine and
    fallback, on a live or paused loop. it can't be undone."""
    try:
        reset = await get_proxy_service().reset_cycle(
            tenant_id, loop, actor=actor, reason=body.reason if body else None
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopStateError as e:
        raise LoopNotCyclableException(str(e))
    if reset is None:
        raise _not_found(loop)
    logger.info(f"cycle reset: {reset.value['id']} by user {actor.user_id}")
    return _serving(reset.value)


@router.get(
    "/{loop}/context",
    status_code=status.HTTP_200_OK,
    response_model=ContextResponse,
)
async def get_context(
    loop: str,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """the context the loop's engine learns from, and what its decisions
    carried in the last day: for each declared property how many carried it
    and how many could be read, and the properties sent but not declared."""
    found = await get_proxy_service().loop_context(tenant_id, loop)
    if found is None:
        raise _not_found(loop)
    return ContextResponse(**found)


@router.put(
    "/{loop}/context",
    status_code=status.HTTP_200_OK,
    response_model=ServingResponse,
)
async def update_context(
    loop: str,
    body: ContextRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """declare which context properties the loop's engine learns from. on an
    engine that learns from context, a loop past draft starts a new cycle,
    which can't be undone; otherwise it can be undone. serving moves on every
    replica within serving_within_seconds."""
    try:
        updated = await get_proxy_service().update_context(
            tenant_id, loop, context=body.context, actor=actor, reason=body.reason
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopRetiredError as e:
        raise LoopRetiredException(str(e))
    except LoopStateError as e:
        raise LoopNotCyclableException(str(e))
    if updated is None:
        raise _not_found(loop)
    logger.info(f"context changed: {updated.value['id']} by user {actor.user_id}")
    return _serving(updated.value)


@router.put(
    "/{loop}/delivery",
    status_code=status.HTTP_200_OK,
    response_model=ServingResponse,
)
async def update_delivery(
    loop: str,
    body: DeliveryRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """change who the loop decides for, and what everyone else gets: its
    audience, rollout, schedule and fallback. a part left out keeps its
    value. it can be undone. serving moves on every replica within
    serving_within_seconds."""
    try:
        updated = await get_proxy_service().update_delivery(
            tenant_id,
            loop,
            audience=body.audience,
            rollout=body.rollout,
            schedule=body.schedule,
            fallback=body.fallback,
            actor=actor,
            reason=body.reason,
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopStateError as e:
        raise LoopRetiredException(str(e))
    if updated is None:
        raise _not_found(loop)
    logger.info(f"delivery changed: {updated.value['id']} by user {actor.user_id}")
    return _serving(updated.value)


@router.post(
    "/{loop}/resume",
    status_code=status.HTTP_200_OK,
    response_model=ServingResponse,
)
async def resume_loop(
    loop: str,
    body: Optional[LoopResumeRequest] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """resume a paused loop: it returns to the state it was paused from.
    serving moves on every replica within serving_within_seconds."""
    try:
        resumed = await get_proxy_service().resume_loop(
            tenant_id, loop, actor=actor, reason=body.reason if body else None
        )
    except LoopStateError as e:
        raise LoopNotPausedException(str(e))
    if resumed is None:
        raise _not_found(loop)
    logger.info(f"loop resumed: {resumed.value['id']} by user {actor.user_id}")
    return _serving(resumed.value)


@router.post(
    "/{loop}/pause",
    status_code=status.HTTP_200_OK,
    response_model=ServingResponse,
)
async def pause_loop(
    loop: str,
    body: Optional[LoopPauseRequest] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """pause a live or committed loop: everyone gets its fallback until a
    person resumes it. serving moves on every replica within
    serving_within_seconds."""
    try:
        paused = await get_proxy_service().pause_loop(
            tenant_id, loop, actor=actor, reason=body.reason if body else None
        )
    except LoopStateError as e:
        raise LoopNotPausableException(str(e))
    if paused is None:
        raise _not_found(loop)
    logger.info(f"loop paused: {paused.value['id']} by user {actor.user_id}")
    return _serving(paused.value)
