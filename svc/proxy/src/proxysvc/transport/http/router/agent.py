import logging
from typing import Optional, List, Union

from fastapi import APIRouter
from fastapi import status
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field

from proxysvc.transport.http.auth.dependencies import get_current_user_id
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import SelectionException
from proxysvc.transport.http.exception import FeedbackException
from proxysvc.transport.http.exception import InvalidContextPropertiesException
from proxysvc.transport.http.exception import InvalidContextVectorException
from proxysvc.transport.http.exception import UsageLimitException
from proxysvc.core.error import ContextPropertiesError
from proxysvc.core.error import ContextVectorError
from proxysvc.core.error import UsageLimitError
from proxysvc.service import ProxyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# module-level proxy service instance, set via set_proxy_service()
_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    """set the proxy service instance for this router."""
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    """get the proxy service instance."""
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


class ContextModel(BaseModel):
    id: str = Field(
        ...,
        description="Stable identifier for the request source, e.g. a user or "
        "session id. Drives deterministic feature-gate rollout.",
    )
    properties: Optional[dict] = Field(
        default=None,
        description='Named request properties, e.g. {"device": "mobile", '
        '"price": 20}. Encoded server-side against the experiment\'s declared '
        "context schema. This is the way to give a contextual strategy features.",
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="Free-form key-value pairs for feature-gate targeting. "
        "Never read by the strategy itself.",
    )
    vector: Optional[List[Union[int, float]]] = Field(
        default=None,
        description="Pre-encoded feature vector. Escape hatch for callers who "
        "already hold their own embeddings; its width must equal the "
        "experiment's dim. Prefer `properties` and let qbrix own the encoding.",
    )


class AgentSelectRequest(BaseModel):
    experiment_id: str
    context: ContextModel


class AgentFeedbackRequest(BaseModel):
    request_id: str
    reward: Union[int, float]


class ArmModel(BaseModel):
    id: str
    name: str
    index: int


class AgentSelectResponse(BaseModel):
    arm: ArmModel
    request_id: Optional[str] = None  # null for a paused experiment (no token minted)
    is_default: bool


class AgentFeedbackResponse(BaseModel):
    accepted: bool


@router.post(
    "/select",
    status_code=status.HTTP_200_OK,
    response_model=AgentSelectResponse,
)
async def agent_select(
    body: AgentSelectRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["agent:read"])),
):
    try:
        svc = get_proxy_service()
        response = await svc.select(
            tenant_id=tenant_id,
            experiment_id=body.experiment_id,
            context_id=body.context.id,
            context_vector=body.context.vector,
            context_metadata=body.context.metadata,
            context_properties=body.context.properties,
        )

        logger.info(f"agent selected for experiment: {body.experiment_id}")

        return response
    except SelectionException:
        raise
    except ContextVectorError as e:
        raise InvalidContextVectorException(str(e))
    except ContextPropertiesError as e:
        raise InvalidContextPropertiesException(str(e))
    except UsageLimitError as e:
        raise UsageLimitException(str(e))
    except Exception as e:
        logger.error(f"agent select: {str(e)}")
        raise SelectionException()


@router.post(
    "/feedback",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentFeedbackResponse,
)
async def agent_feedback(
    body: AgentFeedbackRequest,
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["agent:write"])),
):
    try:
        svc = get_proxy_service()
        accepted = await svc.feed(
            request_id=body.request_id,
            reward=body.reward,
        )
        logger.info(f"agent feedback received for request: {body.request_id}")
        return {"accepted": accepted}
    except FeedbackException:
        raise
    except Exception as e:
        logger.error(f"agent feed: {str(e)}")
        raise FeedbackException()
