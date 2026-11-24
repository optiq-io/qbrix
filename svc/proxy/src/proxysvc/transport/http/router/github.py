from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import Response
from fastapi import status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pydantic import Field

from qbrixlog import get_logger

from proxysvc.core.actor import Actor
from proxysvc.core.error import GitHubAlreadyConnectedError
from proxysvc.core.error import GitHubNotConnectedError
from proxysvc.core.error import GitHubSignatureError
from proxysvc.core.error import GitHubStateError
from proxysvc.core.error import GitHubUnavailableError
from proxysvc.mod.auth import operator
from proxysvc.mod.github.service import ORGANISATION
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import GitHubAlreadyConnectedException
from proxysvc.transport.http.exception import GitHubNotConnectedException
from proxysvc.transport.http.exception import GitHubSignatureException
from proxysvc.transport.http.exception import GitHubUnavailableException

logger = get_logger(__name__)

router = APIRouter(prefix="/github", tags=["github"])

ADMIN = "system:admin"

INSTALLED = "installed"
REQUESTED = "requested"
STATE = "state"
ALREADY_CONNECTED = "already_connected"
UNAVAILABLE = "unavailable"

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


class Repository(BaseModel):
    full_name: str
    mentions: int
    last_mention: Optional[str] = None


class GitHub(BaseModel):
    """the workspace's github connection. reachable is null while nothing
    says either way, and repositories is null when github couldn't be asked."""

    connected: bool
    owner: Optional[str] = None
    set_up_by: Optional[PersonRef] = None
    at: Optional[str] = None
    repositories: Optional[list[Repository]]
    reachable: Optional[bool]
    reach_note: Optional[str] = None
    manage_url: Optional[str] = None
    install_url: Optional[str] = None


class ConnectRequest(BaseModel):
    organisation: Optional[str] = Field(
        default=None, pattern=f"^{ORGANISATION.pattern}$", max_length=39
    )


class Connect(BaseModel):
    """what the console posts to github: the manifest as the form's only
    field, to form_action."""

    form_action: str
    manifest: dict


class Disconnected(BaseModel):
    app_settings_url: str


def _is_admin(user) -> bool:
    return ADMIN in operator.auth_operator.get_scopes_for_role(user.role)


def _back(outcome: str) -> RedirectResponse:
    page = get_proxy_service().github.settings_page
    return RedirectResponse(
        f"{page}?{urlencode({'github': outcome})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("", status_code=status.HTTP_200_OK, response_model=GitHub)
async def read_github(
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(require_scopes(["loop:read"])),
):
    """whether the workspace has connected github, who set it up, the
    repositories it may see, and whether github can reach this install."""
    return await get_proxy_service().github.read(
        tenant_id, admin_id=user.id if _is_admin(user) else None
    )


@router.post("/connect", status_code=status.HTTP_200_OK, response_model=Connect)
async def connect_github(
    body: ConnectRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """the manifest for the workspace's own app, made on the admin's account
    or the organisation named."""
    try:
        return await get_proxy_service().github.connect(
            tenant_id, body.organisation, actor=actor
        )
    except GitHubAlreadyConnectedError as e:
        raise GitHubAlreadyConnectedException(str(e))


@router.get("/created", include_in_schema=False)
async def app_created(code: str = "", state: str = ""):
    """github sends the admin here once the app exists; they go on to
    install it."""
    try:
        install_url = await get_proxy_service().github.created(code, state)
    except GitHubStateError as e:
        logger.warning(f"github created callback refused: {e}")
        return _back(STATE)
    except GitHubAlreadyConnectedError:
        return _back(ALREADY_CONNECTED)
    except GitHubUnavailableError as e:
        logger.warning(f"github manifest conversion failed: {e}")
        return _back(UNAVAILABLE)
    return RedirectResponse(install_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/installed", include_in_schema=False)
async def app_installed(
    installation_id: Optional[int] = None,
    setup_action: str = "",
    state: str = "",
):
    """github sends the admin here once the app is installed, or once they
    asked an organisation owner to install it."""
    if installation_id is None:
        return _back(REQUESTED if setup_action == "request" else STATE)
    try:
        await get_proxy_service().github.installed(installation_id, state)
    except GitHubStateError as e:
        logger.warning(f"github installed callback refused: {e}")
        return _back(STATE)
    except GitHubUnavailableError as e:
        logger.warning(f"github installation check failed: {e}")
        return _back(UNAVAILABLE)
    return _back(INSTALLED)


@router.post(
    "/events/{events_token}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def receive_event(events_token: str, request: Request):
    """where the workspace's app sends its events."""
    try:
        await get_proxy_service().github.event(
            events_token, request.headers, await request.body()
        )
    except GitHubNotConnectedError as e:
        raise GitHubNotConnectedException(str(e))
    except GitHubSignatureError as e:
        raise GitHubSignatureException(str(e))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_200_OK, response_model=Disconnected)
async def disconnect_github(
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(require_scopes([ADMIN])),
):
    """remove the installation on github and the credentials here; the
    result says where the app's owner deletes the app itself."""
    try:
        return await get_proxy_service().github.disconnect(tenant_id, actor=actor)
    except GitHubNotConnectedError as e:
        raise GitHubNotConnectedException(str(e))
    except GitHubUnavailableError as e:
        raise GitHubUnavailableException(str(e))
