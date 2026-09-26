from __future__ import annotations

from datetime import datetime
from datetime import timezone
import json

import grpc
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict

from qbrixcore.policy import POLICIES
from qbrixcore.policy import RewardType
from qbrixproto import common_pb2, proxy_pb2, proxy_pb2_grpc

from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.schema import GateConfigPatchRequest
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.mod.gate.schema import RuleRequest
from proxysvc.service import ProxyService
from proxysvc.transport.grpc.auth.context import get_grpc_auth_context
from proxysvc.transport.grpc.exception.base import ExperimentNotFoundException
from proxysvc.transport.grpc.exception.base import GateConfigNotFoundException
from proxysvc.transport.grpc.exception.base import InvalidArgumentException
from proxysvc.transport.grpc.exception.base import PoolNotFoundException
from proxysvc.transport.grpc.exception.base import UnauthenticatedException


def _unstruct(value):
    """undo Struct's one number type, so a param arrives as it would over http.

    Struct stores every number as a double, so an integer sent by the client
    reaches us as a float — and `dim: 4.0` is not an int, which is exactly what
    ExperimentState.context_dim tests for before enforcing the context width.
    json.loads gives an int for the same payload, so this restores parity with
    the http path rather than guessing.
    """
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _unstruct(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unstruct(v) for v in value]
    return value


def _request_policy_params(request) -> dict:
    """prefer the full-fidelity Struct, fall back to the string map.

    the same precedence the sdk already applies on the response side. the map
    is kept for wire compatibility: an older client sends only that, and it
    still works for the scalar params it can represent.
    """
    if request.HasField("policy_params_json"):
        return _unstruct(MessageToDict(request.policy_params_json))
    return dict(request.policy_params)


