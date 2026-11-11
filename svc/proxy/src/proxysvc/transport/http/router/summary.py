from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel

from proxysvc.core.error import SummaryRangeError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import SummaryRangeException
from proxysvc.transport.http.router.change import ChangeCounts
from proxysvc.transport.http.router.loop import HistoryEntry
from proxysvc.transport.http.router.loop import Who
from proxysvc.transport.http.router.milestone import Milestone

router = APIRouter(prefix="/summary", tags=["summary"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class SummaryMetric(BaseModel):
    id: str
    name: str
    type: str


class SummaryOptionShare(BaseModel):
    key: str
    name: str
    share: Optional[float] = None


class ShareAt(BaseModel):
    at: str
    cycle: int
    options: list[SummaryOptionShare]


class ShareThenNow(BaseModel):
    then: Optional[ShareAt] = None
    now: Optional[ShareAt] = None


class Recovery(BaseModel):
    at: str
    who: Who
    via: Optional[str] = None
    change_id: str


class Alert(BaseModel):
    kind: Literal["safety_pause"]
    signal: Optional[str] = None
    opened_at: str
    evidence: Optional[dict[str, Any]] = None
    change_id: str
    recovered: Optional[Recovery] = None


class ChangesByWho(BaseModel):
    who: Who
    via: Optional[str] = None
    count: int
    changes: list[HistoryEntry]


class LoopWeek(BaseModel):
    id: str
    key: str
    name: str
    state: str
    committed: Optional[str] = None
    metric: SummaryMetric
    share: ShareThenNow
    lift: Optional[float] = None
    early: bool
    alerts: list[Alert]
    milestones: list[Milestone]
    changes: list[ChangesByWho]


class OldDraft(BaseModel):
    id: str
    key: str
    name: str
    created_at: str


class Drafts(BaseModel):
    count: int
    older_than_7_days: list[OldDraft]


class WeekSummary(BaseModel):
    since: str
    until: str
    loops: list[LoopWeek]
    drafts: Drafts
    changes: ChangeCounts


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=WeekSummary,
)
async def workspace_summary(
    since: Optional[datetime] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """the workspace since a moment, seven days back by default: each live,
    paused and committed loop's share then and now, lift, safety pauses and
    their recoveries, milestones and changes by who; the drafts; and the
    workspace's change counts."""
    try:
        found = await get_proxy_service().workspace_summary(tenant_id, since)
    except SummaryRangeError as e:
        raise SummaryRangeException(str(e))
    return WeekSummary(**found)
