import grpc

from qbrixlog import get_logger
from qbrixproto import common_pb2, motor_pb2_grpc
from qbrixproto import motor_pb2
from qbrixruntime.grpc import HEALTH_SERVICE_NAME
from qbrixruntime.grpc import add_health
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.grpc import enable_reflection
from qbrixruntime.grpc import serve_until_shutdown
from qbrixruntime.shutdown import shutdown_signal

from motorsvc.config import MotorSettings
from motorsvc.service import MotorService

logger = get_logger(__name__)


class MotorGRPCServicer(motor_pb2_grpc.MotorServiceServicer):
    def __init__(self, service: MotorService):
        self._service = service

    async def Select(self, request, context):
        try:
            result = await self._service.select(
                tenant_id=request.tenant_id,
                experiment_id=request.experiment_id,
                context_id=request.context.id,
                context_vector=list(request.context.vector),
                context_metadata=dict(request.context.metadata),
            )
            return motor_pb2.SelectResponse(
                arm=common_pb2.Arm(
                    id=result["arm"]["id"],
                    name=result["arm"]["name"],
                    index=result["arm"]["index"],
                ),
                learner_experiment_id=result.get("learner_experiment_id", ""),
                learner_index=result.get("learner_index", 0),
                policy=result.get("policy", ""),
            )
        except ValueError as e:
            logger.warning("experiment not found: %s", request.experiment_id)
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(e))
            return motor_pb2.SelectResponse()
        except Exception as e:
            logger.error(
                "selection failed for experiment %s: %s", request.experiment_id, e
            )
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return motor_pb2.SelectResponse()

    async def Health(self, request, context):
        healthy = await self._service.health()
        return common_pb2.HealthCheckResponse(
            status=(
                common_pb2.HealthCheckResponse.SERVING
                if healthy
                else common_pb2.HealthCheckResponse.NOT_SERVING
            )
        )


async def serve(settings: MotorSettings | None = None) -> None:
    if settings is None:
        settings = MotorSettings()

    async with shutdown_signal() as shutdown:
        service = MotorService(settings)
        await service.start()

        server = build_server(settings)
        motor_pb2_grpc.add_MotorServiceServicer_to_server(
            MotorGRPCServicer(service), server
        )
        health = await add_health(server, "motor")
        enable_reflection(
            server,
            motor_pb2.DESCRIPTOR.services_by_name["MotorService"].full_name,
            HEALTH_SERVICE_NAME,
        )

        logger.info("starting motor grpc server on %s", bind(server, settings))
        await server.start()

        try:
            await serve_until_shutdown(
                server, shutdown, grace=settings.shutdown_grace_sec, health=health
            )
        finally:
            logger.info("shutting down motor grpc server")
            await service.stop()
