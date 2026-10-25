from __future__ import annotations

import logging
from typing import Any
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel
from pydantic import Field

from proxysvc.core.error import DecisionContextError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import UsageLimitError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import InvalidDecisionContextException
from proxysvc.transport.http.exception import LoopNotFoundException
from proxysvc.transport.http.exception import SelectionException
from proxysvc.transport.http.exception import UsageLimitException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["select"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class SelectContext(BaseModel):
    unit: Any = Field(
        default=None,
        description="Who or what sees the decision: a user, a session, an account. "
        "Stable for as long as its outcome can arrive.",
    )
    properties: Any = Field(
        default=None,
        description='What the app knows about the request, e.g. {"device": "mobile"}. '
        "Recorded with the decision.",
    )


class SelectRequest(BaseModel):
    loop: str
    context: SelectContext = Field(default_factory=SelectContext)


class SelectedOption(BaseModel):
    key: str
    name: str
    config: dict[str, Any]


class SelectResponse(BaseModel):
    option: SelectedOption
    request_id: Optional[str] = None
    reason: str


@router.post(
    "/select",
    status_code=status.HTTP_200_OK,
    response_model=SelectResponse,
)
async def select(
    body: SelectRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["agent:read"])),
):
    """the loop's option for this request, and why."""
    try:
        answer = await get_proxy_service().select_loop(
            tenant_id, body.loop, body.context.unit, body.context.properties
        )
    except LoopNotFoundError as e:
        raise LoopNotFoundException(str(e))
    except DecisionContextError as e:
        raise InvalidDecisionContextException(str(e))
    except UsageLimitError as e:
        raise UsageLimitException(str(e))
    except Exception as e:
        logger.error(f"select for loop {body.loop}: {e}")
        raise SelectionException()
    return SelectResponse(**answer)
