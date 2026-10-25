from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel
from pydantic import Field

from proxysvc.core.error import InvalidOutcomeError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import TokenInvalidError
from proxysvc.service import ProxyService
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.transport.http.exception import InvalidOutcomeException
from proxysvc.transport.http.exception import InvalidRequestIdException
from proxysvc.transport.http.exception import LoopNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["outcome"])

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class OutcomeRequest(BaseModel):
    request_id: str = Field(description="The request_id select answered with.")
    value: Any = Field(description="The outcome, valid for the loop's metric type.")
    id: Any = Field(
        default=None,
        description="Makes the outcome idempotent: a repeat with the same id "
        "counts once. A fresh id when absent.",
    )
    at: Optional[datetime] = Field(
        default=None,
        description="When it happened, ISO 8601 (UTC without an offset). "
        "Arrival time when absent.",
    )


class OutcomeResponse(BaseModel):
    id: str
    at: datetime


@router.post(
    "/outcome",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=OutcomeResponse,
)
async def outcome(
    body: OutcomeRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    _scoped=Depends(require_scopes(["agent:write"])),
):
    """an outcome for one decision, recorded for its loop's metric."""
    try:
        answer = await get_proxy_service().outcome(
            tenant_id, body.request_id, body.value, body.id, body.at
        )
    except TokenInvalidError:
        raise InvalidRequestIdException()
    except InvalidOutcomeError as e:
        raise InvalidOutcomeException(str(e))
    except LoopNotFoundError as e:
        raise LoopNotFoundException(str(e))
    except Exception as e:
        logger.error(f"outcome: {e}")
        raise InternalServerException()
    return OutcomeResponse(
        id=answer["id"],
        at=datetime.fromtimestamp(answer["at_ms"] / 1000, tz=timezone.utc),
    )
