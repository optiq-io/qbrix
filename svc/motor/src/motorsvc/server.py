import asyncio
from concurrent import futures

import grpc

from motorsvc.config import MotorSettings
from motorsvc.service import MotorService


class MotorGRPCServicer:
    def __init__(self, service: MotorService):
        self._service = service

    async def Select(self, request, context):
        try:
            result = await self._service.select(
                experiment_id=request.experiment_id,
                context_id=request.context.id,
                context_vector=list(request.context.vector),
                context_metadata=dict(request.context.metadata)
            )
            # TODO: Return proper proto response once generated
            return result
        except ValueError as e:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(e))
            return None
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return None

    async def Health(self, request, context):
        healthy = await self._service.health()
        # TODO: Return proper proto response once generated
        return {"status": 1 if healthy else 2}


async def serve(settings: MotorSettings | None = None) -> None:
    if settings is None:
        settings = MotorSettings()

    service = MotorService(settings)
    await service.start()

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    # TODO: Add servicer once proto stubs are generated
    # motor_pb2_grpc.add_MotorServiceServicer_to_server(MotorGRPCServicer(service), server)

    listen_addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    print(f"Starting Motor gRPC server on {listen_addr}")
    await server.start()

    try:
        await server.wait_for_termination()
    finally:
        await service.stop()
        await server.stop(grace=5)
