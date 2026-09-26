from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi import status
from fastapi import Depends
from pydantic import BaseModel

from proxysvc.transport.http.auth.dependencies import get_current_user
from proxysvc.transport.http.auth.dependencies import get_current_user_id
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import ExperimentNotFoundException
from proxysvc.transport.http.exception import ExperimentCreationException
from proxysvc.transport.http.exception import ExperimentLimitException
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.transport.http.exception import ContextDimImmutableException
from proxysvc.transport.http.exception import ContextSchemaImmutableException
from proxysvc.transport.http.exception import InvalidPolicyParamsException
from proxysvc.transport.http.exception import LearnerExperimentDeleteException
from proxysvc.transport.http.exception import ExperimentRunningException
from proxysvc.core.error import BadPolicyParamsError
from proxysvc.core.error import ExperimentLimitError
from proxysvc.core.error import LearnerExperimentDeleteError
from proxysvc.core.error import ContextDimImmutableError
from proxysvc.core.error import ContextSchemaImmutableError
from proxysvc.core.error import ExperimentRunningError
from proxysvc.service import ProxyService
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.mod.gate.response import GateConfigResponse
from proxysvc.mod.gate.response import to_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["experiments"])

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


class ExperimentCreateRequest(BaseModel):
    name: str
    pool_id: str
    policy: str = ""
    policy_params: dict = {}
    enabled: bool = True
    feature_gate: Optional[GateConfigRequest] = None


class ExperimentUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    policy_params: Optional[dict] = None


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
    arms: list[ArmResponse] = []


class ExperimentResponse(BaseModel):
    id: str
    name: str
    pool_id: str
    policy: str
    policy_params: dict
    enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pool: Optional[PoolResponse] = None
    feature_gate: Optional[GateConfigResponse] = None
    meta_experiment_id: Optional[str] = None


class ExperimentListResponse(BaseModel):
    experiments: list[ExperimentResponse]
    limit: int
    offset: int


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentResponse,
)
async def create_experiment(
    body: ExperimentCreateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_user),
    _scoped=Depends(require_scopes(["experiment:write"])),
):
    """create a new experiment."""
    try:
        service = get_proxy_service()

        if body.policy == "auto":
            experiment = await service.create_meta_experiment(
                tenant_id=tenant_id,
                name=body.name,
                pool_id=body.pool_id,
                policy_params=body.policy_params,
                enabled=body.enabled,
                feature_gate_config=body.feature_gate,
                actor_id=user.id,
                plan_tier=user.plan_tier,
            )
        else:
            if not body.policy:
                raise BadPolicyParamsError("policy is required")
            experiment = await service.create_experiment(
                tenant_id=tenant_id,
                name=body.name,
                pool_id=body.pool_id,
                policy=body.policy,
                policy_params=body.policy_params,
                enabled=body.enabled,
                feature_gate_config=body.feature_gate,
                actor_id=user.id,
                plan_tier=user.plan_tier,
            )

        logger.info(f"experiment created: {experiment['id']} by user {user.id}")
        return _to_response(experiment)
    except BadPolicyParamsError as e:
        raise InvalidPolicyParamsException(str(e))
    except ExperimentLimitError as e:
        raise ExperimentLimitException(str(e))
    except ExperimentCreationException:
        raise
    except Exception as e:
        logger.error(f"experiment creation error: {str(e)}")
        raise ExperimentCreationException()


@router.get(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
    response_model=ExperimentResponse,
)
async def get_experiment(
    experiment_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["experiment:read"])),
):
    """get experiment by id."""
    service = get_proxy_service()
    experiment = await service.get_experiment(tenant_id, experiment_id)

    if experiment is None:
        raise ExperimentNotFoundException(f"experiment not found: {experiment_id}")

    return _to_response(experiment)


