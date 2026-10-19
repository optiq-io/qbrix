from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import redis.asyncio as redis
from redis.asyncio.client import Pipeline
from redis.exceptions import WatchError

from qbrixstore.config import RedisSettings

_LEARNING_ATTEMPTS = 5


def _stream_id(message_id: str) -> tuple[int, int]:
    ms, _, seq = message_id.partition("-")
    return int(ms), int(seq or 0)


@dataclass(frozen=True)
class Learning:
    """what an experiment has learned: its params, how many outcomes they
    include, and the highest feedback stream id applied to them."""

    params: dict | None
    applied: int = 0
    last_id: str = "0-0"

    def includes(self, message_id: str) -> bool:
        return _stream_id(message_id) <= _stream_id(self.last_id)

    def advance(self, params: dict, message_ids: list[str]) -> Learning:
        return Learning(
            params=params,
            applied=self.applied + len(message_ids),
            last_id=max([self.last_id, *message_ids], key=_stream_id),
        )

    @classmethod
    def decode(cls, params: str | None, record: str | None) -> Learning:
        if record is None:
            return cls(params=json.loads(params) if params is not None else None)
        fields = json.loads(record)
        return cls(
            params=json.loads(params) if params is not None else None,
            applied=fields["applied"],
            last_id=fields["last_id"],
        )

    def encode_record(self) -> str:
        return json.dumps({"applied": self.applied, "last_id": self.last_id})


Train = Callable[[dict | None, Learning], Learning | None]
StageAck = Callable[[Pipeline], None]


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
    def _learning_key(tenant_id: str, experiment_id: str) -> str:
        return f"qbrix:tenant:{tenant_id}:learning:{experiment_id}"

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

    async def read_learning(self, tenant_id: str, experiment_id: str) -> Learning:
        params, record = await self.client.mget(
            self._param_key(tenant_id, experiment_id),
            self._learning_key(tenant_id, experiment_id),
        )
        return Learning.decode(params, record)

    async def apply_learning(
        self,
        tenant_id: str,
        experiment_id: str,
        train: Train,
        ack: StageAck,
    ) -> Learning | None:
        """train on the current learning and commit the result with the ack.

        the experiment, params and learning record are watched, so a reset,
        delete or pause that lands while ``train`` runs reruns it on the fresh
        state instead of being overwritten. ``train`` returns ``None`` when
        there is nothing to write; the ack is committed either way.
        """
        experiment_key = self._experiment_key(tenant_id, experiment_id)
        param_key = self._param_key(tenant_id, experiment_id)
        learning_key = self._learning_key(tenant_id, experiment_id)

        async with self.client.pipeline(transaction=True) as pipe:
            for _ in range(_LEARNING_ATTEMPTS):
                try:
                    await pipe.watch(experiment_key, param_key, learning_key)
                    experiment, params, record = await pipe.mget(
                        experiment_key, param_key, learning_key
                    )
                    learned = train(
                        json.loads(experiment) if experiment is not None else None,
                        Learning.decode(params, record),
                    )
                    pipe.multi()
                    if learned is not None:
                        # noinspection PyAsyncCall
                        pipe.set(param_key, json.dumps(learned.params))
                        # noinspection PyAsyncCall
                        pipe.set(learning_key, learned.encode_record())
                    ack(pipe)
                    await pipe.execute()
                    return learned
                except WatchError:
                    continue
        raise WatchError(
            f"learning for {tenant_id}/{experiment_id} kept changing during "
            f"{_LEARNING_ATTEMPTS} attempts"
        )

    async def reset_learning(self, tenant_id: str, experiment_id: str) -> None:
        await self.client.delete(
            self._param_key(tenant_id, experiment_id),
            self._learning_key(tenant_id, experiment_id),
        )

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
            self._learning_key(tenant_id, experiment_id),
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
