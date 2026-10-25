from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

import redis.asyncio as redis
from redis.asyncio.client import Pipeline
from redis.exceptions import WatchError

from qbrixstore.config import RedisSettings
from qbrixstore.redis.health import LoopSelectReason
from qbrixstore.redis.health import OUTCOME_HEALTH_TTL_SEC
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import OutcomeHealth
from qbrixstore.redis.health import SELECT_HEALTH_TTL_SEC
from qbrixstore.redis.health import SelectErrorReason
from qbrixstore.redis.health import SelectHealth
from qbrixstore.redis.health import SelectOutcome

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

    async def restore_learning(
        self, tenant_id: str, experiment_id: str, learning: Learning
    ) -> Learning:
        """replace the learning with ``learning`` and return what it replaced.

        watched like ``apply_learning``, so the returned learning is exactly
        the one the restore overwrote, even while cortex trains.
        """
        experiment_key = self._experiment_key(tenant_id, experiment_id)
        param_key = self._param_key(tenant_id, experiment_id)
        learning_key = self._learning_key(tenant_id, experiment_id)

        async with self.client.pipeline(transaction=True) as pipe:
            for _ in range(_LEARNING_ATTEMPTS):
                try:
                    await pipe.watch(experiment_key, param_key, learning_key)
                    params, record = await pipe.mget(param_key, learning_key)
                    replaced = Learning.decode(params, record)
                    pipe.multi()
                    if learning.params is None:
                        # noinspection PyAsyncCall
                        pipe.delete(param_key)
                    else:
                        # noinspection PyAsyncCall
                        pipe.set(param_key, json.dumps(learning.params))
                    # noinspection PyAsyncCall
                    pipe.set(learning_key, learning.encode_record())
                    await pipe.execute()
                    return replaced
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

    @staticmethod
    def _select_health_key(
        tenant_id: str,
        experiment_id: str,
        minute: int,
        outcome: SelectOutcome,
        reason: SelectErrorReason | None = None,
    ) -> str:
        key = (
            f"qbrix:tenant:{tenant_id}:health:select:{experiment_id}"
            f":{minute}:{outcome.value}"
        )
        return f"{key}:{reason.value}" if reason is not None else key

    async def record_select(
        self,
        tenant_id: str,
        experiment_id: str,
        outcome: SelectOutcome,
        reason: SelectErrorReason | None = None,
        minute: int | None = None,
    ) -> None:
        """count one select call in its minute bucket, and its reason if any."""
        if minute is None:
            minute = int(time.time()) // 60
        keys = [self._select_health_key(tenant_id, experiment_id, minute, outcome)]
        if reason is not None:
            keys.append(
                self._select_health_key(
                    tenant_id, experiment_id, minute, outcome, reason
                )
            )
        pipe = self.client.pipeline(transaction=False)
        for key in keys:
            # noinspection PyAsyncCall
            pipe.incr(key)
            # noinspection PyAsyncCall
            pipe.expire(key, SELECT_HEALTH_TTL_SEC)
        await pipe.execute()

    async def select_health(
        self,
        tenant_id: str,
        experiment_id: str,
        window_minutes: int,
        now_minute: int | None = None,
    ) -> SelectHealth:
        """sum the select outcomes of the last ``window_minutes`` minutes,
        the current one included."""
        if now_minute is None:
            now_minute = int(time.time()) // 60
        minutes = range(now_minute - window_minutes + 1, now_minute + 1)
        slots: list[tuple[SelectOutcome, SelectErrorReason | None]] = [
            (outcome, None) for outcome in SelectOutcome
        ] + [(SelectOutcome.ERROR, reason) for reason in SelectErrorReason]
        keys = [
            self._select_health_key(tenant_id, experiment_id, m, outcome, reason)
            for m in minutes
            for outcome, reason in slots
        ]
        values = await self.client.mget(keys) if keys else []

        outcomes = {outcome: 0 for outcome in SelectOutcome}
        by_reason: dict[str, int] = {}
        for (outcome, reason), value in zip(slots * len(minutes), values):
            if not value:
                continue
            if reason is None:
                outcomes[outcome] += int(value)
            else:
                by_reason[reason.value] = by_reason.get(reason.value, 0) + int(value)

        return SelectHealth(
            ok=outcomes[SelectOutcome.OK],
            client=outcomes[SelectOutcome.CLIENT],
            error=outcomes[SelectOutcome.ERROR],
            not_found=outcomes[SelectOutcome.NOT_FOUND],
            by_reason=by_reason,
        )

    @staticmethod
    def _loop_select_key(
        tenant_id: str, loop_id: str, minute: int, reason: LoopSelectReason
    ) -> str:
        return (
            f"qbrix:tenant:{tenant_id}:health:loop_select:{loop_id}"
            f":{minute}:{reason.value}"
        )

    async def record_loop_select(
        self,
        tenant_id: str,
        loop_id: str,
        reason: LoopSelectReason,
        minute: int | None = None,
    ) -> None:
        """count one answered select call for a loop by its reason, in its minute."""
        if minute is None:
            minute = int(time.time()) // 60
        key = self._loop_select_key(tenant_id, loop_id, minute, reason)
        pipe = self.client.pipeline(transaction=False)
        # noinspection PyAsyncCall
        pipe.incr(key)
        # noinspection PyAsyncCall
        pipe.expire(key, SELECT_HEALTH_TTL_SEC)
        await pipe.execute()

    async def loop_selects(
        self,
        tenant_id: str,
        loop_id: str,
        window_minutes: int,
        now_minute: int | None = None,
    ) -> dict[str, int]:
        """a loop's answered select calls by reason over the last
        ``window_minutes`` minutes, the current one included."""
        if now_minute is None:
            now_minute = int(time.time()) // 60
        minutes = range(now_minute - window_minutes + 1, now_minute + 1)
        slots = [(m, reason) for m in minutes for reason in LoopSelectReason]
        keys = [self._loop_select_key(tenant_id, loop_id, m, r) for m, r in slots]
        values = await self.client.mget(keys) if keys else []
        counts = {reason.value: 0 for reason in LoopSelectReason}
        for (_, reason), value in zip(slots, values):
            if value:
                counts[reason.value] += int(value)
        return counts

    @staticmethod
    def _outcome_health_key(
        tenant_id: str,
        experiment_id: str,
        minute: int,
        disposition: OutcomeDisposition,
    ) -> str:
        return (
            f"qbrix:tenant:{tenant_id}:health:outcome:{experiment_id}"
            f":{minute}:{disposition.value}"
        )

    @staticmethod
    def _last_arrival_key(tenant_id: str, experiment_id: str) -> str:
        return f"qbrix:tenant:{tenant_id}:health:outcome:{experiment_id}:last_arrival"

    @staticmethod
    def _invalid_outcome_key(tenant_id: str, minute: int) -> str:
        return f"qbrix:tenant:{tenant_id}:health:outcome_invalid:{minute}"

    def stage_outcomes(
        self,
        pipe: Pipeline,
        tenant_id: str,
        experiment_id: str,
        counts: dict[OutcomeDisposition, int],
        last_arrival_ms: int | None = None,
        minute: int | None = None,
    ) -> None:
        """queue outcome counts onto a caller's pipeline, so they land with
        whatever else it writes, or not at all."""
        if minute is None:
            minute = int(time.time()) // 60
        for disposition, count in counts.items():
            if count <= 0:
                continue
            key = self._outcome_health_key(
                tenant_id, experiment_id, minute, disposition
            )
            # noinspection PyAsyncCall
            pipe.incrby(key, count)
            # noinspection PyAsyncCall
            pipe.expire(key, OUTCOME_HEALTH_TTL_SEC)
        if last_arrival_ms is not None:
            # noinspection PyAsyncCall
            pipe.set(
                self._last_arrival_key(tenant_id, experiment_id),
                last_arrival_ms,
                ex=OUTCOME_HEALTH_TTL_SEC,
            )

    async def count_outcomes(
        self,
        tenant_id: str,
        experiment_id: str,
        counts: dict[OutcomeDisposition, int],
        minute: int | None = None,
    ) -> None:
        pipe = self.client.pipeline(transaction=False)
        self.stage_outcomes(pipe, tenant_id, experiment_id, counts, minute=minute)
        await pipe.execute()

    async def count_invalid_outcome(
        self, tenant_id: str, minute: int | None = None
    ) -> None:
        """count an outcome whose token failed verification. it names no
        experiment that can be trusted, so it is counted per tenant only."""
        if minute is None:
            minute = int(time.time()) // 60
        key = self._invalid_outcome_key(tenant_id, minute)
        pipe = self.client.pipeline(transaction=False)
        # noinspection PyAsyncCall
        pipe.incr(key)
        # noinspection PyAsyncCall
        pipe.expire(key, OUTCOME_HEALTH_TTL_SEC)
        await pipe.execute()

    async def invalid_outcomes(
        self, tenant_id: str, window_minutes: int, now_minute: int | None = None
    ) -> int:
        if now_minute is None:
            now_minute = int(time.time()) // 60
        keys = [
            self._invalid_outcome_key(tenant_id, m)
            for m in range(now_minute - window_minutes + 1, now_minute + 1)
        ]
        values = await self.client.mget(keys) if keys else []
        return sum(int(value) for value in values if value)

    async def outcome_health(
        self,
        tenant_id: str,
        experiment_id: str,
        window_minutes: int,
        now_minute: int | None = None,
    ) -> OutcomeHealth:
        """sum the outcome dispositions of the last ``window_minutes`` minutes,
        the current one included, with the last arrival."""
        if now_minute is None:
            now_minute = int(time.time()) // 60
        minutes = range(now_minute - window_minutes + 1, now_minute + 1)
        dispositions = list(OutcomeDisposition)
        keys = [
            self._outcome_health_key(tenant_id, experiment_id, m, disposition)
            for m in minutes
            for disposition in dispositions
        ]
        *values, last_arrival = await self.client.mget(
            *keys, self._last_arrival_key(tenant_id, experiment_id)
        )

        learned = 0
        by_reason: dict[str, int] = {}
        for disposition, value in zip(dispositions * len(minutes), values):
            if not value:
                continue
            if disposition is OutcomeDisposition.LEARNED:
                learned += int(value)
            else:
                by_reason[disposition.value] = by_reason.get(
                    disposition.value, 0
                ) + int(value)

        return OutcomeHealth(
            learned=learned,
            not_learned=sum(by_reason.values()),
            by_reason=by_reason,
            last_arrival_ms=int(last_arrival) if last_arrival is not None else None,
        )
