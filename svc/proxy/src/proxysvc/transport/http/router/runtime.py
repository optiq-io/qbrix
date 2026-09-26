import logging
from typing import Optional

from fastapi import APIRouter
from fastapi import status
from fastapi import Depends
from pydantic import BaseModel

from proxysvc.transport.http.auth.dependencies import get_current_user_id
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.service import ProxyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime", tags=["runtime"])


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


class StreamLengthResponse(BaseModel):
    len: int


class StreamHealthResponse(BaseModel):
    healthy: bool


class ServiceHealthResponse(BaseModel):
    service: str
    status: str


@router.get(
    "/redis/stream/size",
    status_code=status.HTTP_200_OK,
    response_model=StreamLengthResponse,
)
async def get_cortex_stream_length(
    tenant_id: str = Depends(get_current_tenant_id),  # noqa
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["runtime:read"])),
):
    svc = get_proxy_service()
    size = await svc.get_cortex_stream_len()
    return StreamLengthResponse(len=size)


@router.get(
    "/redis/health",
    status_code=status.HTTP_200_OK,
    response_model=ServiceHealthResponse,
)
async def get_redis_health(
    tenant_id: str = Depends(get_current_tenant_id),  # noqa
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["runtime:read"])),
) -> ServiceHealthResponse:
    """redis health check endpoint."""
    svc = get_proxy_service()
    healthy = await svc.health()
    return ServiceHealthResponse(
        service="redis",
        status="healthy" if healthy else "unhealthy",
    )


@router.get(
    "/motor/health",
    status_code=status.HTTP_200_OK,
    response_model=ServiceHealthResponse,
)
async def get_motor_health(
    tenant_id: str = Depends(get_current_tenant_id),  # noqa
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["runtime:read"])),
) -> ServiceHealthResponse:
    """motorsvc health check via grpc."""
    svc = get_proxy_service()
    healthy = await svc.motor_health()
    return ServiceHealthResponse(
        service="motorsvc",
        status="healthy" if healthy else "unhealthy",
    )


@router.get(
    "/cortex/health",
    status_code=status.HTTP_200_OK,
    response_model=ServiceHealthResponse,
)
async def get_cortex_health(
    tenant_id: str = Depends(get_current_tenant_id),  # noqa
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["runtime:read"])),
) -> ServiceHealthResponse:
    """cortexsvc health check via grpc."""
    svc = get_proxy_service()
    healthy = await svc.cortex_health()
    return ServiceHealthResponse(
        service="cortexsvc",
        status="healthy" if healthy else "unhealthy",
    )
