from qbrixcore.param.backend import BaseParamBackend
from qbrixcore.param.state import BaseParamState
from qbrixstore.redis.client import RedisClient

from motorsvc.cache import MotorCache


class RedisParamBackend(BaseParamBackend):
    def __init__(self, redis_client: RedisClient, cache: MotorCache):
        self._redis = redis_client
        self._cache = cache

    def get(self, experiment_id: str) -> BaseParamState | None:
        cached = self._cache.get_params(experiment_id)
        if cached is not None:
            return cached
        return None

    def set(self, experiment_id: str, params: BaseParamState) -> None:
        self._cache.set_params(experiment_id, params)

    async def refresh_from_redis(self, experiment_id: str) -> dict | None:
        params = await self._redis.get_params(experiment_id)
        if params is not None:
            self._cache.set_params(experiment_id, params)
        return params
