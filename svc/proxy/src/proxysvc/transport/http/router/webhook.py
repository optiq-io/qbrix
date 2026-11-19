from __future__ import annotations

from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Response
from fastapi import status
from pydantic import BaseModel

from proxysvc.core.actor import Actor
from proxysvc.core.error import WebhookNotFoundError
from proxysvc.core.error import WebhookURLError
from proxysvc.mod.auth import operator
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import ForbiddenException
from proxysvc.transport.http.exception import InvalidWebhookURLException
from proxysvc.transport.http.exception import WebhookNotFoundException

router = APIRouter(prefix="/webhook", tags=["webhook"])

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


class AttemptResult(BaseModel):
    at: str
    status_code: Optional[int] = None
    error: Optional[str] = None


class Delivery(BaseModel):
    """one message to the webhook: what it carried, and each attempt."""

    id: str
    kind: Literal["alert", "test"]
    summary: str
    status: Literal["pending", "delivered", "failing", "gave_up", "failed"]
    attempts: int
    results: list[AttemptResult]
    last_status_code: Optional[int] = None
    last_error: Optional[str] = None
    sent_by: Optional[PersonRef] = None
    created_at: str
    delivered_at: Optional[str] = None


class Webhook(BaseModel):
    """the workspace's webhook. url is present only when an admin reveals it,
    and secret only in the response that made it."""

    configured: bool
    url_masked: Optional[str] = None
    url: Optional[str] = None
    secret_hint: Optional[str] = None
    secret: Optional[str] = None
    created_by: Optional[PersonRef] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deliveries: list[Delivery]


class WebhookRequest(BaseModel):
    url: str


def _is_admin(user) -> bool:
    return ADMIN in operator.auth_operator.get_scopes_for_role(user.role)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=Webhook,
    response_model_exclude_none=True,
)
async def read_webhook(
    reveal: bool = False,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes(["loop:read"])),
):
    """whether the workspace has a webhook, its address up to the host, and
    its last five deliveries, for every role. only an admin reveals the
    whole address."""
    webhooks = get_proxy_service().webhooks
    if reveal:
        if not _is_admin(user):
            raise ForbiddenException("only an admin can reveal the webhook's address")
        webhooks.log_reveal(tenant_id, actor=actor)
    return await webhooks.read(tenant_id, reveal=reveal)


@router.put(
    "",
    status_code=status.HTTP_200_OK,
    response_model=Webhook,
    response_model_exclude_none=True,
)
async def put_webhook(
    body: WebhookRequest,
    response: Response,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """set the workspace's webhook address. the first time, the response
    carries the signing secret, and no later read does."""
    try:
        found = await get_proxy_service().webhooks.put(tenant_id, body.url, actor=actor)
    except WebhookURLError as e:
        raise InvalidWebhookURLException(str(e))
    if "secret" in found:
        response.status_code = status.HTTP_201_CREATED
    return found


@router.post(
    "/secret",
    status_code=status.HTTP_200_OK,
    response_model=Webhook,
    response_model_exclude_none=True,
)
async def regenerate_secret(
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """replace the signing secret; the response carries the new one once."""
    try:
        return await get_proxy_service().webhooks.regenerate(tenant_id, actor=actor)
    except WebhookNotFoundError as e:
        raise WebhookNotFoundException(str(e))


@router.post(
    "/test",
    status_code=status.HTTP_200_OK,
    response_model=Delivery,
    response_model_exclude_none=True,
)
async def send_test(
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """send a test message now and return how it went."""
    try:
        return await get_proxy_service().webhooks.test(tenant_id, actor=actor)
    except WebhookNotFoundError as e:
        raise WebhookNotFoundException(str(e))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def remove_webhook(
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """remove the webhook and every delivery it made."""
    try:
        await get_proxy_service().webhooks.remove(tenant_id, actor=actor)
    except WebhookNotFoundError as e:
        raise WebhookNotFoundException(str(e))
