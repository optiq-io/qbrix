import asyncio
from concurrent import futures

import grpc

from proxysvc.config import ProxySettings
from proxysvc.service import ProxyService


class ProxyGRPCServicer:
    def __init__(self, service: ProxyService):
        self._service = service

    async def CreatePool(self, request, context):
        try:
            arms = [{"name": arm.name, "metadata": dict(arm.metadata)} for arm in request.arms]
            result = await self._service.create_pool(request.name, arms)
            return {"pool": result}
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return None

    async def GetPool(self, request, context):
        result = await self._service.get_pool(request.pool_id)
        if result is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Pool not found: {request.pool_id}")
            return None
        return {"pool": result}

    async def CreateExperiment(self, request, context):
        try:
            feature_gate = None
            if request.HasField("feature_gate"):
                feature_gate = {
                    "rollout_percentage": request.feature_gate.rollout_percentage,
                    "default_arm_id": request.feature_gate.default_arm_id or None,
                    "rules": []
                }
            result = await self._service.create_experiment(
                name=request.name,
                pool_id=request.pool_id,
                protocol=request.protocol,
                protocol_params=dict(request.protocol_params),
                enabled=request.enabled,
                feature_gate_config=feature_gate
            )
            return {"experiment": result}
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return None

    async def GetExperiment(self, request, context):
        result = await self._service.get_experiment(request.experiment_id)
        if result is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Experiment not found: {request.experiment_id}")
            return None
        return {"experiment": result}

    async def Select(self, request, context):
        try:
            result = await self._service.select(
                experiment_id=request.experiment_id,
                context_id=request.context.id,
                context_vector=list(request.context.vector),
                context_metadata=dict(request.context.metadata)
            )
            return result
        except ValueError as e:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(e))
            return None
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return None

    async def Feedback(self, request, context):
        try:
            accepted = await self._service.feedback(
                experiment_id=request.experiment_id,
                request_id=request.request_id,
                arm_index=request.arm_index,
                reward=request.reward,
                context_id=request.context.id,
                context_vector=list(request.context.vector),
                context_metadata=dict(request.context.metadata)
            )
            return {"accepted": accepted}
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return None

    async def Health(self, request, context):
        healthy = await self._service.health()
        return {"status": 1 if healthy else 2}


async def serve(settings: ProxySettings | None = None) -> None:
    if settings is None:
        settings = ProxySettings()

    service = ProxyService(settings)
    await service.start()

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    # TODO: Add servicer once proto stubs are generated
    # proxy_pb2_grpc.add_ProxyServiceServicer_to_server(ProxyGRPCServicer(service), server)

    listen_addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    print(f"Starting Proxy gRPC server on {listen_addr}")
    await server.start()

    try:
        await server.wait_for_termination()
    finally:
        await service.stop()
        await server.stop(grace=5)
