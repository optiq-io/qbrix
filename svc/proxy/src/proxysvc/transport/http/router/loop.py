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
from proxysvc.core.error import LoopStateError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_actor
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import CycleNotFoundException
from proxysvc.transport.http.exception import InvalidCursorException
from proxysvc.transport.http.exception import InvalidLoopException
from proxysvc.transport.http.exception import LoopKeyTakenException
from proxysvc.transport.http.exception import LoopNotDraftException
from proxysvc.transport.http.exception import LoopNotFoundException
from proxysvc.transport.http.exception import LoopNotPausedException

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


class HistoryEntry(BaseModel):
    id: str
    kind: str
    at: Optional[str] = None
    status: str
    who: Who
    via: Optional[Via] = None
    reason: Optional[str] = None
    evidence: Optional[dict[str, Any]] = None
    request_id: Optional[str] = None
    undoes_id: Optional[str] = None


class LoopSummary(BaseModel):
    id: str
    key: str
    name: str
    purpose: str
    metric: LoopMetric
    engine: str
    state: str
    paused_from: Optional[str] = None
    live_since: Optional[str] = None
    owner: Person
    fallback: str
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


class ResumeResponse(BaseModel):
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
    draft: int
    paused: int


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


LoopState = Literal["draft", "live", "paused"]
ResultsPeriod = Literal["24h", "7d", "cycle"]
PAGE_LIMIT = 50
PAGE_LIMIT_MAX = 200


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
    cursor: Optional[str] = None,
    limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT_MAX),
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """a loop's changes, newest first: what, when, who, via and why."""
    try:
        history = await get_proxy_service().loop_history(
            tenant_id, loop, cursor=cursor, limit=limit
        )
    except InvalidCursorError as e:
        raise InvalidCursorException(str(e))
    if history is None:
        raise _not_found(loop)
    return HistoryResponse(**history)


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
    return LoopResponse(**renamed)


@router.post(
    "/{loop}/resume",
    status_code=status.HTTP_200_OK,
    response_model=ResumeResponse,
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
    logger.info(f"loop resumed: {resumed['id']} by user {actor.user_id}")
    return ResumeResponse(
        loop=LoopResponse(**resumed),
        serving_within_seconds=math.ceil(settings.experiment_cache_ttl),
    )