class ProxyGRPCServicer(proxy_pb2_grpc.ProxyServiceServicer):
    def __init__(self, service: ProxyService):
        self._service = service

    @staticmethod
    def _get_tenant_id() -> str:
        """extract tenant_id from grpc auth context set by interceptor."""
        auth_ctx = get_grpc_auth_context()
        if auth_ctx is None:
            raise UnauthenticatedException("authentication context not available")
        return auth_ctx.tenant_id

    async def CreatePool(self, request, context):
        tenant_id = self._get_tenant_id()
        arms = [
            {
                "name": arm.name,
                "metadata": dict(arm.metadata) if hasattr(arm, "metadata") else {},
            }
            for arm in request.arms
        ]
        response = await self._service.create_pool(tenant_id, request.name, arms)
        return proxy_pb2.CreatePoolResponse(pool=self._dict_to_pool(response))

    async def GetPool(self, request, context):
        tenant_id = self._get_tenant_id()
        response = await self._service.get_pool(tenant_id, request.pool_id)
        if response is None:
            raise PoolNotFoundException(f"pool not found: {request.pool_id}")
        return proxy_pb2.GetPoolResponse(pool=self._dict_to_pool(response))

    async def ListPools(self, request, context):
        tenant_id = self._get_tenant_id()
        limit = request.limit or 100
        offset = request.offset or 0
        pools = await self._service.list_pools(tenant_id, limit=limit, offset=offset)
        return proxy_pb2.ListPoolsResponse(
            pools=[self._dict_to_pool(p) for p in pools],
            limit=limit,
            offset=offset,
        )

    async def UpdatePool(self, request, context):
        tenant_id = self._get_tenant_id()
        kwargs = {}
        if request.HasField("name"):
            kwargs["name"] = request.name
        response = await self._service.update_pool(tenant_id, request.pool_id, **kwargs)
        if response is None:
            raise PoolNotFoundException(f"pool not found: {request.pool_id}")
        return proxy_pb2.UpdatePoolResponse(pool=self._dict_to_pool(response))

    async def DeletePool(self, request, context):
        tenant_id = self._get_tenant_id()
        deleted = await self._service.delete_pool(tenant_id, request.pool_id)
        if not deleted:
            raise PoolNotFoundException(f"pool not found: {request.pool_id}")
        return proxy_pb2.DeletePoolResponse(deleted=deleted)

    async def CreateExperiment(self, request, context):
        tenant_id = self._get_tenant_id()
        feature_gate = None
        if request.HasField("feature_gate"):
            feature_gate = self._proto_to_gate_config(request.feature_gate)
        response = await self._service.create_experiment(
            tenant_id=tenant_id,
            name=request.name,
            pool_id=request.pool_id,
            policy=request.policy,
            policy_params=_request_policy_params(request),
            enabled=request.enabled,
            feature_gate_config=feature_gate,
        )
        resp = proxy_pb2.CreateExperimentResponse(
            experiment=self._dict_to_experiment(response),
        )
        if response.get("feature_gate"):
            resp.feature_gate.CopyFrom(
                self._config_to_proto_gate(response["feature_gate"])
            )
        if response.get("pool"):
            resp.pool.CopyFrom(self._dict_to_pool(response["pool"]))
        return resp

    async def GetExperiment(self, request, context):
        tenant_id = self._get_tenant_id()
        response = await self._service.get_experiment(tenant_id, request.experiment_id)
        if response is None:
            raise ExperimentNotFoundException(
                f"experiment not found: {request.experiment_id}"
            )
        resp = proxy_pb2.GetExperimentResponse(
            experiment=self._dict_to_experiment(response),
        )
        if response.get("feature_gate"):
            resp.feature_gate.CopyFrom(
                self._config_to_proto_gate(response["feature_gate"])
            )
        if response.get("pool"):
            resp.pool.CopyFrom(self._dict_to_pool(response["pool"]))
        return resp

    async def ListExperiments(self, request, context):
        tenant_id = self._get_tenant_id()
        limit = request.limit or 100
        offset = request.offset or 0
        kwargs = {}
        if request.HasField("search"):
            kwargs["search"] = request.search
        if request.HasField("enabled"):
            kwargs["enabled"] = request.enabled
        experiments = await self._service.list_experiments(
            tenant_id, limit=limit, offset=offset, **kwargs
        )
        return proxy_pb2.ListExperimentsResponse(
            experiments=[self._dict_to_experiment(e) for e in experiments],
            limit=limit,
            offset=offset,
            items=[self._build_experiment_detail(e) for e in experiments],
        )

    async def ListPoolExperiments(self, request, context):
        tenant_id = self._get_tenant_id()
        experiments = await self._service.list_pool_experiments(
            tenant_id, request.pool_id
        )
        return proxy_pb2.ListPoolExperimentsResponse(
            experiments=[self._dict_to_experiment(e) for e in experiments],
            items=[self._build_experiment_detail(e) for e in experiments],
        )

    async def UpdateExperiment(self, request, context):
        tenant_id = self._get_tenant_id()
        kwargs = {}
        if request.HasField("enabled"):
            kwargs["enabled"] = request.enabled
        if request.HasField("policy_params_json") or request.policy_params:
            kwargs["policy_params"] = _request_policy_params(request)
        if request.HasField("feature_gate"):
            kwargs["feature_gate_config"] = self._proto_to_gate_config(
                request.feature_gate
            )
        response = await self._service.update_experiment(
            tenant_id, request.experiment_id, **kwargs
        )
        if response is None:
            raise ExperimentNotFoundException(
                f"experiment not found: {request.experiment_id}"
            )
        resp = proxy_pb2.UpdateExperimentResponse(
            experiment=self._dict_to_experiment(response),
        )
        if response.get("feature_gate"):
            resp.feature_gate.CopyFrom(
                self._config_to_proto_gate(response["feature_gate"])
            )
        if response.get("pool"):
            resp.pool.CopyFrom(self._dict_to_pool(response["pool"]))
        return resp

    async def DeleteExperiment(self, request, context):
        tenant_id = self._get_tenant_id()
        deleted = await self._service.delete_experiment(
            tenant_id, request.experiment_id
        )
        if not deleted:
            raise ExperimentNotFoundException(
                f"experiment not found: {request.experiment_id}"
            )
        return proxy_pb2.DeleteExperimentResponse(deleted=deleted)

    async def CreateGateConfig(self, request, context):
        tenant_id = self._get_tenant_id()
        config = self._proto_to_gate_config(request.config)
        response = await self._service.create_gate_config(
            tenant_id, request.experiment_id, config
        )
        if response is None:
            raise ExperimentNotFoundException(
                f"experiment not found: {request.experiment_id}"
            )
        return proxy_pb2.CreateGateConfigResponse(
            config=self._config_to_proto_gate(response)
        )

    async def GetGateConfig(self, request, context):
        tenant_id = self._get_tenant_id()
        response = await self._service.get_gate_config(tenant_id, request.experiment_id)
        if response is None:
            raise GateConfigNotFoundException(
                f"gate config not found for experiment: {request.experiment_id}"
            )
        return proxy_pb2.GetGateConfigResponse(
            config=self._config_to_proto_gate(response)
        )

    async def UpdateGateConfig(self, request, context):
        tenant_id = self._get_tenant_id()
        if request.update_mask:
            response = await self._service.patch_gate_config(
                tenant_id,
                request.experiment_id,
                self._proto_to_gate_patch(request.config, request.update_mask),
            )
        else:
            config = self._proto_to_gate_config(request.config)
            response = await self._service.update_gate_config(
                tenant_id, request.experiment_id, config
            )
        if response is None:
            raise GateConfigNotFoundException(
                f"gate config not found for experiment: {request.experiment_id}"
            )
        return proxy_pb2.UpdateGateConfigResponse(
            config=self._config_to_proto_gate(response)
        )

    async def DeleteGateConfig(self, request, context):
        tenant_id = self._get_tenant_id()
        deleted = await self._service.delete_gate_config(
            tenant_id, request.experiment_id
        )
        if not deleted:
            raise GateConfigNotFoundException(
                f"gate config not found for experiment: {request.experiment_id}"
            )
        return proxy_pb2.DeleteGateConfigResponse(deleted=deleted)

    async def Select(self, request, context):
        tenant_id = self._get_tenant_id()
        response = await self._service.select(
            tenant_id=tenant_id,
            experiment_id=request.experiment_id,
            context_id=request.context.id,
            # a repeated proto3 field has no presence, so an unset vector
            # arrives as []. treat it as absent, or a properties-only call
            # would look like both channels at once.
            context_vector=list(request.context.vector) or None,
            context_metadata=dict(request.context.metadata),
            context_properties=(
                MessageToDict(request.context.properties)
                if request.context.HasField("properties")
                else None
            ),
        )
        return proxy_pb2.SelectResponse(
            arm=common_pb2.Arm(
                id=response["arm"]["id"],
                name=response["arm"]["name"],
                index=response["arm"]["index"],
            ),
            request_id=response.get("request_id") or "",
            is_default=response.get("is_default", False),
        )

    async def Feedback(self, request, context):
        if not request.request_id:  # for paused experiments, request_id is None
            return proxy_pb2.FeedbackResponse(accepted=False)
        accepted = await self._service.feed(
            request_id=request.request_id,
            reward=request.reward,
        )
        return proxy_pb2.FeedbackResponse(accepted=accepted)

    async def ListPolicies(self, request, context):
        reward_type = None
        if request.HasField("reward_type"):
            try:
                reward_type = RewardType(request.reward_type)
            except ValueError:
                raise InvalidArgumentException(
                    f"invalid reward_type: {request.reward_type} "
                    "(expected binary | bounded | continuous)"
                )
        matching = [
            p for p in POLICIES if reward_type is None or reward_type in p.reward_types
        ]
        return proxy_pb2.ListPoliciesResponse(
            policies=[self._policy_to_proto(p) for p in matching],
        )

    @staticmethod
    def _policy_to_proto(policy_cls) -> proxy_pb2.Policy:
        doc = policy_cls.__doc__ or ""
        description = doc.strip().splitlines()[0].strip() if doc.strip() else ""
        return proxy_pb2.Policy(
            name=policy_cls.name,
            category=policy_cls.category,
            reward_types=[rt.value for rt in policy_cls.reward_types],
            description=description,
            user_params=[
                ProxyGRPCServicer._policy_param_to_proto(p)
                for p in policy_cls.user_params()
            ],
        )

    @staticmethod
    def _policy_param_to_proto(param) -> proxy_pb2.PolicyParam:
        return proxy_pb2.PolicyParam(
            name=param.name,
            type=param.type,
            required=param.required,
            default=ProxyGRPCServicer._to_proto_value(param.default),
            description=param.description,
            constraints={k: float(v) for k, v in param.constraints.items()},
        )

    @staticmethod
    def _to_proto_value(value) -> struct_pb2.Value:
        v = struct_pb2.Value()
        if value is None:
            v.null_value = struct_pb2.NULL_VALUE
        elif isinstance(value, bool):
            v.bool_value = value
        elif isinstance(value, (int, float)):
            v.number_value = float(value)
        elif isinstance(value, str):
            v.string_value = value
        else:
            v.string_value = json.dumps(value)
        return v

    async def Health(self, request, context):
        healthy = await self._service.health()
        return common_pb2.HealthCheckResponse(
            status=(
                common_pb2.HealthCheckResponse.SERVING
                if healthy
                else common_pb2.HealthCheckResponse.NOT_SERVING
            )
        )

    @staticmethod
    def _dict_to_pool(d: dict) -> common_pb2.Pool:
        return common_pb2.Pool(
            id=d["id"],
            name=d["name"],
            arms=[
                common_pb2.Arm(
                    id=arm["id"],
                    name=arm["name"],
                    index=arm["index"],
                    is_active=arm.get("is_active", True),
                    metadata={
                        k: str(v) for k, v in (arm.get("metadata") or {}).items()
                    },
                )
                for arm in d.get("arms", [])
            ],
            created_at=d.get("created_at") or "",
            updated_at=d.get("updated_at") or "",
        )

    @staticmethod
    def _dict_to_experiment(d: dict) -> common_pb2.Experiment:
        policy_params = d.get("policy_params") or {}
        exp = common_pb2.Experiment(
            id=d["id"],
            name=d["name"],
            pool_id=d["pool_id"],
            policy=d["policy"],
            policy_params={k: str(v) for k, v in policy_params.items()},
            enabled=d.get("enabled", False),
            created_at=d.get("created_at") or "",
            updated_at=d.get("updated_at") or "",
        )
        if policy_params:
            exp.policy_params_json.update(policy_params)
        return exp

    @classmethod
    def _build_experiment_detail(cls, d: dict) -> proxy_pb2.ExperimentDetail:
        detail = proxy_pb2.ExperimentDetail(
            experiment=cls._dict_to_experiment(d),
        )
        if d.get("feature_gate"):
            detail.feature_gate.CopyFrom(cls._config_to_proto_gate(d["feature_gate"]))
        if d.get("pool"):
            detail.pool.CopyFrom(cls._dict_to_pool(d["pool"]))
        return detail

    @staticmethod
    def _proto_to_gate_config(proto: proxy_pb2.FeatureGateConfig) -> GateConfigRequest:
        """convert proto FeatureGateConfig to GateConfigRequest for service layer."""
        schedule_start = None
        schedule_end = None
        active_hours_start = None
        active_hours_end = None

        if proto.HasField("schedule"):
            if proto.schedule.start_timestamp_ms:
                schedule_start = datetime.fromtimestamp(
                    proto.schedule.start_timestamp_ms / 1000, tz=timezone.utc
                ).isoformat()
            if proto.schedule.end_timestamp_ms:
                schedule_end = datetime.fromtimestamp(
                    proto.schedule.end_timestamp_ms / 1000, tz=timezone.utc
                ).isoformat()

        if proto.HasField("active_hours"):
            if proto.active_hours.start:
                active_hours_start = proto.active_hours.start
            if proto.active_hours.end:
                active_hours_end = proto.active_hours.end

        rules = []
        for rule in proto.rules:
            try:
                value = json.loads(rule.value)
            except (json.JSONDecodeError, TypeError):
                value = rule.value
            rules.append(
                RuleRequest(
                    key=rule.key,
                    operator=rule.operator,
                    value=value,
                    arm_id=rule.arm_id or None,
                    arm_name=None,
                )
            )

        return GateConfigRequest(
            enabled=proto.enabled,
            rollout_percentage=proto.rollout_percentage,
            default_arm_id=proto.default_arm_id or None,
            timezone=proto.timezone or "UTC",
            schedule_start=schedule_start,
            schedule_end=schedule_end,
            active_hours_start=active_hours_start,
            active_hours_end=active_hours_end,
            rules=rules,
        )

    @classmethod
    def _proto_to_gate_patch(
        cls, proto: proxy_pb2.FeatureGateConfig, update_mask
    ) -> GateConfigPatchRequest:
        """select the masked fields out of a full proto config.

        proto3 gives no presence on FeatureGateConfig's scalars, so the mask is
        what says which of them the caller meant. an unknown name is rejected
        rather than ignored — a typo that silently changes nothing is the class
        of bug this endpoint exists to remove.
        """
        full = cls._proto_to_gate_config(proto)
        known = set(GateConfigPatchRequest.model_fields)
        unknown = [name for name in update_mask if name not in known]
        if unknown:
            raise InvalidArgumentException(
                f"unknown update_mask field(s): {', '.join(sorted(unknown))}"
            )
        return GateConfigPatchRequest(
            **{name: getattr(full, name) for name in update_mask}
        )

    @staticmethod
    def _config_to_proto_gate(config: FeatureGateConfig) -> proxy_pb2.FeatureGateConfig:
        """convert FeatureGateConfig pydantic instance to proto FeatureGateConfig.

        mirrors to_response() as the canonical reader of FeatureGateConfig —
        hour.timezone is the source of truth for timezone (period and hour share
        the same ZoneInfo by construction in repository.to_config).
        """
        exp = config.experiment
        arm = exp.arm.committed
        proto_config = proxy_pb2.FeatureGateConfig(
            enabled=config.enabled,
            rollout_percentage=exp.rollout.percentage,
            default_arm_id=arm.id or "",
            timezone=str(exp.schedule.hour.timezone),
        )

        if exp.schedule.period.start:
            start = exp.schedule.period.start
            # sqlite returns naive datetime; treat as UTC to match _parse_datetime
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            proto_config.schedule.start_timestamp_ms = int(start.timestamp() * 1000)
        if exp.schedule.period.end:
            end = exp.schedule.period.end
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            proto_config.schedule.end_timestamp_ms = int(end.timestamp() * 1000)
        if exp.schedule.hour.start:
            proto_config.active_hours.start = exp.schedule.hour.start.strftime("%H:%M")
        if exp.schedule.hour.end:
            proto_config.active_hours.end = exp.schedule.hour.end.strftime("%H:%M")

        for r in config.rules:
            proto_config.rules.append(
                proxy_pb2.RuleConfig(
                    key=r.key,
                    operator=str(r.operator),
                    value=r.value if isinstance(r.value, str) else json.dumps(r.value),
                    arm_id=(
                        r.arm.committed.id
                        if r.arm and r.arm.committed and r.arm.committed.id
                        else ""
                    ),
                )
            )

        return proto_config
