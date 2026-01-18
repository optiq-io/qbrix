from concurrent import futures

import grpc

from qbrixproto import common_pb2, proxy_pb2, proxy_pb2_grpc

from proxysvc.config import ProxySettings
from proxysvc.service import ProxyService


class ProxyGRPCServicer(proxy_pb2_grpc.ProxyServiceServicer):
    def __init__(self, service: ProxyService):
        self._service = service

    async def CreatePool(self, request, context):
        try:
            arms = [{"name": arm.name, "metadata": dict(arm.metadata) if hasattr(arm, 'metadata') else {}} for arm in request.arms]
            response = await self._service.create_pool(request.name, arms)
            return proxy_pb2.CreatePoolResponse(
                pool=self._dict_to_pool(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return proxy_pb2.CreatePoolResponse()

    async def GetPool(self, request, context):
        response = await self._service.get_pool(request.pool_id)
        if response is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Pool not found: {request.pool_id}")
            return proxy_pb2.GetPoolResponse()
        return proxy_pb2.GetPoolResponse(
            pool=self._dict_to_pool(response)
        )

    async def DeletePool(self, request, context):
        deleted = await self._service.delete_pool(request.pool_id)
        if not deleted:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Pool not found: {request.pool_id}")
        return proxy_pb2.DeletePoolResponse(deleted=deleted)

    async def CreateExperiment(self, request, context):
        try:
            feature_gate = None
            if request.HasField("feature_gate"):
                feature_gate = {
                    "rollout_percentage": request.feature_gate.rollout_percentage,
                    "default_arm_id": request.feature_gate.default_arm_id or None,
                    "rules": []
                }
            response = await self._service.create_experiment(
                name=request.name,
                pool_id=request.pool_id,
                protocol=request.protocol,
                protocol_params=dict(request.protocol_params),
                enabled=request.enabled,
                feature_gate_config=feature_gate
            )
            return proxy_pb2.CreateExperimentResponse(
                experiment=self._dict_to_experiment(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return proxy_pb2.CreateExperimentResponse()

    async def GetExperiment(self, request, context):
        response = await self._service.get_experiment(request.experiment_id)
        if response is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Experiment not found: {request.experiment_id}")
            return proxy_pb2.GetExperimentResponse()
        return proxy_pb2.GetExperimentResponse(
            experiment=self._dict_to_experiment(response)
        )

    async def UpdateExperiment(self, request, context):
        try:
            kwargs = {}
            if request.HasField("enabled"):
                kwargs["enabled"] = request.enabled
            if request.protocol_params:
                kwargs["protocol_params"] = dict(request.protocol_params)
            if request.HasField("feature_gate"):
                kwargs["feature_gate_config"] = {
                    "rollout_percentage": request.feature_gate.rollout_percentage,
                    "default_arm_id": request.feature_gate.default_arm_id or None,
                    "rules": []
                }
            response = await self._service.update_experiment(request.experiment_id, **kwargs)
            if response is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Experiment not found: {request.experiment_id}")
                return proxy_pb2.UpdateExperimentResponse()
            return proxy_pb2.UpdateExperimentResponse(
                experiment=self._dict_to_experiment(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return proxy_pb2.UpdateExperimentResponse()

    async def DeleteExperiment(self, request, context):
        deleted = await self._service.delete_experiment(request.experiment_id)
        if not deleted:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Experiment not found: {request.experiment_id}")
        return proxy_pb2.DeleteExperimentResponse(deleted=deleted)

    async def Select(self, request, context):
        try:
            response = await self._service.select(
                experiment_id=request.experiment_id,
                context_id=request.context.id,
                context_vector=list(request.context.vector),
                context_metadata=dict(request.context.metadata)
            )
            return proxy_pb2.SelectResponse(
                arm=common_pb2.Arm(
                    id=response["arm"]["id"],
                    name=response["arm"]["name"],
                    index=response["arm"]["index"]
                ),
                request_id=response["request_id"],
                is_default=response.get("is_default", False)
            )
        except ValueError as e:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(e))
            return proxy_pb2.SelectResponse()
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return proxy_pb2.SelectResponse()

    async def Feedback(self, request, context):
        try:
            accepted = await self._service.feed(
                experiment_id=request.experiment_id,
                request_id=request.request_id,
                arm_index=request.arm_index,
                reward=request.reward,
                context_id=request.context.id,
                context_vector=list(request.context.vector),
                context_metadata=dict(request.context.metadata)
            )
            return proxy_pb2.FeedbackResponse(accepted=accepted)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return proxy_pb2.FeedbackResponse(accepted=False)

    async def Health(self, request, context):
        healthy = await self._service.health()
        return common_pb2.HealthCheckResponse(
            status=common_pb2.HealthCheckResponse.SERVING if healthy
            else common_pb2.HealthCheckResponse.NOT_SERVING
        )

    @staticmethod
    def _dict_to_pool(d: dict) -> common_pb2.Pool:
        return common_pb2.Pool(
            id=d["id"],
            name=d["name"],
            arms=[
                common_pb2.Arm(id=arm["id"], name=arm["name"], index=arm["index"])
                for arm in d.get("arms", [])
            ]
        )

    @staticmethod
    def _dict_to_experiment(d: dict) -> common_pb2.Experiment:
        return common_pb2.Experiment(
            id=d["id"],
            name=d["name"],
            pool_id=d["pool_id"],
            protocol=d["protocol"],
            protocol_params={k: str(v) for k, v in d.get("protocol_params", {}).items()},
            enabled=d.get("enabled", False)
        )


async def serve(settings: ProxySettings | None = None) -> None:
    if settings is None:
        settings = ProxySettings()

    service = ProxyService(settings)
    await service.start()

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    proxy_pb2_grpc.add_ProxyServiceServicer_to_server(ProxyGRPCServicer(service), server)

    listen_addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    print(f"Starting Proxy gRPC server on {listen_addr}")
    await server.start()

    try:
        await server.wait_for_termination()
    finally:
        await service.stop()
        await server.stop(grace=5)
