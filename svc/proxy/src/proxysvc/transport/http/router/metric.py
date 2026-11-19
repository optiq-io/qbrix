from __future__ import annotations

import logging
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import MetricInUseError
from proxysvc.core.error import MetricInvalidError
from proxysvc.core.error import MetricNameTakenError
from proxysvc.mod.metric.service import DEFAULT_WINDOW_SECONDS
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_actor
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import ConflictException
from proxysvc.transport.http.exception import InvalidMetricException
from proxysvc.transport.http.exception import MetricInUseException
from proxysvc.transport.http.exception import MetricNameTakenException
from proxysvc.transport.http.exception import MetricNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class ScoreRangeBody(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    lo: float
    hi: float


class MetricCreateRequest(BaseModel):
    name: str
    semantic: str
    type: str
    range: Optional[ScoreRangeBody] = None
    window_seconds: int = DEFAULT_WINDOW_SECONDS


class MetricResponse(BaseModel):
    id: str
    name: str
    type: str
    range: Optional[ScoreRangeBody] = None
    version: str
    semantic: str
    window_seconds: int
    created_by: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MetricUpdateRequest(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="A new name; only while no decision has used the metric.",
    )
    window_seconds: Optional[int] = Field(
        default=None, description="A new window: a minor version."
    )
    semantic: Optional[str] = Field(
        default=None, description="What the metric stands for now."
    )
    semantic_change: Optional[Literal["reword", "same", "new"]] = Field(
        default=None,
        description="reword: the same meaning in other words, no new version. "
        "same: the same meaning, a minor version. new: a new meaning, a major "
        "version that starts a new cycle on every loop still deciding.",
    )
    reason: Optional[str] = None


class MetricDeleteRequest(BaseModel):
    reason: Optional[str] = None


class ChangeRef(BaseModel):
    id: str
    kind: str
    undoable: bool


class MetricCycleStarted(BaseModel):
    loop: str
    cycle: int


class MetricUpdatedResponse(BaseModel):
    metric: MetricResponse
    change: ChangeRef
    cycles: list[MetricCycleStarted] = Field(
        description="The cycles a new semantic started, one per loop."
    )


class MetricVersionAuthor(BaseModel):
    id: str
    name: str


class MetricVersionChange(BaseModel):
    field: str
    before: str
    after: str


class MetricVersionResponse(BaseModel):
    version: str
    semantic: str
    window_seconds: int
    created_by: MetricVersionAuthor
    created_at: Optional[str] = None
    reason: Optional[str] = None
    changed: list[MetricVersionChange]


class MetricDetailResponse(MetricResponse):
    versions: list[MetricVersionResponse] = Field(
        description="Every version, newest first."
    )


class MetricLoopResponse(BaseModel):
    id: str
    key: str
    name: str
    state: str


class MetricInUseResponse(MetricResponse):
    loops: list[MetricLoopResponse]


class MetricListResponse(BaseModel):
    metrics: list[MetricInUseResponse]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MetricResponse,
)
async def create_metric(
    body: MetricCreateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["metric:write"])),
):
    """create a metric at version 1.0."""
    try:
        created = await get_proxy_service().create_metric(
            tenant_id,
            name=body.name,
            semantic=body.semantic,
            metric_type=body.type,
            score_range=(body.range.lo, body.range.hi) if body.range else None,
            window_seconds=body.window_seconds,
            actor=actor,
        )
    except MetricInvalidError as e:
        raise InvalidMetricException(str(e))
    except MetricNameTakenError as e:
        raise MetricNameTakenException(str(e))
    logger.info(f"metric created: {created.value['id']} by user {actor.user_id}")
    return MetricResponse(**created.value)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=MetricListResponse,
)
async def list_metrics(
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["metric:read"])),
):
    """list every metric in the workspace, with the loops that use it."""
    metrics = await get_proxy_service().metrics_in_use(tenant_id)
    return MetricListResponse(metrics=[MetricInUseResponse(**m) for m in metrics])


def _not_found(metric: str) -> MetricNotFoundException:
    return MetricNotFoundException(f"no metric named or with id {metric!r}")


@router.get(
    "/{metric}",
    status_code=status.HTTP_200_OK,
    response_model=MetricDetailResponse,
)
async def get_metric(
    metric: str,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["metric:read"])),
):
    """get a metric by its name or its id, with its versions."""
    found = await get_proxy_service().metric_detail(tenant_id, metric)
    if found is None:
        raise _not_found(metric)
    return MetricDetailResponse(**found)


@router.patch(
    "/{metric}",
    status_code=status.HTTP_200_OK,
    response_model=MetricUpdatedResponse,
)
async def update_metric(
    metric: str,
    body: MetricUpdateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["metric:write"])),
):
    """change a metric's name, window or semantic. a new window is a minor
    version; a new semantic is reworded, the same (minor) or new (major, which
    starts a new cycle on every loop still deciding)."""
    try:
        updated = await get_proxy_service().update_metric(
            tenant_id,
            metric,
            name=body.name,
            window_seconds=body.window_seconds,
            semantic=body.semantic,
            semantic_change=body.semantic_change,
            actor=actor,
            reason=body.reason,
        )
    except MetricInvalidError as e:
        raise InvalidMetricException(str(e))
    except MetricNameTakenError as e:
        raise MetricNameTakenException(str(e))
    except MetricInUseError as e:
        raise MetricInUseException(str(e))
    except ChangeConflictError as e:
        raise ConflictException(str(e))
    if updated is None:
        raise _not_found(metric)
    logger.info(
        f"metric changed: {updated.value['metric']['id']} by user {actor.user_id}"
    )
    return MetricUpdatedResponse(**updated.value, change=updated.change)


@router.delete(
    "/{metric}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_metric(
    metric: str,
    body: Optional[MetricDeleteRequest] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["metric:write"])),
):
    """delete a metric no loop has used; once one has, it stays."""
    try:
        deleted = await get_proxy_service().delete_metric(
            tenant_id, metric, actor=actor, reason=body.reason if body else None
        )
    except MetricInUseError as e:
        raise MetricInUseException(str(e))
    if deleted is None:
        raise _not_found(metric)
    logger.info(f"metric deleted: {deleted.value['id']} by user {actor.user_id}")
