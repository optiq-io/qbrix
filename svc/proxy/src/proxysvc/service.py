from qbrixlog import get_logger
from qbrixstore.postgres.session import init_db
from qbrixstore.redis.client import RedisClient
from qbrixstore.config import PostgresSettings, RedisSettings
from qbrixstore.stream import topology

from proxysvc import edition
from proxysvc.config import ProxySettings
from proxysvc.transport.grpc.client import MotorClient
from proxysvc.transport.grpc.client import CortexClient
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.events import EventEmitter
from proxysvc.mod.agent import AgentService
from proxysvc.mod.experiment.service import ExperimentService
from proxysvc.mod.gate import GateService
from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.schema import GateConfigPatchRequest
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.mod.pool.service import PoolService

logger = get_logger(__name__)


class ProxyService:
    """thin facade over the per-domain services.

    builds the collaborators in start() and forwards each public method to
    the pool / experiment / gate / agent sub-service that owns it. gate-config
    crud and runtime health checks remain inline.
    """

    def __init__(self, settings: ProxySettings):
        self._settings = settings
        self._redis: RedisClient | None = None
        self._events: EventEmitter | None = None
        self._motor_client: MotorClient | None = None
        self._cortex_client: CortexClient | None = None
        self._gate_service: GateService | None = None
        self._agent_service: AgentService | None = None
        self._pool_service: PoolService | None = None
        self._experiment_service: ExperimentService | None = None
        self._entitlements: Entitlements | None = None

    async def start(self) -> None:
        pg_settings = PostgresSettings(
            host=self._settings.postgres_host,
            port=self._settings.postgres_port,
            user=self._settings.postgres_user,
            password=self._settings.postgres_password,
            database=self._settings.postgres_database,
        )
        init_db(pg_settings)

        redis_settings = RedisSettings(
            host=self._settings.redis_host,
            port=self._settings.redis_port,
            password=self._settings.redis_password,
            db=self._settings.redis_db,
        )
        self._redis = RedisClient(redis_settings)
        await self._redis.connect()

        self._events = EventEmitter.for_settings(redis_settings, self._settings)
        await self._events.start()

        self._motor_client = MotorClient(
            self._settings.motor_address, self._settings.motor_client_settings
        )
        await self._motor_client.connect()

        self._cortex_client = CortexClient(
            self._settings.cortex_address, self._settings.cortex_client_settings
        )
        await self._cortex_client.connect()

        self._gate_service = GateService(
            self._redis,
            self._settings,
            events=self._events,
        )

        self._build_services()

    def _build_services(self) -> None:
        """wire the per-domain sub-services from the constructed collaborators.

        called at the end of start(); test fixtures that inject mock
        collaborators directly call this to assemble the facade.
        """
        if self._entitlements is None:
            self._entitlements = edition.entitlements(self._settings, self._redis)
        self._pool_service = PoolService(events=self._events)
        self._experiment_service = ExperimentService(
            redis=self._redis,
            gate_service=self._gate_service,
            cortex_client=self._cortex_client,
            events=self._events,
            settings=self._settings,
            entitlements=self._entitlements,
        )
        self._agent_service = AgentService(
            gate_service=self._gate_service,
            motor_client=self._motor_client,
            events=self._events,
            settings=self._settings,
            experiment_service=self._experiment_service,
            entitlements=self._entitlements,
        )

    @property
    def entitlements(self) -> Entitlements:
        if self._entitlements is None:
            raise RuntimeError("proxy service not started")
        return self._entitlements

    async def stop(self) -> None:
        if self._motor_client:
            await self._motor_client.close()
        if self._cortex_client:
            await self._cortex_client.close()
        if self._events:
            await self._events.stop()
        if self._redis:
            await self._redis.close()

    # pool

    async def create_pool(
        self, tenant_id: str, name: str, arms: list[dict], actor_id: str = ""
    ) -> dict:
        return await self._pool_service.create_pool(tenant_id, name, arms, actor_id)

    async def get_pool(self, tenant_id: str, pool_id: str) -> dict | None:
        return await self._pool_service.get_pool(tenant_id, pool_id)

    async def list_pools(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        return await self._pool_service.list_pools(tenant_id, limit, offset)

    async def update_pool(
        self, tenant_id: str, pool_id: str, actor_id: str = "", **kwargs
    ) -> dict | None:
        return await self._pool_service.update_pool(
            tenant_id, pool_id, actor_id, **kwargs
        )

    async def delete_pool(
        self, tenant_id: str, pool_id: str, actor_id: str = ""
    ) -> bool:
        return await self._pool_service.delete_pool(tenant_id, pool_id, actor_id)

    # experiment

    async def list_pool_experiments(self, tenant_id: str, pool_id: str) -> list[dict]:
        return await self._experiment_service.list_pool_experiments(tenant_id, pool_id)

    async def create_experiment(
        self,
        tenant_id: str,
        name: str,
        pool_id: str,
        policy: str = "",
        policy_params: dict | None = None,
        enabled: bool = True,
        feature_gate_config: GateConfigRequest | None = None,
        actor_id: str = "",
        plan_tier: str = "free",
    ) -> dict:
        return await self._experiment_service.create_experiment(
            tenant_id=tenant_id,
            name=name,
            pool_id=pool_id,
            policy=policy,
            policy_params=policy_params,
            enabled=enabled,
            feature_gate_config=feature_gate_config,
            actor_id=actor_id,
            plan_tier=plan_tier,
        )

    async def create_meta_experiment(
        self,
        tenant_id: str,
        name: str,
        pool_id: str,
        policy_params: dict,
        enabled: bool = True,
        feature_gate_config: GateConfigRequest | None = None,
        actor_id: str = "",
        plan_tier: str = "free",
    ) -> dict:
        return await self._experiment_service.create_meta_experiment(
            tenant_id=tenant_id,
            name=name,
            pool_id=pool_id,
            policy_params=policy_params,
            enabled=enabled,
            feature_gate_config=feature_gate_config,
            actor_id=actor_id,
            plan_tier=plan_tier,
        )

    async def get_experiment(self, tenant_id: str, experiment_id: str) -> dict | None:
        return await self._experiment_service.get_experiment(tenant_id, experiment_id)

    async def list_experiments(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict]:
        return await self._experiment_service.list_experiments(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            search=search,
            enabled=enabled,
        )

    async def update_experiment(
        self,
        tenant_id: str,
        experiment_id: str,
        actor_id: str = "",
        plan_tier: str = "free",
        **kwargs,
    ) -> dict | None:
        return await self._experiment_service.update_experiment(
            tenant_id,
            experiment_id,
            actor_id=actor_id,
            plan_tier=plan_tier,
            **kwargs,
        )

    async def delete_experiment(
        self, tenant_id: str, experiment_id: str, actor_id: str = ""
    ) -> bool:
        return await self._experiment_service.delete_experiment(
            tenant_id, experiment_id, actor_id
        )

    async def reset_experiment(
        self, tenant_id: str, experiment_id: str, actor_id: str = ""
    ) -> dict | None:
        return await self._experiment_service.reset_experiment(
            tenant_id, experiment_id, actor_id
        )

    # gate config

    async def create_gate_config(
        self,
        tenant_id: str,
        experiment_id: str,
        config: GateConfigRequest,
        actor_id: str = "",
    ) -> FeatureGateConfig | None:
        return await self._gate_service.create_gate_config(
            tenant_id, experiment_id, config, actor_id
        )

    async def get_gate_config(
        self, tenant_id: str, experiment_id: str
    ) -> FeatureGateConfig | None:
        return await self._gate_service.get_config(tenant_id, experiment_id)

    async def update_gate_config(
        self,
        tenant_id: str,
        experiment_id: str,
        config: GateConfigRequest,
        actor_id: str = "",
    ) -> FeatureGateConfig | None:
        return await self._gate_service.update_gate_config(
            tenant_id, experiment_id, config, actor_id
        )

    async def patch_gate_config(
        self,
        tenant_id: str,
        experiment_id: str,
        patch: GateConfigPatchRequest,
        actor_id: str = "",
    ) -> FeatureGateConfig | None:
        return await self._gate_service.patch_gate_config(
            tenant_id, experiment_id, patch, actor_id
        )

    async def evaluate_gate_config(
        self,
        tenant_id: str,
        experiment_id: str,
        context_id: str,
        metadata: dict,
    ):
        """dry-run the gate for a sample context; None if no gate is configured."""
        return await self._gate_service.evaluate_trace(
            tenant_id, experiment_id, context_id, metadata
        )

    async def delete_gate_config(
        self, tenant_id: str, experiment_id: str, actor_id: str = ""
    ) -> bool:
        return await self._gate_service.delete_gate_config(
            tenant_id, experiment_id, actor_id
        )

    # agent

    async def select(
        self,
        tenant_id: str,
        experiment_id: str,
        context_id: str,
        context_vector: list[float] | None = None,
        context_metadata: dict | None = None,
        context_properties: dict | None = None,
    ) -> dict:
        return await self._agent_service.select(
            tenant_id=tenant_id,
            experiment_id=experiment_id,
            context_id=context_id,
            context_vector=context_vector,
            context_metadata=context_metadata,
            context_properties=context_properties,
        )

    async def feed(self, request_id: str, reward: float) -> bool:
        return await self._agent_service.feed(request_id, reward)

    # runtime

    async def get_cortex_stream_len(self) -> int | None:
        length = await self._redis.client.xlen(topology.FEEDBACK.name)
        return int(length)

    async def health(self) -> bool:
        try:
            await self._redis.client.ping()
            return True
        except Exception:  # noqa
            return False

    async def motor_health(self) -> bool:
        try:
            return await self._motor_client.health()
        except Exception:  # noqa
            return False

    async def cortex_health(self) -> bool:
        try:
            return await self._cortex_client.health()
        except Exception:  # noqa
            return False
