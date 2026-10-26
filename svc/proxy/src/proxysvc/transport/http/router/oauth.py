from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from proxysvc.core.actor import Actor
from proxysvc.core.error import OAuthError
from proxysvc.core.error import OAuthRedirectError
from proxysvc.core.error import OAuthRequestNotFoundError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_current_user
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.exception import OAuthRequestNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])
request_router = APIRouter(prefix="/connections/requests", tags=["connections"])

_proxy_service: Optional[ProxyService] = None

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


def _oauth_error(error: OAuthError) -> JSONResponse:
    return JSONResponse(
        status_code=401 if error.error == "invalid_client" else 400,
        content={"error": error.error, "error_description": error.description},
        headers=_NO_STORE,
    )


async def _form(request: Request) -> dict[str, str]:
    """the token and revocation endpoints take application/x-www-form-urlencoded."""
    body = (await request.body()).decode(errors="replace")
    return dict(parse_qsl(body, keep_blank_values=True))


@router.get("/.well-known/oauth-authorization-server")
async def metadata():
    return get_proxy_service().oauth.metadata()


@router.post("/oauth/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _oauth_error(
            OAuthError("invalid_client_metadata", "the body must be a json object")
        )
    try:
        client = await get_proxy_service().oauth.register(body)
    except OAuthError as e:
        return _oauth_error(e)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content=client, headers=_NO_STORE
    )


@router.get("/oauth/authorize")
async def authorize(request: Request):
    oauth = get_proxy_service().oauth
    try:
        location = await oauth.authorize(dict(request.query_params))
    except OAuthRedirectError as e:
        location = oauth.error_redirect(e)
    except OAuthError as e:
        return _oauth_error(e)
    return RedirectResponse(location, status_code=status.HTTP_302_FOUND)


@router.post("/oauth/token")
async def token(request: Request):
    try:
        tokens = await get_proxy_service().oauth.token(await _form(request))
    except OAuthError as e:
        return _oauth_error(e)
    return JSONResponse(content=tokens, headers=_NO_STORE)


@router.post("/oauth/revoke")
async def revoke(request: Request):
    """rfc 7009: answers 200 whether or not the token was known."""
    form = await _form(request)
    if form.get("token"):
        await get_proxy_service().oauth.revoke(form["token"])
    return JSONResponse(content={}, headers=_NO_STORE)


class DecisionBody(BaseModel):
    approve: bool


@request_router.get("/{request_id}")
async def get_request(
    request_id: str,
    _person: Actor = Depends(get_person),
    user=Depends(get_current_user),
):
    """what the console's approval page shows."""
    try:
        return await get_proxy_service().oauth.get_request(
            request_id, name=user.name or user.email, email=user.email
        )
    except OAuthRequestNotFoundError as e:
        raise OAuthRequestNotFoundException(str(e))


@request_router.post("/{request_id}")
async def decide(
    request_id: str,
    body: DecisionBody,
    person: Actor = Depends(get_person),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """approve or deny; returns where to send the browser back to the client."""
    try:
        redirect_to = await get_proxy_service().oauth.decide(
            request_id,
            user_id=person.user_id,
            tenant_id=tenant_id,
            approve=body.approve,
        )
    except OAuthRequestNotFoundError as e:
        raise OAuthRequestNotFoundException(str(e))
    return {"redirect_to": redirect_to}
