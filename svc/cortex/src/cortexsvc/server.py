import asyncio
from concurrent import futures

import grpc

from cortexsvc.config import CortexSettings
from cortexsvc.service import CortexService


class CortexGRPCServicer:
    def __init__(self, service: CortexService):
        self._service = service

    async def FlushBatch(self, request, context):
        try:
            count = await self._service.flush_batch(request.experiment_id or None)
            return {"events_processed": count}
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return None

    async def GetStats(self, request, context):
        stats = self._service.get_stats(request.experiment_id or None)
        return {"stats": stats}

    async def Health(self, request, context):
        healthy = await self._service.health()
        return {"status": 1 if healthy else 2}


async def serve(settings: CortexSettings | None = None) -> None:
    if settings is None:
        settings = CortexSettings()

    service = CortexService(settings)
    await service.start()

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    # TODO: Add servicer once proto stubs are generated
    # cortex_pb2_grpc.add_CortexServiceServicer_to_server(CortexGRPCServicer(service), server)

    listen_addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    print(f"Starting Cortex gRPC server on {listen_addr}")
    await server.start()

    consumer_task = asyncio.create_task(service.run_consumer())

    try:
        await server.wait_for_termination()
    finally:
        consumer_task.cancel()
        await service.stop()
        await server.stop(grace=5)
