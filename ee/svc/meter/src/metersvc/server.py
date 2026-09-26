from qbrixlog import get_logger
from qbrixruntime.grpc import HEALTH_SERVICE_NAME
from qbrixruntime.grpc import add_health
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.grpc import enable_reflection
from qbrixruntime.grpc import serve_until_shutdown
from qbrixruntime.shutdown import shutdown_signal

from metersvc.config import MeterSettings
from metersvc.service import MeterService

logger = get_logger(__name__)


async def serve(settings: MeterSettings | None = None) -> None:
    if settings is None:
        settings = MeterSettings()

    async with shutdown_signal() as shutdown:
        service = MeterService(settings)
        await service.start()

        server = build_server(settings)
        health = await add_health(server, "meter")
        enable_reflection(server, HEALTH_SERVICE_NAME)

        logger.info("starting meter grpc server on %s", bind(server, settings))
        await server.start()

        try:
            await serve_until_shutdown(
                server, shutdown, grace=settings.shutdown_grace_sec, health=health
            )
        finally:
            logger.info("shutting down meter grpc server")
            await service.stop()
