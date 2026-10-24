from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel
from pydantic import ConfigDict

from proxysvc.core.actor import Actor
from proxysvc.core.error import MetricInvalidError
from proxysvc.core.error import MetricNameTakenError
from proxysvc.mod.metric.service import DEFAULT_WINDOW_SECONDS
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_actor
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import InvalidMetricException
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


class MetricListResponse(BaseModel):
    metrics: list[MetricResponse]


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
        metric = await get_proxy_service().create_metric(
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
    logger.info(f"metric created: {metric['id']} by user {actor.user_id}")
    return MetricResponse(**metric)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=MetricListResponse,
)
async def list_metrics(
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["metric:read"])),
):
    """list every metric in the workspace."""
    metrics = await get_proxy_service().list_metrics(tenant_id)
    return MetricListResponse(metrics=[MetricResponse(**m) for m in metrics])


@router.get(
    "/{metric}",
    status_code=status.HTTP_200_OK,
    response_model=MetricResponse,
)
async def get_metric(
    metric: str,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["metric:read"])),
):
    """get a metric by its name or its id."""
    found = await get_proxy_service().get_metric(tenant_id, metric)
    if found is None:
        raise MetricNotFoundException(f"no metric named or with id {metric!r}")
    return MetricResponse(**found)
