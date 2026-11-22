from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
from typing import TypeVar

from cachebox import TTLCache
from qbrixstore.clickhouse.client import ARRIVAL_BUCKETS
from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.ledger import MetricArrival
from qbrixstore.clickhouse.ledger import MetricPulse
from qbrixstore.clickhouse.ledger import MetricVersion
from qbrixstore.redis.client import RedisClient

T = TypeVar("T")

MINUTE_MS = 60_000
ARRIVAL_RANGE_MS = 7 * 24 * 60 * MINUTE_MS
COUNT_HOURS = 7 * 24
PULSE_MINUTES = 30
RATE_MINUTES = 5
CACHE_TTL_SEC = 60.0
CACHE_MAXSIZE = 1024

Reader = Callable[[Callable[[ClickHouseClient], T]], Awaitable[T]]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _version(metric: dict) -> MetricVersion:
    return MetricVersion(
        metric_id=metric["id"],
        version=metric["version"],
        window_ms=metric["window_seconds"] * 1000,
    )


def _late_share(arrival: MetricArrival | None) -> float | None:
    if arrival is None or not arrival.outcomes:
        return None
    return arrival.late / arrival.outcomes


def pulse_of(rows: Sequence[MetricPulse], until_ms: int) -> dict[str, list[int]]:
    """each metric's events per minute, oldest first, one value per minute
    of the pulse whether or not anything arrived in it."""
    since_ms = until_ms - PULSE_MINUTES * MINUTE_MS
    pulses: dict[str, list[int]] = {}
    for row in rows:
        index = (row.minute_ms - since_ms) // MINUTE_MS
        if 0 <= index < PULSE_MINUTES:
            pulse = pulses.setdefault(row.metric_id, [0] * PULSE_MINUTES)
            pulse[index] += row.outcomes
    return pulses


def list_health(arrival: MetricArrival | None, pulse: list[int] | None) -> dict:
    pulse = pulse or [0] * PULSE_MINUTES
    return {
        "outcomes_per_minute": sum(pulse[-RATE_MINUTES:]) / RATE_MINUTES,
        "median_wait_seconds": (
            arrival.half_ms / 1000 if arrival and arrival.outcomes else None
        ),
        "late_share": _late_share(arrival),
        "pulse": pulse,
    }


def arrival_of(arrival: MetricArrival | None, window_seconds: int) -> dict:
    """how a metric's outcomes arrive across its window: equal slices of the
    window, then one bucket for everything after it."""
    has = arrival is not None and arrival.outcomes > 0
    return {
        "outcomes": arrival.outcomes if has else 0,
        "bucket_seconds": window_seconds / ARRIVAL_BUCKETS,
        "buckets": (list(arrival.buckets) if has else [0] * (ARRIVAL_BUCKETS + 1)),
        "half_seconds": arrival.half_ms / 1000 if has else None,
        "p99_seconds": arrival.p99_ms / 1000 if has else None,
        "late_share": _late_share(arrival),
    }


class MetricHealthService:
    """how a metric's outcomes arrive and how they end, across every loop
    that improves it.

    arrival and the pulse are read from the ledger for the whole workspace
    at once and kept a minute: a list of fifty metrics is two queries.
    counts come from redis, by the hour.
    """

    def __init__(
        self,
        redis: RedisClient,
        read: Reader,
        *,
        clock: Callable[[], int] = _now_ms,
    ):
        self._redis = redis
        self._read = read
        self._clock = clock
        self._cache: TTLCache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL_SEC)

    async def list_health(
        self, tenant_id: str, metrics: Sequence[dict]
    ) -> dict[str, dict]:
        """each metric's outcomes a minute now, median wait, share late and
        its pulse, keyed by metric id."""
        if not metrics:
            return {}
        arrivals, pulses = await asyncio.gather(
            self._arrivals(tenant_id, [_version(m) for m in metrics]),
            self._pulses(tenant_id),
        )
        return {
            m["id"]: list_health(arrivals.get(m["id"]), pulses.get(m["id"]))
            for m in metrics
        }

    async def detail_health(self, tenant_id: str, metric: dict) -> dict:
        """how a metric's outcomes arrive across its window, and its counts
        over the last seven days."""
        arrivals, counts = await asyncio.gather(
            self._arrivals(tenant_id, [_version(metric)]),
            self._redis.metric_outcomes(tenant_id, [metric["id"]], COUNT_HOURS),
        )
        return {
            "arrival": arrival_of(arrivals.get(metric["id"]), metric["window_seconds"]),
            "counts": counts[metric["id"]],
        }

    async def _arrivals(
        self, tenant_id: str, versions: list[MetricVersion]
    ) -> dict[str, MetricArrival]:
        key = ("arrival", tenant_id, tuple(versions))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        since = self._clock() - ARRIVAL_RANGE_MS
        rows = await self._read(
            lambda ch: ch.metric_arrivals(tenant_id, versions, since)
        )
        arrivals = {row.metric_id: row for row in rows}
        self._cache[key] = arrivals
        return arrivals

    async def _pulses(self, tenant_id: str) -> dict[str, list[int]]:
        key = ("pulse", tenant_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        until = self._clock() // MINUTE_MS * MINUTE_MS
        since = until - PULSE_MINUTES * MINUTE_MS
        rows = await self._read(lambda ch: ch.metric_pulse(tenant_id, since, until))
        pulses = pulse_of(rows, until)
        self._cache[key] = pulses
        return pulses
