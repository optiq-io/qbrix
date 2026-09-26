from qbrixlog import get_logger
from qbrixproto import common_pb2
from qbrixruntime.grpc import HEALTH_SERVICE_NAME
from qbrixruntime.grpc import add_health
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.grpc import enable_reflection
from qbrixruntime.grpc import serve_until_shutdown
from qbrixruntime.shutdown import shutdown_signal

from tracesvc.config import TraceSettings
from tracesvc.service import TraceService

logger = get_logger(__name__)


class TraceGRPCServicer:
    """grpc servicer for trace service health and stats."""

    def __init__(self, service: TraceService):
        self._service = service

    async def Health(self, request, context):  # noqa
        healthy = await self._service.health()
        return common_pb2.HealthCheckResponse(
            status=(
                common_pb2.HealthCheckResponse.SERVING
                if healthy
                else common_pb2.HealthCheckResponse.NOT_SERVING
            )
        )


async def serve(settings: TraceSettings | None = None) -> None:

    if settings is None:
        settings = TraceSettings()

    async with shutdown_signal() as shutdown:
        service = TraceService(settings)
        await service.start()

        server = build_server(settings)
        health = await add_health(server, "trace")
        enable_reflection(server, HEALTH_SERVICE_NAME)

        logger.info("starting trace grpc server on %s", bind(server, settings))
        await server.start()

        try:
            await serve_until_shutdown(
                server, shutdown, grace=settings.shutdown_grace_sec, health=health
            )
        finally:
            logger.info("shutting down trace grpc server")
            await service.stop()
