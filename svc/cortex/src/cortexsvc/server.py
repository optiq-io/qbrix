import grpc

from qbrixlog import get_logger
from qbrixproto import common_pb2, cortex_pb2_grpc
from qbrixproto import cortex_pb2
from qbrixruntime.grpc import HEALTH_SERVICE_NAME
from qbrixruntime.grpc import add_health
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.grpc import enable_reflection
from qbrixruntime.grpc import serve_until_shutdown
from qbrixruntime.shutdown import shutdown_signal

from cortexsvc.config import CortexSettings
from cortexsvc.service import CortexService

logger = get_logger(__name__)


class CortexGRPCServicer(cortex_pb2_grpc.CortexServiceServicer):

    def __init__(self, service: CortexService):
        self._service = service

    async def FlushBatch(self, request, context):
        try:
            count = await self._service.flush_batch(request.experiment_id or None)
            return cortex_pb2.FlushBatchResponse(events_processed=count)
        except Exception as e:
            logger.error("flush batch failed: %s", e)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return cortex_pb2.FlushBatchResponse(events_processed=0)

    async def GetStats(self, request, context):
        stats_list = self._service.get_stats(request.experiment_id or None)
        return cortex_pb2.GetStatsResponse(
            stats=[
                cortex_pb2.ExperimentStats(
                    experiment_id=s["experiment_id"],
                    total_events=s.get("total", 0),
                    pending_events=s.get("pending", 0),
                    last_train_timestamp_ms=s.get("last_train", 0),
                )
                for s in stats_list
            ]
        )

    async def Health(self, request, context):
        healthy = await self._service.health()
        return common_pb2.HealthCheckResponse(
            status=(
                common_pb2.HealthCheckResponse.SERVING
                if healthy
                else common_pb2.HealthCheckResponse.NOT_SERVING
            )
        )


async def serve(settings: CortexSettings | None = None) -> None:

    if settings is None:
        settings = CortexSettings()

    async with shutdown_signal() as shutdown:
        service = CortexService(settings)
        await service.start()

        server = build_server(settings)
        cortex_pb2_grpc.add_CortexServiceServicer_to_server(
            CortexGRPCServicer(service), server
        )
        health = await add_health(server, "cortex")
        enable_reflection(
            server,
            cortex_pb2.DESCRIPTOR.services_by_name["CortexService"].full_name,
            HEALTH_SERVICE_NAME,
        )

        logger.info("starting cortex grpc server on %s", bind(server, settings))
        await server.start()

        try:
            await serve_until_shutdown(
                server, shutdown, grace=settings.shutdown_grace_sec, health=health
            )
        finally:
            logger.info("shutting down cortex grpc server")
            await service.stop()
