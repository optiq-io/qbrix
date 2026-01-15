import time

from qbrixstore.postgres.session import init_db, get_session, create_tables
from qbrixstore.postgres.models import Pool, Experiment
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.streams import RedisStreamPublisher, FeedbackEvent
from qbrixstore.config import PostgresSettings, RedisSettings

from proxysvc.config import ProxySettings
from proxysvc.repository import PoolRepository, ExperimentRepository
from proxysvc.motor_client import MotorClient


class ProxyService:
    def __init__(self, settings: ProxySettings):
        self._settings = settings
        self._redis: RedisClient | None = None
        self._publisher: RedisStreamPublisher | None = None
        self._motor_client: MotorClient | None = None

    async def start(self) -> None:
        pg_settings = PostgresSettings(
            host=self._settings.postgres_host,
            port=self._settings.postgres_port,
            user=self._settings.postgres_user,
            password=self._settings.postgres_password,
            database=self._settings.postgres_database
        )
        init_db(pg_settings)
        await create_tables()

        redis_settings = RedisSettings(
            host=self._settings.redis_host,
            port=self._settings.redis_port,
            password=self._settings.redis_password,
            db=self._settings.redis_db,
            stream_name=self._settings.stream_name
        )
        self._redis = RedisClient(redis_settings)
        await self._redis.connect()

        self._publisher = RedisStreamPublisher(redis_settings)
        await self._publisher.connect()

        self._motor_client = MotorClient(self._settings.motor_address)
        await self._motor_client.connect()

    async def stop(self) -> None:
        if self._motor_client:
            await self._motor_client.close()
        if self._publisher:
            await self._publisher.close()
        if self._redis:
            await self._redis.close()

    async def create_pool(self, name: str, arms: list[dict]) -> dict:
        async with get_session() as session:
            repo = PoolRepository(session)
            pool = await repo.create(name, arms)
            return self._pool_to_dict(pool)

    async def get_pool(self, pool_id: str) -> dict | None:
        async with get_session() as session:
            repo = PoolRepository(session)
            pool = await repo.get(pool_id)
            if pool is None:
                return None
            return self._pool_to_dict(pool)

    async def create_experiment(
        self,
        name: str,
        pool_id: str,
        protocol: str,
        protocol_params: dict,
        enabled: bool,
        feature_gate_config: dict | None = None
    ) -> dict:
        async with get_session() as session:
            repo = ExperimentRepository(session)
            experiment = await repo.create(
                name=name,
                pool_id=pool_id,
                protocol=protocol,
                protocol_params=protocol_params,
                enabled=enabled,
                feature_gate_config=feature_gate_config
            )
            exp_dict = self._experiment_to_dict(experiment)
            await self._sync_experiment_to_redis(exp_dict)
            return exp_dict

    async def get_experiment(self, experiment_id: str) -> dict | None:
        async with get_session() as session:
            repo = ExperimentRepository(session)
            experiment = await repo.get(experiment_id)
            if experiment is None:
                return None
            return self._experiment_to_dict(experiment)

    async def update_experiment(self, experiment_id: str, **kwargs) -> dict | None:
        async with get_session() as session:
            repo = ExperimentRepository(session)
            experiment = await repo.update(experiment_id, **kwargs)
            if experiment is None:
                return None
            exp_dict = self._experiment_to_dict(experiment)
            await self._sync_experiment_to_redis(exp_dict)
            return exp_dict

    async def select(
        self,
        experiment_id: str,
        context_id: str,
        context_vector: list[float],
        context_metadata: dict
    ) -> dict:
        # TODO: Add feature gate check here
        return await self._motor_client.select(
            experiment_id=experiment_id,
            context_id=context_id,
            context_vector=context_vector,
            context_metadata=context_metadata
        )

    async def feedback(
        self,
        experiment_id: str,
        request_id: str,
        arm_index: int,
        reward: float,
        context_id: str,
        context_vector: list[float],
        context_metadata: dict
    ) -> bool:
        event = FeedbackEvent(
            experiment_id=experiment_id,
            request_id=request_id,
            arm_index=arm_index,
            reward=reward,
            context_id=context_id,
            context_vector=context_vector,
            context_metadata=context_metadata,
            timestamp_ms=int(time.time() * 1000)
        )
        await self._publisher.publish(event)
        return True

    async def _sync_experiment_to_redis(self, experiment: dict) -> None:
        await self._redis.set_experiment(experiment["id"], experiment)

    async def health(self) -> bool:
        try:
            await self._redis.client.ping()
            return True
        except Exception:
            return False

    def _pool_to_dict(self, pool: Pool) -> dict:
        return {
            "id": pool.id,
            "name": pool.name,
            "arms": [
                {"id": arm.id, "name": arm.name, "index": arm.index, "is_active": arm.is_active}
                for arm in sorted(pool.arms, key=lambda a: a.index)
            ]
        }

    def _experiment_to_dict(self, experiment: Experiment) -> dict:
        return {
            "id": experiment.id,
            "name": experiment.name,
            "pool_id": experiment.pool_id,
            "pool": self._pool_to_dict(experiment.pool) if experiment.pool else None,
            "protocol": experiment.protocol,
            "protocol_params": experiment.protocol_params,
            "enabled": experiment.enabled
        }
