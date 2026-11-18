from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional
from typing import Union

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from proxysvc.core.error import InvalidOutcomeError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.core.error import TokenInvalidError
from proxysvc.mod.loop.track import BATCH_MAX
from proxysvc.mod.loop.track import TrackEvent
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import BaseAPIException
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.transport.http.exception import InvalidDecisionsException
from proxysvc.transport.http.exception import InvalidOutcomeException
from proxysvc.transport.http.exception import MetricNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["track"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class TrackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(description="The metric's name, as code sends it.")
    value: Any = Field(description="The outcome, valid for the metric's type.")
    decisions: Any = Field(
        default=None,
        description="The decisions token decisions() returns. The event credits "
        "exactly the decisions in it whose loop improves the metric.",
    )
    unit: Optional[str] = Field(
        default=None,
        description="Who or what the event happened to, the unit sent with "
        "select. Matched to its open decisions when the event carries none.",
    )
    id: Any = Field(
        default=None,
        description="Makes the event idempotent: a repeat with the same id "
        "counts once. A fresh id when absent.",
    )
    at: Optional[datetime] = Field(
        default=None,
        description="When it happened, ISO 8601 (UTC without an offset). "
        "Arrival time when absent.",
    )

    def event(self) -> TrackEvent:
        return TrackEvent(
            metric=self.metric,
            value=self.value,
            decisions=self.decisions,
            unit=self.unit,
            id=self.id,
            at=self.at,
        )


class TrackBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TrackRequest] = Field(min_length=1, max_length=BATCH_MAX)


class TrackResponse(BaseModel):
    id: str
    at: datetime
    credited: Optional[int] = Field(
        description="How many decisions the event credits; null when it waits "
        "to be matched by its unit."
    )


class TrackError(BaseModel):
    code: str
    detail: str


class TrackResult(BaseModel):
    """one event's result in a batch: what was recorded, or why it wasn't."""

    id: Optional[str] = None
    at: Optional[datetime] = None
    credited: Optional[int] = None
    error: Optional[TrackError] = None


class TrackBatchResponse(BaseModel):
    results: list[TrackResult]


def _answer(answer: dict) -> dict:
    return {
        "id": answer["id"],
        "at": datetime.fromtimestamp(answer["at_ms"] / 1000, tz=timezone.utc),
        "credited": answer["credited"],
    }


def _http_error(error: Exception) -> BaseAPIException:
    if isinstance(error, TokenInvalidError):
        return InvalidDecisionsException(str(error))
    if isinstance(error, InvalidOutcomeError):
        return InvalidOutcomeException(str(error))
    if isinstance(error, MetricNotFoundError):
        return MetricNotFoundException(str(error))
    return InternalServerException()


@router.post(
    "/track",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Union[TrackResponse, TrackBatchResponse],
)
async def track(
    body: Union[TrackBatchRequest, TrackRequest],
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["agent:write"])),
):
    """an event for a metric, or a batch of up to 500, each answered in order."""
    service = get_proxy_service()
    try:
        if isinstance(body, TrackBatchRequest):
            results = await service.track_batch(
                tenant_id, [event.event() for event in body.events]
            )
            return TrackBatchResponse(results=[_result(r) for r in results])
        return TrackResponse(**_answer(await service.track(tenant_id, body.event())))
    except (TokenInvalidError, InvalidOutcomeError, MetricNotFoundError) as e:
        raise _http_error(e)
    except Exception as e:
        logger.error(f"track: {e}")
        raise InternalServerException()


def _result(result: dict | Exception) -> TrackResult:
    if isinstance(result, Exception):
        error = _http_error(result)
        return TrackResult(error=TrackError(code=error.code, detail=error.detail))
    return TrackResult(**_answer(result))
