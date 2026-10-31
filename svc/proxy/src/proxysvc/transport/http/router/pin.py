from __future__ import annotations

import logging
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status

from proxysvc.core.actor import Actor
from proxysvc.core.error import PinTargetNotFoundError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.exception import PinTargetNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pins", tags=["pins"])

_proxy_service: Optional[ProxyService] = None

PinKind = Literal["loop", "metric"]


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


@router.get("", status_code=status.HTTP_200_OK)
async def list_pins(
    person: Actor = Depends(get_person),
    tenant_id: str = Depends(get_current_tenant_id),
):
    pins = await get_proxy_service().pins.list(tenant_id, person.user_id)
    return {"pins": pins}


@router.put("/{kind}/{ref}", status_code=status.HTTP_204_NO_CONTENT)
async def pin(
    kind: PinKind,
    ref: str,
    person: Actor = Depends(get_person),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        await get_proxy_service().pins.pin(tenant_id, person.user_id, kind, ref)
    except PinTargetNotFoundError as e:
        raise PinTargetNotFoundException(str(e))


@router.delete("/{kind}/{ref}", status_code=status.HTTP_204_NO_CONTENT)
async def unpin(
    kind: PinKind,
    ref: str,
    person: Actor = Depends(get_person),
):
    await get_proxy_service().pins.unpin(person.user_id, kind, ref)
