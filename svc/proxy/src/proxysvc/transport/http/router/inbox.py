from __future__ import annotations

from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel

from proxysvc.core.actor import Actor
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.router.change import ChangeEntry
from proxysvc.transport.http.router.summary import Alert

router = APIRouter(prefix="/inbox", tags=["inbox"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class Asked(BaseModel):
    """how often the connection asked for this kind lately, and how many of
    those were approved: what raising its level rests on."""

    kind: str
    count: int
    approved: int
    since: str


class LoopRef(BaseModel):
    id: str
    key: str
    name: str


class InboxItem(BaseModel):
    """one item, in one shape: a change carries change (and asked while it
    waits), an alert carries its loop and alert."""

    kind: Literal["change", "safety_pause"]
    at: str
    change: Optional[ChangeEntry] = None
    asked: Optional[Asked] = None
    loop: Optional[LoopRef] = None
    alert: Optional[Alert] = None


class Inbox(BaseModel):
    waiting: list[InboxItem]
    notified: list[InboxItem]
    alerts: list[InboxItem]
    suggestions: list[InboxItem]


class InboxCount(BaseModel):
    waiting: int


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=Inbox,
)
async def read_inbox(
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes(["loop:read"])),
):
    """the reader's inbox: changes waiting on them, oldest first; what their
    connections did at act and notify in the last seven days, newest first;
    the workspace's loops paused by qbrix; and suggestions."""
    found = await get_proxy_service().inbox(tenant_id, actor.user_id, user.role)
    return Inbox(**found)


@router.get(
    "/count",
    status_code=status.HTTP_200_OK,
    response_model=InboxCount,
)
async def count_inbox(
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes(["loop:read"])),
):
    """how many changes wait on the reader, for the navigation's count."""
    found = await get_proxy_service().inbox_count(tenant_id, actor.user_id, user.role)
    return InboxCount(**found)
