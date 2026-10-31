from __future__ import annotations

import logging
from typing import Any
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import status
from pydantic import BaseModel

from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeMovedError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.core.error import ExperimentLimitError
from proxysvc.core.error import ExperimentRunningError
from proxysvc.core.error import InvalidCursorError
from proxysvc.core.error import LoopKeyTakenError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import LoopStateError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.mod.auth.scope import ROLE_SCOPES
from proxysvc.mod.change.undo import undo_scope
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_active_user
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_person
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import ChangeNotFoundException
from proxysvc.transport.http.exception import ChangeNotUndoableException
from proxysvc.transport.http.exception import InsufficientScopesException
from proxysvc.transport.http.exception import InvalidCursorException
from proxysvc.transport.http.exception import LoopNotFoundException
from proxysvc.transport.http.exception import MetricNotFoundException
from proxysvc.transport.http.router.loop import HistoryEntry
from proxysvc.transport.http.router.loop import PAGE_LIMIT
from proxysvc.transport.http.router.loop import PAGE_LIMIT_MAX
from proxysvc.transport.http.router.loop import Who

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/changes", tags=["changes"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class ChangeTarget(BaseModel):
    type: str
    id: str
    key: Optional[str] = None
    name: Optional[str] = None


class ActorMark(BaseModel):
    kind: Literal["member", "connection", "qbrix"]
    name: Optional[str] = None
    on_behalf_of: Optional[str] = None
    via: Optional[str] = None


class Piece(BaseModel):
    """one part of a change's sentence. actor carries the actor, the others a
    text or a name."""

    kind: Literal["actor", "text", "loop", "metric"]
    actor: Optional[ActorMark] = None
    text: Optional[str] = None
    name: Optional[str] = None


class Difference(BaseModel):
    field: str
    before: Optional[str] = None
    after: Optional[str] = None


class UndoneBy(BaseModel):
    id: str
    who: Who
    at: str


class ChangeEntry(HistoryEntry):
    api_key_id: Optional[str] = None
    target: ChangeTarget
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    pieces: list[Piece]
    diff: list[Difference]
    undoable: bool
    not_undoable_reason: Optional[str] = None
    undone_by: Optional[UndoneBy] = None
    count: int
    first_at: Optional[str] = None
    ids: list[str]


class ChangePage(BaseModel):
    changes: list[ChangeEntry]
    next_cursor: Optional[str] = None


class UndoRequest(BaseModel):
    reason: Optional[str] = None


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ChangePage,
)
async def list_changes(
    who: Optional[list[Literal["member", "connection", "qbrix"]]] = Query(default=None),
    kind: Optional[list[str]] = Query(default=None),
    loop: Optional[str] = None,
    metric: Optional[str] = None,
    undoable: Optional[bool] = None,
    fold: bool = True,
    cursor: Optional[str] = None,
    limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT_MAX),
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """every change in the workspace, newest first, with bursts folded."""
    try:
        page = await get_proxy_service().list_workspace_changes(
            tenant_id,
            who=who or (),
            kinds=kind or (),
            loop=loop,
            metric=metric,
            undoable=undoable,
            fold=fold,
            cursor=cursor,
            limit=limit,
        )
    except InvalidCursorError as e:
        raise InvalidCursorException(str(e))
    except LoopNotFoundError:
        raise LoopNotFoundException(f"no loop with the key or id {loop!r}")
    except MetricNotFoundError:
        raise MetricNotFoundException(f"no metric named or with id {metric!r}")
    return ChangePage(**page)


@router.get(
    "/{change_id}",
    status_code=status.HTTP_200_OK,
    response_model=ChangeEntry,
)
async def get_change(
    change_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["loop:read"])),
):
    """one change, unfolded."""
    entry = await get_proxy_service().get_change_entry(tenant_id, change_id)
    if entry is None:
        raise ChangeNotFoundException(f"no change with the id {change_id!r}")
    return ChangeEntry(**entry)


@router.post(
    "/{change_id}/undo",
    status_code=status.HTTP_200_OK,
    response_model=ChangeEntry,
)
async def undo_change(
    change_id: str,
    body: Optional[UndoRequest] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_person),
    user=Depends(get_current_active_user),
):
    """undo a change by writing its inverse, and return the new change."""
    service = get_proxy_service()
    change = await service.get_change(tenant_id, change_id)
    if change is None:
        raise ChangeNotFoundException(f"no change with the id {change_id!r}")
    scope = undo_scope(change["target_type"])
    if scope not in ROLE_SCOPES.get(user.role, ()):
        raise InsufficientScopesException(f"required scope '{scope}' not available")
    try:
        undo = await service.undo_change(
            tenant_id,
            change_id,
            actor=actor,
            reason=body.reason if body else None,
            plan_tier=user.plan_tier,
        )
    except ChangeMovedError as e:
        raise ChangeNotUndoableException(
            str(e), context={"later_change_id": e.later_change_id}
        )
    except (
        ChangeNotUndoableError,
        ChangeConflictError,
        ExperimentLimitError,
        ExperimentRunningError,
        LoopKeyTakenError,
        LoopStateError,
    ) as e:
        raise ChangeNotUndoableException(str(e))
    logger.info(f"change undone: {change_id} by user {actor.user_id}")
    return ChangeEntry(**await service.get_change_entry(tenant_id, undo["id"]))
