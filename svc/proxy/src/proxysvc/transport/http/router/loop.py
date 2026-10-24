from __future__ import annotations

import logging
from typing import Any
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel
from pydantic import Field

from qbrixcore.engine import ENGINES

from proxysvc.core.actor import Actor
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopKeyTakenError
from proxysvc.core.error import LoopStateError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_actor
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import InvalidLoopException
from proxysvc.transport.http.exception import LoopKeyTakenException
from proxysvc.transport.http.exception import LoopNotDraftException
from proxysvc.transport.http.exception import LoopNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loops", tags=["loops"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class OptionBody(BaseModel):
    name: str
    key: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class LoopCreateRequest(BaseModel):
    name: str
    key: Optional[str] = None
    purpose: str = ""
    metric: Optional[str] = None
    engine: str = ENGINES.DEFAULT
    options: list[OptionBody]
    fallback: Optional[str] = None


class LoopRenameRequest(BaseModel):
    name: Optional[str] = None
    key: Optional[str] = None


class LoopMetric(BaseModel):
    id: str
    name: str


class OptionResponse(BaseModel):
    id: str
    key: str
    name: str
    config: dict[str, Any]


class CycleResponse(BaseModel):
    id: str
    number: int
    engine: str
    engine_version: str
    metric_version: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


class LoopResponse(BaseModel):
    id: str
    key: str
    name: str
    purpose: str
    metric: LoopMetric
    engine: str
    state: str
    paused_from: Optional[str] = None
    owner: str
    fallback: str
    options: list[OptionResponse]
    cycle: Optional[CycleResponse] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _not_found(loop: str) -> LoopNotFoundException:
    return LoopNotFoundException(f"no loop with the key or id {loop!r}")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=LoopResponse,
)
async def create_loop(
    body: LoopCreateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """create a draft loop with its options, metric and engine."""
    try:
        loop = await get_proxy_service().create_loop(
            tenant_id,
            name=body.name,
            key=body.key,
            purpose=body.purpose,
            metric=body.metric,
            engine=body.engine,
            options=[option.model_dump() for option in body.options],
            fallback=body.fallback,
            actor=actor,
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopKeyTakenError as e:
        raise LoopKeyTakenException(str(e))
    logger.info(f"loop created: {loop['id']} by user {actor.user_id}")
    return LoopResponse(**loop)


@router.post(
    "/{loop}/launch",
    status_code=status.HTTP_200_OK,
    response_model=LoopResponse,
)
async def launch_loop(
    loop: str,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """launch a draft: its first cycle starts and it goes live."""
    try:
        launched = await get_proxy_service().launch_loop(tenant_id, loop, actor=actor)
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopStateError as e:
        raise LoopNotDraftException(str(e))
    if launched is None:
        raise _not_found(loop)
    logger.info(f"loop launched: {launched['id']} by user {actor.user_id}")
    return LoopResponse(**launched)


@router.patch(
    "/{loop}",
    status_code=status.HTTP_200_OK,
    response_model=LoopResponse,
)
async def rename_loop(
    loop: str,
    body: LoopRenameRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    actor: Actor = Depends(get_actor),
    _scoped=Depends(require_scopes(["loop:write"])),
):
    """rename a loop at any time; change its key only while it is a draft."""
    try:
        renamed = await get_proxy_service().rename_loop(
            tenant_id, loop, name=body.name, key=body.key, actor=actor
        )
    except LoopInvalidError as e:
        raise InvalidLoopException(str(e))
    except LoopKeyTakenError as e:
        raise LoopKeyTakenException(str(e))
    except LoopStateError as e:
        raise LoopNotDraftException(str(e))
    if renamed is None:
        raise _not_found(loop)
    return LoopResponse(**renamed)
