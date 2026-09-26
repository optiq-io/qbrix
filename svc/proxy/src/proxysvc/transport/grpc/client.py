import logging

from typing import List, Union, Any, Sequence, Tuple
import grpc

from qbrixproto import cortex_pb2
from qbrixproto import cortex_pb2_grpc
from qbrixproto import common_pb2
from qbrixproto import motor_pb2
from qbrixproto import motor_pb2_grpc
from proxysvc.config import MotorClientSettings, CortexClientSettings

logger = logging.getLogger(__name__)


def _build_grpc_options(
    settings: MotorClientSettings | CortexClientSettings,
) -> Sequence[Tuple[str, Any]]:
    """build grpc channel options from client settings."""
    return [
        ("grpc.keepalive_time_ms", settings.grpc_keepalive_time_ms),
        ("grpc.keepalive_timeout_ms", settings.grpc_keepalive_timeout_ms),
        (
            "grpc.http2.max_pings_without_data",
            settings.grpc_http2_max_pings_without_data,
        ),
        (
            "grpc.keepalive_permit_without_calls",
            int(settings.grpc_keepalive_permit_without_calls),
        ),
    ]


class CortexClient:
    def __init__(self, address: str, settings: CortexClientSettings | None = None):
        self._address = address
        self._settings = settings or CortexClientSettings()
        self._channel: grpc.aio.Channel | None = None
        self._stub: cortex_pb2_grpc.CortexServiceStub | None = None

    async def connect(self) -> None:
        logger.debug("cortex client connecting.")
        options = _build_grpc_options(self._settings)
        self._channel = grpc.aio.insecure_channel(self._address, options=options)
        self._stub = cortex_pb2_grpc.CortexServiceStub(self._channel)
        logger.debug("cortex client connected.")

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()

    async def health(self) -> bool:
        if self._stub is None:
            raise RuntimeError("CortexClient not connected. Call connect() first.")

        request = common_pb2.HealthCheckRequest()
        response = await self._stub.Health(request)
        return response.status == common_pb2.HealthCheckResponse.SERVING

    async def flush_batch(self, experiment_id: str) -> int:
        """drain pending feedback for an experiment, returning events processed."""
        if self._stub is None:
            raise RuntimeError("CortexClient not connected. Call connect() first.")

        request = cortex_pb2.FlushBatchRequest(experiment_id=experiment_id)
        response = await self._stub.FlushBatch(request)
        return response.events_processed


class MotorClient:
    def __init__(self, address: str, settings: MotorClientSettings | None = None):
        self._address = address
        self._settings = settings or MotorClientSettings()
        self._channel: grpc.aio.Channel | None = None
        self._stub: motor_pb2_grpc.MotorServiceStub | None = None

    async def connect(self) -> None:
        logger.debug("motor client connecting.")
        options = _build_grpc_options(self._settings)
        self._channel = grpc.aio.insecure_channel(self._address, options=options)
        self._stub = motor_pb2_grpc.MotorServiceStub(self._channel)
        logger.debug("motor client connected.")

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()

    async def select(
        self,
        tenant_id: str,
        experiment_id: str,
        context_id: str,
        context_vector: List[Union[int, float]],
        context_metadata: dict,
    ) -> dict:
        if self._stub is None:
            raise RuntimeError("MotorClient not connected. Call connect() first.")

        request = motor_pb2.SelectRequest(
            tenant_id=tenant_id,
            experiment_id=experiment_id,
            context=common_pb2.Context(
                id=context_id,
                vector=context_vector or [],
                metadata=(
                    {k: str(v) for k, v in context_metadata.items()}
                    if context_metadata
                    else {}
                ),
            ),
        )
        response = await self._stub.Select(request)
        result = {
            "arm": {
                "id": response.arm.id,
                "name": response.arm.name,
                "index": response.arm.index,
            },
            "policy": response.policy,
        }
        if response.learner_experiment_id:
            result["learner_experiment_id"] = response.learner_experiment_id
            result["learner_index"] = response.learner_index
        return result

    async def health(self) -> bool:
        if self._stub is None:
            raise RuntimeError("MotorClient not connected. Call connect() first.")

        request = common_pb2.HealthCheckRequest()
        response = await self._stub.Health(request)
        return response.status == common_pb2.HealthCheckResponse.SERVING