@router.patch(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
    response_model=ExperimentResponse,
)
async def update_experiment(
    experiment_id: str,
    body: ExperimentUpdateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_user),
    _scoped=Depends(require_scopes(["experiment:write"])),
):
    """update experiment by id."""
    try:
        service = get_proxy_service()

        kwargs = {}
        if body.enabled is not None:
            kwargs["enabled"] = body.enabled
        if body.policy_params is not None:
            kwargs["policy_params"] = body.policy_params

        experiment = await service.update_experiment(
            tenant_id,
            experiment_id,
            actor_id=user.id,
            plan_tier=user.plan_tier,
            **kwargs,
        )

        if experiment is None:
            raise ExperimentNotFoundException(f"experiment not found: {experiment_id}")

        logger.info(f"experiment updated: {experiment_id} by user {user.id}")
        return _to_response(experiment)
    except BadPolicyParamsError as e:
        logger.error(str(e))
        raise InvalidPolicyParamsException(str(e))
    except ContextSchemaImmutableError as e:
        raise ContextSchemaImmutableException(str(e))
    except ContextDimImmutableError as e:
        raise ContextDimImmutableException(str(e))
    except ExperimentLimitError as e:
        logger.error(str(e))
        raise ExperimentLimitException(str(e))
    except ExperimentNotFoundException:
        raise
    except Exception as e:
        logger.error(f"uncaught experiment update error: {str(e)}")
        raise InternalServerException("experiment update failed")


@router.post(
    "/{experiment_id}/reset",
    status_code=status.HTTP_200_OK,
    response_model=ExperimentResponse,
)
async def reset_experiment(
    experiment_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_user),
    _scoped=Depends(require_scopes(["experiment:write"])),
):
    """reset an experiment's learned params back to its configured policy_params."""
    try:
        service = get_proxy_service()
        experiment = await service.reset_experiment(
            tenant_id, experiment_id, actor_id=user.id
        )
    except ExperimentRunningError as e:
        logger.error(str(e))
        raise ExperimentRunningException(str(e))

    if experiment is None:
        raise ExperimentNotFoundException(f"experiment not found: {experiment_id}")

    logger.info(f"experiment reset: {experiment_id} by user {user.id}")
    return _to_response(experiment)


@router.delete(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_experiment(
    experiment_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["experiment:delete"])),
):
    """delete experiment by id."""
    try:
        service = get_proxy_service()
        deleted = await service.delete_experiment(
            tenant_id, experiment_id, actor_id=user_id
        )
    except LearnerExperimentDeleteError as e:
        logger.error(str(e))
        raise LearnerExperimentDeleteException(str(e))
    except Exception as e:
        logger.error(str(e))
        raise InternalServerException("experiment deletion failed")

    if not deleted:
        not_found_msg = f"no experiment found with id: {experiment_id}"
        logger.error(not_found_msg)
        raise ExperimentNotFoundException(not_found_msg)

    logger.info(f"experiment deleted: {experiment_id} by user {user_id}")
    return {"message": "experiment deleted successfully"}


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ExperimentListResponse,
)
async def list_experiments(
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    enabled: Optional[bool] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["experiment:read"])),
):
    """list experiments with pagination and optional search/filter."""
    service = get_proxy_service()
    experiments = await service.list_experiments(
        tenant_id,
        limit=limit,
        offset=offset,
        search=search,
        enabled=enabled,
    )

    return ExperimentListResponse(
        experiments=[_to_response(exp) for exp in experiments],
        limit=limit,
        offset=offset,
    )


def _to_response(exp: dict) -> ExperimentResponse:
    pool_data = exp.get("pool")
    pool_resp = None
    if pool_data:
        pool_resp = PoolResponse(
            id=pool_data["id"],
            name=pool_data["name"],
            created_at=pool_data.get("created_at"),
            updated_at=pool_data.get("updated_at"),
            arms=[
                ArmResponse(
                    id=a["id"],
                    name=a["name"],
                    index=a["index"],
                    is_active=a.get("is_active", True),
                    metadata=a.get("metadata", {}),
                )
                for a in pool_data.get("arms", [])
            ],
        )

    gate_config = exp.get("feature_gate")
    gate_resp = to_response(gate_config) if gate_config else None

    return ExperimentResponse(
        id=exp["id"],
        name=exp["name"],
        pool_id=exp["pool_id"],
        policy=exp["policy"],
        policy_params=exp.get("policy_params", {}),
        enabled=exp.get("enabled", True),
        created_at=exp.get("created_at"),
        updated_at=exp.get("updated_at"),
        pool=pool_resp,
        feature_gate=gate_resp,
        meta_experiment_id=exp.get("meta_experiment_id"),
    )
