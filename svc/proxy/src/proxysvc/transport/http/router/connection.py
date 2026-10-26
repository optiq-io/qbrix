from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status

from proxysvc.core.actor import Actor
from proxysvc.core.error import ConnectionNotFoundError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_active_user
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.exception import ConnectionNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


@router.get("", status_code=status.HTTP_200_OK)
async def list_connections(
    person: Actor = Depends(get_person),
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_active_user),
):
    """an admin sees every connection in the workspace; anyone else their own."""
    connections = await get_proxy_service().connections.list(
        tenant_id, user_id=person.user_id, role=user.role
    )
    return {"connections": connections}


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connection(
    connection_id: str,
    person: Actor = Depends(get_person),
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_active_user),
):
    try:
        await get_proxy_service().connections.revoke(
            tenant_id, connection_id, user_id=person.user_id, role=user.role
        )
    except ConnectionNotFoundError as e:
        raise ConnectionNotFoundException(str(e))
