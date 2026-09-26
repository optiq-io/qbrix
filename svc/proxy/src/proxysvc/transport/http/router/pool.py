import logging
from typing import List
from typing import Optional
from typing import Any

from fastapi import APIRouter
from fastapi import status
from fastapi import Depends
from pydantic import BaseModel

from proxysvc.transport.http.auth.dependencies import get_current_user_id
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import PoolNotFoundException
from proxysvc.transport.http.exception import PoolHasExperimentsException
from proxysvc.transport.http.exception import PoolCreationException
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.service import ProxyService
from proxysvc.core.error import PoolHasExperimentsError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pools", tags=["pools"])

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


class ArmRequest(BaseModel):
    name: str
    metadata: dict = {}


class PoolCreateRequest(BaseModel):
    name: str
    arms: List[ArmRequest]


class PoolUpdateRequest(BaseModel):
    name: Optional[str] = None


class ArmResponse(BaseModel):
    id: str
    name: str
    index: int
    is_active: bool = True
    metadata: dict = {}


class PoolResponse(BaseModel):
    id: str
    name: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    arms: List[ArmResponse] = []


class PoolListResponse(BaseModel):
    pools: List[PoolResponse]
    limit: int
    offset: int


class ExperimentLinkedResponse(BaseModel):
    id: str
    name: str
    pool_id: str
    policy: str
    policy_params: dict
    enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pool: Optional[dict[str, Any]] = None
    feature_gate: Optional[dict[str, Any]] = None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PoolResponse,
)
async def create_pool(
    body: PoolCreateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["pool:write"])),
):
    """create a new pool with arms."""
    try:
        service = get_proxy_service()
        arms_data = [{"name": arm.name, "metadata": arm.metadata} for arm in body.arms]
        pool = await service.create_pool(
            tenant_id, body.name, arms_data, actor_id=user_id
        )

        logger.info(f"pool created: {pool['id']} by user {user_id}")
        return _to_response(pool)
    except PoolCreationException:
        raise
    except Exception as e:
        logger.error(f"pool creation error: {str(e)}")
        raise PoolCreationException()


@router.get(
    "/{pool_id}",
    status_code=status.HTTP_200_OK,
    response_model=PoolResponse,
)
async def get_pool(
    pool_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["pool:read"])),
):
    """get pool by id."""
    service = get_proxy_service()
    pool = await service.get_pool(tenant_id, pool_id)

    if pool is None:
        raise PoolNotFoundException(f"pool not found: {pool_id}")

    return _to_response(pool)


@router.patch(
    "/{pool_id}",
    status_code=status.HTTP_200_OK,
    response_model=PoolResponse,
)
async def update_pool(
    pool_id: str,
    body: PoolUpdateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["pool:write"])),
):
    """update pool by id."""
    try:
        service = get_proxy_service()

        kwargs = {}
        if body.name is not None:
            kwargs["name"] = body.name

        pool = await service.update_pool(tenant_id, pool_id, actor_id=user_id, **kwargs)

        if pool is None:
            raise PoolNotFoundException(f"pool not found: {pool_id}")

        logger.info(f"pool updated: {pool_id} by user {user_id}")
        return _to_response(pool)
    except PoolNotFoundException:
        raise
    except Exception as e:
        logger.error(f"pool update error: {str(e)}")
        raise InternalServerException("pool update failed")


@router.delete(
    "/{pool_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_pool(
    pool_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["pool:delete"])),
):
    """delete pool by id."""
    service = get_proxy_service()

    try:
        deleted = await service.delete_pool(tenant_id, pool_id, actor_id=user_id)
    except PoolHasExperimentsError as e:
        raise PoolHasExperimentsException(str(e))

    if not deleted:
        raise PoolNotFoundException(f"pool not found: {pool_id}")

    logger.info(f"pool deleted: {pool_id} by user {user_id}")
    return {"message": "pool deleted successfully"}


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=PoolListResponse,
)
async def list_pools(
    limit: int = 100,
    offset: int = 0,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["pool:read"])),
):
    """list all pools with pagination."""
    service = get_proxy_service()
    pools = await service.list_pools(tenant_id, limit=limit, offset=offset)

    return PoolListResponse(
        pools=[_to_response(pool) for pool in pools],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{pool_id}/experiments",
    status_code=status.HTTP_200_OK,
    response_model=list[ExperimentLinkedResponse],
)
async def list_pool_experiments(
    pool_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["pool:read"])),
):
    """list experiments linked to a pool."""
    service = get_proxy_service()

    pool = await service.get_pool(tenant_id, pool_id)
    if pool is None:
        raise PoolNotFoundException(f"pool not found: {pool_id}")

    experiments = await service.list_pool_experiments(tenant_id, pool_id)
    return [
        ExperimentLinkedResponse(
            id=exp["id"],
            name=exp["name"],
            pool_id=exp["pool_id"],
            policy=exp["policy"],
            policy_params=exp.get("policy_params", {}),
            enabled=exp.get("enabled", True),
            created_at=exp.get("created_at"),
            updated_at=exp.get("updated_at"),
            pool=exp.get("pool"),
            feature_gate=exp.get("feature_gate"),
        )
        for exp in experiments
    ]


def _to_response(pool: dict) -> PoolResponse:
    return PoolResponse(
        id=pool["id"],
        name=pool["name"],
        created_at=pool.get("created_at"),
        updated_at=pool.get("updated_at"),
        arms=[
            ArmResponse(
                id=arm["id"],
                name=arm["name"],
                index=arm["index"],
                is_active=arm.get("is_active", True),
                metadata=arm.get("metadata", {}),
            )
            for arm in pool.get("arms", [])
        ],
    )
