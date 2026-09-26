from qbrixlog import get_logger
from qbrixcore.context import Context
from qbrixstore.redis.client import RedisClient
from qbrixstore.config import RedisSettings

from motorsvc.cache import MotorCache
from motorsvc.config import MotorSettings
from motorsvc.param_backend import RedisBackedInMemoryParamBackend
from motorsvc.agent_factory import AgentFactory

logger = get_logger(__name__)


class MotorService:

    def __init__(self, settings: MotorSettings):
        self._settings = settings
        self._cache = MotorCache(settings)
        self._redis: RedisClient | None = None
        self._param_backend: RedisBackedInMemoryParamBackend | None = None
        self._agent_factory: AgentFactory | None = None

    async def start(self) -> None:
        redis_settings = RedisSettings(
            host=self._settings.redis_host,
            port=self._settings.redis_port,
            password=self._settings.redis_password,
            db=self._settings.redis_db,
        )
        self._redis = RedisClient(redis_settings)
        await self._redis.connect()
        logger.info(
            "connected to redis at %s:%s",
            self._settings.redis_host,
            self._settings.redis_port,
        )

        self._param_backend = RedisBackedInMemoryParamBackend(self._redis, self._cache)
        self._agent_factory = AgentFactory(self._cache, self._param_backend)

    async def stop(self) -> None:
        if self._redis:
            await self._redis.close()
            logger.info("disconnected from redis")

    async def select(
        self,
        tenant_id: str,
        experiment_id: str,
        context_id: str,
        context_vector: list[float],
        context_metadata: dict,
    ) -> dict:
        experiment_record = self._cache.get_experiment(tenant_id, experiment_id)
        if experiment_record is None:
            experiment_record = await self._redis.get_experiment(
                tenant_id, experiment_id
            )
            if experiment_record is None:
                raise ValueError(f"experiment not found: {experiment_id}")
            self._cache.set_experiment(tenant_id, experiment_id, experiment_record)

        context = Context(
            id=context_id, vector=context_vector or [], metadata=context_metadata or {}
        )

        # meta-bandit: two-hop select (meta → learner → arm)
        if experiment_record["policy"] == "MetaBanditPolicy":
            return await self._meta_select(tenant_id, experiment_record, context)

        agent = await self._agent_factory.get_or_create(tenant_id, experiment_record)
        choice_index = agent.select(context)
        arm = agent.pool.arms[choice_index]

        return {
            "arm": {"id": arm.id, "name": arm.name, "index": choice_index},
            "policy": experiment_record["policy"],
        }

    async def _meta_select(
        self,
        tenant_id: str,
        meta_record: dict,
        context: Context,
    ) -> dict:
        """two-hop meta-bandit selection: pick learner, then pick arm."""
        meta_agent = await self._agent_factory.get_or_create(tenant_id, meta_record)
        learner_index = meta_agent.select(context)

        learners = meta_record.get("policy_params", {}).get("learners", [])
        if learner_index >= len(learners):
            raise ValueError(
                f"meta-bandit learner index {learner_index} out of range (M={len(learners)})"
            )
        learner_id = learners[learner_index]

        learner_record = self._cache.get_experiment(tenant_id, learner_id)
        if learner_record is None:
            learner_record = await self._redis.get_experiment(tenant_id, learner_id)
            if learner_record is None:
                raise ValueError(
                    f"meta-bandit learner experiment not found: {learner_id}"
                )
            self._cache.set_experiment(tenant_id, learner_id, learner_record)

        learner_agent = await self._agent_factory.get_or_create(
            tenant_id, learner_record
        )
        arm_index = learner_agent.select(context)
        arm = learner_agent.pool.arms[arm_index]

        return {
            "arm": {"id": arm.id, "name": arm.name, "index": arm_index},
            "learner_experiment_id": learner_id,
            "learner_index": learner_index,
            "policy": learner_record["policy"],
        }

    async def health(self) -> bool:
        try:
            await self._redis.client.ping()
            return True
        except Exception:  # noqa
            return False
