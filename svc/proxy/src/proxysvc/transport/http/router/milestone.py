from __future__ import annotations

from datetime import datetime
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import status
from pydantic import BaseModel

from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import LoopNotFoundException
from proxysvc.transport.http.exception import MetricNotFoundException
from proxysvc.transport.http.router.change import Difference
from proxysvc.transport.http.router.loop import PAGE_LIMIT
from proxysvc.transport.http.router.loop import PAGE_LIMIT_MAX

router = APIRouter(prefix="/events", tags=["events"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class EventLoop(BaseModel):
    id: str
    key: str
    name: str


class EventPiece(BaseModel):
    """one part of an event's sentence: a text, or the name of a loop or an
    option."""

    kind: Literal["text", "loop", "option"]
    text: Optional[str] = None
    name: Optional[str] = None


class Event(BaseModel):
    id: str
    kind: str
    at: str
    first_at: Optional[str] = None
    count: int
    loop: EventLoop
    cycle_id: Optional[str] = None
    source: str
    pieces: list[EventPiece]
    diff: list[Difference]


class EventList(BaseModel):
    events: list[Event]


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=EventList,
)
async def list_events(
    loop: Optional[str] = None,
    metric: Optional[str] = None,
    kind: Optional[list[str]] = Query(default=None),
    since: Optional[datetime] = None,
    limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT_MAX),
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """what the workspace's loops reached, newest first."""
    try:
        found = await get_proxy_service().list_events(
            tenant_id,
            loop=loop,
            metric=metric,
            kinds=kind or (),
            since=since,
            limit=limit,
        )
    except LoopNotFoundError:
        raise LoopNotFoundException(f"no loop with the key or id {loop!r}")
    except MetricNotFoundError:
        raise MetricNotFoundException(f"no metric named or with id {metric!r}")
    return EventList(**found)
