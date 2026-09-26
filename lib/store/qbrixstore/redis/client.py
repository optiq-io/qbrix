import json

import redis.asyncio as redis

from qbrixstore.config import RedisSettings


class RedisClient:
    def __init__(self, settings: RedisSettings | None = None):
        if settings is None:
            settings = RedisSettings()
        self._settings = settings
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        # from_url builds its own ConnectionPool, so each RedisClient holds a
        # separate pool rather than sharing one process-wide.
        self._client = redis.from_url(self._settings.url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    @staticmethod
    def _param_key(tenant_id: str, experiment_id: str) -> str:
        return f"qbrix:tenant:{tenant_id}:params:{experiment_id}"

    @staticmethod
    def _experiment_key(tenant_id: str, experiment_id: str) -> str:
        return f"qbrix:tenant:{tenant_id}:experiment:{experiment_id}"

    @staticmethod
    def _gate_key(tenant_id: str, experiment_id: str) -> str:
        return f"qbrix:tenant:{tenant_id}:gate:{experiment_id}"

    @staticmethod
    def _usage_key(tenant_id: str, period_key: str) -> str:
        return f"qbrix:tenant:{tenant_id}:usage:selections:{period_key}"

    async def get_params(self, tenant_id: str, experiment_id: str) -> dict | None:
        data = await self.client.get(self._param_key(tenant_id, experiment_id))
        if data is None:
            return None
        return json.loads(data)

    async def set_params(
        self, tenant_id: str, experiment_id: str, params: dict, ttl: int | None = None
    ) -> None:
        key = self._param_key(tenant_id, experiment_id)
        await self.client.set(key, json.dumps(params), ex=ttl)

    async def delete_params(self, tenant_id: str, experiment_id: str) -> None:
        await self.client.delete(self._param_key(tenant_id, experiment_id))

    async def get_experiment(self, tenant_id: str, experiment_id: str) -> dict | None:
        data = await self.client.get(self._experiment_key(tenant_id, experiment_id))
        if data is None:
            return None
        return json.loads(data)

    async def set_experiment(
        self,
        tenant_id: str,
        experiment_id: str,
        experiment: dict,
        ttl: int | None = None,
    ) -> None:
        key = self._experiment_key(tenant_id, experiment_id)
        await self.client.set(key, json.dumps(experiment), ex=ttl)

    async def delete_experiment(self, tenant_id: str, experiment_id: str) -> None:
        await self.client.delete(
            self._experiment_key(tenant_id, experiment_id),
            self._param_key(tenant_id, experiment_id),
        )

    async def get_gate_config(self, tenant_id: str, experiment_id: str) -> dict | None:
        data = await self.client.get(self._gate_key(tenant_id, experiment_id))
        if data is None:
            return None
        return json.loads(data)

    async def set_gate_config(
        self, tenant_id: str, experiment_id: str, config: dict, ttl: int | None = None
    ) -> None:
        key = self._gate_key(tenant_id, experiment_id)
        await self.client.set(key, json.dumps(config), ex=ttl)

    async def delete_gate_config(self, tenant_id: str, experiment_id: str) -> None:
        await self.client.delete(self._gate_key(tenant_id, experiment_id))

    async def incr_selection_usage(
        self, tenant_id: str, period_key: str, ttl: int
    ) -> int:
        """atomically increment and return the per-tenant selection counter for the
        billing period, refreshing its ttl so the key expires after the period ends.
        """
        key = self._usage_key(tenant_id, period_key)
        pipe = self.client.pipeline()
        # noinspection PyAsyncCall
        pipe.incr(key)
        # noinspection PyAsyncCall
        pipe.expire(key, ttl)
        response = await pipe.execute()
        return int(response[0]) if response[0] else 0

    async def get_selection_usage(self, tenant_id: str, period_key: str) -> int:
        """read the current selection count for the period without incrementing."""
        value = await self.client.get(self._usage_key(tenant_id, period_key))
        return int(value) if value else 0
