from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel

from proxysvc.core.actor import Actor
from proxysvc.core.error import KeyLabelError
from proxysvc.core.error import KeyLimitError
from proxysvc.core.error import KeyNotFoundError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import APIKeyLimitException
from proxysvc.transport.http.exception import InvalidKeyLabelException
from proxysvc.transport.http.exception import KeyNotFoundException

router = APIRouter(prefix="/keys", tags=["keys"])

ADMIN = "system:admin"

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class PersonRef(BaseModel):
    id: str
    name: str


class Key(BaseModel):
    """a workspace key. secret is present only in the response that made it."""

    id: str
    app: str
    environment: str
    created_by: Optional[PersonRef] = None
    created_at: str
    rotated_at: Optional[str] = None
    secret: Optional[str] = None


class KeyList(BaseModel):
    keys: list[Key]


class KeyRequest(BaseModel):
    app: str
    environment: str


class KeyRename(BaseModel):
    app: Optional[str] = None
    environment: Optional[str] = None


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=KeyList,
    response_model_exclude_none=True,
)
async def list_keys(
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes(["loop:read"])),
):
    """the workspace's active keys, for every role, never a secret."""
    return {"keys": await get_proxy_service().keys.list(tenant_id)}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Key,
    response_model_exclude_none=True,
)
async def create_key(
    body: KeyRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """create a key for an app and environment; the response carries its
    secret, and no later read does."""
    try:
        return await get_proxy_service().keys.create(
            tenant_id, app=body.app, environment=body.environment, actor=actor
        )
    except KeyLabelError as e:
        raise InvalidKeyLabelException(str(e))
    except KeyLimitError as e:
        raise APIKeyLimitException(str(e))


@router.patch(
    "/{key_id}",
    status_code=status.HTTP_200_OK,
    response_model=Key,
    response_model_exclude_none=True,
)
async def rename_key(
    key_id: str,
    body: KeyRename,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """change a key's app or environment; its secret stays the same."""
    try:
        return await get_proxy_service().keys.rename(
            tenant_id, key_id, app=body.app, environment=body.environment
        )
    except KeyLabelError as e:
        raise InvalidKeyLabelException(str(e))
    except KeyNotFoundError as e:
        raise KeyNotFoundException(str(e))


@router.post(
    "/{key_id}/rotate",
    status_code=status.HTTP_200_OK,
    response_model=Key,
    response_model_exclude_none=True,
)
async def rotate_key(
    key_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """replace a key's secret; the response carries the new one once, and the
    old one is refused at once."""
    try:
        return await get_proxy_service().keys.rotate(tenant_id, key_id)
    except KeyNotFoundError as e:
        raise KeyNotFoundException(str(e))


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """revoke a key; calls made with it are refused at once."""
    try:
        await get_proxy_service().keys.revoke(tenant_id, key_id)
    except KeyNotFoundError as e:
        raise KeyNotFoundException(str(e))
