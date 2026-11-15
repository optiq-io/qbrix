from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import status
from pydantic import BaseModel

from proxysvc.core.error import LoopNotFoundError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import LoopNotFoundException
from proxysvc.transport.http.router.loop import PAGE_LIMIT
from proxysvc.transport.http.router.loop import PAGE_LIMIT_MAX
from proxysvc.transport.http.router.loop import Alert

router = APIRouter(prefix="/alerts", tags=["alerts"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class AlertList(BaseModel):
    alerts: list[Alert]


@router.get("", status_code=status.HTTP_200_OK, response_model=AlertList)
async def list_alerts(
    loop: Optional[str] = None,
    open: Optional[bool] = None,
    limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT_MAX),
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """the workspace's alerts, newest first: safety pauses and warnings, open
    or ended, each with how it ended."""
    try:
        found = await get_proxy_service().list_alerts(
            tenant_id, loop=loop, open=open, limit=limit
        )
    except LoopNotFoundError:
        raise LoopNotFoundException(f"no loop with the key or id {loop!r}")
    return AlertList(**found)
