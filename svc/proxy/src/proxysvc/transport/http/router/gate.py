from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi import status
from fastapi import Depends

from proxysvc.transport.http.auth.dependencies import get_current_user_id
from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import GateAlreadyExistsException
from proxysvc.transport.http.exception import GateNotFoundException
from proxysvc.transport.http.exception import ExperimentNotFoundException
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.core.error import GateExistsError
from proxysvc.service import ProxyService
from proxysvc.mod.gate.schema import GateConfigPatchRequest
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.mod.gate.schema import GateEvaluateRequest
from proxysvc.mod.gate.response import GateConfigResponse
from proxysvc.mod.gate.response import GateEvaluateResponse
from proxysvc.mod.gate.response import to_response
from proxysvc.mod.gate.response import to_evaluation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gates", tags=["gates"])

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


@router.post(
    "/{experiment_id}",
    status_code=status.HTTP_201_CREATED,
    response_model=GateConfigResponse,
)
async def create_gate_config(
    experiment_id: str,
    body: GateConfigRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["gate:write"])),
):
    """create feature gate config for an experiment."""
    try:
        service = get_proxy_service()
        result = await service.create_gate_config(
            tenant_id, experiment_id, body, actor_id=user_id
        )

        if result is None:
            raise ExperimentNotFoundException(f"experiment not found: {experiment_id}")

        logger.info(
            f"gate config created for experiment: {experiment_id} by user {user_id}"
        )
        return to_response(result)
    except ExperimentNotFoundException:
        raise
    except GateExistsError as e:
        raise GateAlreadyExistsException(str(e))
    except Exception as e:
        logger.error(f"gate config creation error: {str(e)}")
        raise InternalServerException("gate config creation failed")


@router.get(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
    response_model=GateConfigResponse,
)
async def get_gate_config(
    experiment_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["gate:read"])),
):
    """get feature gate config for an experiment."""
    service = get_proxy_service()
    result = await service.get_gate_config(tenant_id, experiment_id)

    if result is None:
        raise GateNotFoundException(
            f"gate config not found for experiment: {experiment_id}"
        )

    return to_response(result)


@router.put(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
    response_model=GateConfigResponse,
)
async def update_gate_config(
    experiment_id: str,
    body: GateConfigRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["gate:write"])),
):
    """update feature gate config for an experiment."""
    try:
        service = get_proxy_service()
        result = await service.update_gate_config(
            tenant_id, experiment_id, body, actor_id=user_id
        )

        if result is None:
            raise GateNotFoundException(
                f"gate config not found for experiment: {experiment_id}"
            )

        logger.info(
            f"gate config updated for experiment: {experiment_id} by user {user_id}"
        )
        return to_response(result)
    except GateNotFoundException:
        raise
    except Exception as e:
        logger.error(f"gate config update error: {str(e)}")
        raise InternalServerException("gate config update failed")


@router.patch(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
    response_model=GateConfigResponse,
)
async def patch_gate_config(
    experiment_id: str,
    body: GateConfigPatchRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["gate:write"])),
):
    """partially update feature gate config for an experiment.

    a field absent from the body is left as stored — unlike PUT, which replaces
    the whole config.
    """
    try:
        service = get_proxy_service()
        result = await service.patch_gate_config(
            tenant_id, experiment_id, body, actor_id=user_id
        )

        if result is None:
            raise GateNotFoundException(
                f"gate config not found for experiment: {experiment_id}"
            )

        logger.info(
            f"gate config patched for experiment: {experiment_id} by user {user_id}"
        )
        return to_response(result)
    except GateNotFoundException:
        raise
    except Exception as e:
        logger.error(f"gate config patch error: {str(e)}")
        raise InternalServerException("gate config patch failed")


@router.delete(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_gate_config(
    experiment_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["gate:write"])),
):
    """delete feature gate config for an experiment."""
    service = get_proxy_service()
    deleted = await service.delete_gate_config(
        tenant_id, experiment_id, actor_id=user_id
    )

    if not deleted:
        raise GateNotFoundException(
            f"gate config not found for experiment: {experiment_id}"
        )

    logger.info(
        f"gate config deleted for experiment: {experiment_id} by user {user_id}"
    )
    return {"message": "gate config deleted successfully"}


@router.post(
    "/{experiment_id}/evaluate",
    status_code=status.HTTP_200_OK,
    response_model=GateEvaluateResponse,
)
async def evaluate_gate_config(
    experiment_id: str,
    body: GateEvaluateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),  # noqa
    _user=Depends(require_scopes(["gate:read"])),
):
    """dry-run the gate against a sample context.

    read-only: nothing is persisted and no selection is recorded. runs the same
    `FeatureGate.decide` the select path uses, so the preview cannot drift from
    live behaviour.
    """
    service = get_proxy_service()
    result = await service.evaluate_gate_config(
        tenant_id, experiment_id, body.context_id, body.context_metadata
    )

    if result is None:
        raise GateNotFoundException(
            f"gate config not found for experiment: {experiment_id}"
        )

    config, decision = result
    return to_evaluation(config, decision)
