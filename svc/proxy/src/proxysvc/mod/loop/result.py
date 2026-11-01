from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone
from typing import TypeVar

from cachebox import TTLCache
from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.ledger import CycleSpan
from qbrixstore.clickhouse.ledger import DecisionBucket
from qbrixstore.clickhouse.ledger import DecisionCount
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import LedgerProgress
from qbrixstore.redis.health import LoopSelectReason
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import OutcomeHealth
from qbrixstore.redis.health import SelectHealth

from proxysvc.core.error import CycleNotFoundError
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.serialize import cycle_to_dict
from proxysvc.mod.loop.stat import DAY_MS
from proxysvc.mod.loop.stat import MINUTE_MS
from proxysvc.mod.loop.stat import columns
from proxysvc.mod.loop.stat import lift
from proxysvc.mod.loop.stat import option_range
from proxysvc.mod.loop.stat import step_for

T = TypeVar("T")

PERIODS_MS: dict[str, int | None] = {
    "24h": DAY_MS,
    "7d": 7 * DAY_MS,
    "cycle": None,
}
SUMMARY_PERIOD = "24h"
LIFT_RANGE_MS = 7 * DAY_MS
HEALTH_MINUTES = 60
RATE_MINUTES = 5
CACHE_TTL_SEC = 5.0
CACHE_MAXSIZE = 1024
OUTCOME_ENDINGS = (
    OutcomeDisposition.LATE,
    OutcomeDisposition.DUPLICATE,
    OutcomeDisposition.EARLIER_CYCLE,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ms(at: datetime) -> int:
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return int(at.timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _window_ms(loop: Loop) -> int:
    return loop.metric.versions[-1].window_sec * 1000


def _share_span(
    cycle: Cycle, period_ms: int | None, now_ms: int
) -> tuple[CycleSpan, int, list[int]]:
    """the span share reads, snapped to the series' columns, its step and
    the columns. no period reads the whole cycle."""
    started = _ms(cycle.started_at)
    end = _ms(cycle.ended_at) if cycle.ended_at else now_ms
    start = started if period_ms is None else max(started, end - period_ms)
    step = step_for(end - start)
    cells = columns(start, end, step)
    return CycleSpan(cycle.id, cells[0] if cells else start, end), step, cells


def _lift_span(
    cycle: Cycle, window_ms: int, now_ms: int
) -> tuple[CycleSpan, bool] | None:
    """the decisions lift reads, and whether that range is still short of
    full. none until the cycle's first window has closed.

    a current cycle reads the 7 days that end one window ago, so every
    decision in it has sealed; an ended cycle reads all of itself."""
    started = _ms(cycle.started_at)
    ended = _ms(cycle.ended_at) if cycle.ended_at else None
    until = min(ended if ended is not None else now_ms, now_ms - window_ms)
    if until <= started:
        return None
    if ended is None:
        since = max(started, until - LIFT_RANGE_MS)
        return CycleSpan(cycle.id, since, until), started > until - LIFT_RANGE_MS
    return CycleSpan(cycle.id, started, until), until < ended


def _rate(decisions: int, cycle: Cycle | None, now_ms: int) -> float:
    """decisions a second over the last few minutes, the current one only as
    far as it has run, and never over more than the cycle has run."""
    elapsed = (RATE_MINUTES - 1) * MINUTE_MS + now_ms % MINUTE_MS
    if cycle is not None:
        elapsed = min(elapsed, now_ms - _ms(cycle.started_at))
    return decisions / (elapsed / 1000) if elapsed > 0 else 0.0


def _pick_cycle(loop: Loop, number: int | None) -> Cycle | None:
    if number is None:
        return loop.cycles[-1] if loop.cycles else None
    for cycle in loop.cycles:
        if cycle.number == number:
            return cycle
    raise CycleNotFoundError(f"loop {loop.key!r} has no cycle {number}")


class LoopResultService:
    """a loop's results, read from the ledger: how decisions are shared
    across options, what is still waiting to seal, lift over an even split,
    and the counters health is judged by.

    every number about outcomes reads sealed decisions only, the ones the
    engines learned from; share counts every decision. nothing here depends
    on the engine.
    """

    def __init__(
        self,
        redis: RedisClient,
        clickhouse: ClickHouseClient | None,
        *,
        clock: Callable[[], int] = _now_ms,
    ):
        self._redis = redis
        self._clickhouse = clickhouse
        self._connected = False
        self._connecting = threading.Lock()
        self._clock = clock
        self._cache: TTLCache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL_SEC)

    def _ledger(self) -> ClickHouseClient:
        if self._clickhouse is None:
            raise RuntimeError("loop results have no clickhouse client")
        with self._connecting:
            if not self._connected:
                self._clickhouse.connect(create_database=False)
                self._connected = True
        return self._clickhouse

    async def _read(self, query: Callable[[ClickHouseClient], T]) -> T:
        """run a ledger query on a worker thread: the driver blocks, and a
        slow query must never hold a decision on the event loop."""
        return await asyncio.to_thread(lambda: query(self._ledger()))

    async def results(
        self,
        tenant_id: str,
        ref: str,
        *,
        cycle_number: int | None = None,
        period: str = SUMMARY_PERIOD,
    ) -> dict | None:
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
        if loop is None:
            return None
        cycle = _pick_cycle(loop, cycle_number)
        progress = await self._redis.ledger_progress()

        now = self._clock()
        calls, recent, health, ledger = await asyncio.gather(
            self._redis.loop_selects(tenant_id, loop.id, HEALTH_MINUTES),
            self._redis.loop_selects(
                tenant_id, loop.id, RATE_MINUTES, now_minute=now // MINUTE_MS
            ),
            self._health(tenant_id, cycle, progress),
            self._cycle_results(tenant_id, loop, cycle, period, progress),
        )
        return {
            "cycle": cycle_to_dict(cycle) if cycle else None,
            "range": period,
            **ledger,
            "calls": calls,
            "decisions_per_second": _rate(
                recent[LoopSelectReason.LIVE.value], cycle, now
            ),
            "health": health,
        }

    async def _cycle_results(
        self,
        tenant_id: str,
        loop: Loop,
        cycle: Cycle | None,
        period: str,
        progress: LedgerProgress | None,
    ) -> dict:
        if cycle is None:
            return {"share": None, "lift": None}
        key = (tenant_id, cycle.id, period)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        now = self._clock()
        span, step, cells = _share_span(cycle, PERIODS_MS[period], now)
        lifted = _lift_span(cycle, _window_ms(loop), now)
        cut = progress.complete_up_to_ms if progress else None
        buckets, counts, stats = await asyncio.gather(
            self._read(
                lambda ch: ch.decision_series(
                    tenant_id, cycle.id, span.since_ms, span.until_ms, step
                )
            ),
            self._read(lambda ch: ch.decision_counts(tenant_id, [span], cut)),
            self._read(
                lambda ch: ch.sealed_stats(tenant_id, [lifted[0]] if lifted else [])
            ),
        )

        result = {
            "share": _share_result(cycle, span, step, cells, counts, buckets),
            "lift": (
                _lift_result(loop.metric.type, cycle.options, stats, *lifted)
                if lifted
                else None
            ),
        }
        self._cache[key] = result
        return result

    async def _health(
        self, tenant_id: str, cycle: Cycle | None, progress: LedgerProgress | None
    ) -> dict:
        learned_up_to = 0
        if cycle is None:
            selects, outcomes = SelectHealth(), OutcomeHealth()
        else:
            selects, outcomes, learning = await asyncio.gather(
                self._redis.select_health(tenant_id, cycle.id, HEALTH_MINUTES),
                self._redis.outcome_health(tenant_id, cycle.id, HEALTH_MINUTES),
                self._redis.read_learning(tenant_id, cycle.id),
            )
            learned_up_to = learning.sealed_up_to
        return {
            "decision_errors": selects.error,
            "outcomes": {
                "learned": outcomes.learned,
                **{
                    ending.value: outcomes.by_reason.get(ending.value, 0)
                    for ending in OUTCOME_ENDINGS
                },
            },
            "last_outcome_at": (
                _iso(outcomes.last_arrival_ms)
                if outcomes.last_arrival_ms is not None
                else None
            ),
            "last_learned_at": _iso(learned_up_to) if learned_up_to else None,
            "ledger_lag_ms": progress.lag_ms if progress else None,
        }

    async def summaries(self, tenant_id: str, loops: Sequence[Loop]) -> dict:
        """each loop's share over the last day and its lift, keyed by loop id,
        from one query per table for the whole page. a draft has none."""
        live = [(loop, loop.cycles[-1]) for loop in loops if loop.cycles]
        if not live:
            return {}
        now = self._clock()
        shares = {
            cycle.id: _share_span(cycle, PERIODS_MS[SUMMARY_PERIOD], now)[0]
            for _, cycle in live
        }
        lifts = {
            cycle.id: lifted
            for loop, cycle in live
            if (lifted := _lift_span(cycle, _window_ms(loop), now))
        }
        counts, stats = await asyncio.gather(
            self._read(
                lambda ch: ch.decision_counts(tenant_id, list(shares.values()), None)
            ),
            self._read(
                lambda ch: ch.sealed_stats(
                    tenant_id, [span for span, _ in lifts.values()]
                )
            ),
        )

        summaries = {}
        for loop, cycle in live:
            counted = _by_option(cycle, [c for c in counts if c.cycle_id == cycle.id])
            total = sum(count.decisions for count in counted)
            lifted = lifts.get(cycle.id)
            sealed = {s.option_index: s for s in stats if s.cycle_id == cycle.id}
            summaries[loop.id] = {
                "share": [
                    {
                        "key": option["key"],
                        "share": count.decisions / total if total else None,
                    }
                    for option, count in zip(cycle.options, counted)
                ],
                "lift": (
                    lift(_sealed_per_option(sealed, cycle.options)) if lifted else None
                ),
                "early": lifted[1] if lifted else False,
            }
        return summaries


def _by_option(cycle: Cycle, counts: Sequence[DecisionCount]) -> list[DecisionCount]:
    """the cycle's counts in option order, zero for an option with none."""
    found = {count.option_index: count for count in counts}
    return [
        found.get(index, DecisionCount(cycle.id, index, 0, 0, 0))
        for index in range(len(cycle.options))
    ]


def _share_result(
    cycle: Cycle,
    span: CycleSpan,
    step: int,
    cells: list[int],
    counts: Sequence[DecisionCount],
    buckets: Sequence[DecisionBucket],
) -> dict:
    counted = _by_option(cycle, counts)
    total = sum(count.decisions for count in counted)
    series = {(b.bucket_ms, b.option_index): b.decisions for b in buckets}
    return {
        "since": _iso(span.since_ms),
        "until": _iso(span.until_ms),
        "step_seconds": step // 1000,
        "options": [
            {
                "key": option["key"],
                "name": option["name"],
                "decisions": count.decisions,
                "share": count.decisions / total if total else None,
                "sealed": count.sealed,
                "waiting": count.waiting,
            }
            for option, count in zip(cycle.options, counted)
        ],
        "series": [
            {
                "at": _iso(cell),
                "decisions": [
                    series.get((cell, index), 0) for index in range(len(cycle.options))
                ],
            }
            for cell in cells
        ],
    }


def _sealed_per_option(sealed: dict, options: list) -> list[tuple[int, float]]:
    return [
        (sealed[index].n, sealed[index].total) if index in sealed else (0, 0.0)
        for index in range(len(options))
    ]


def _lift_result(
    metric_type: str, options: list, stats: list, span: CycleSpan, early: bool
) -> dict:
    sealed = {s.option_index: s for s in stats}
    per_option = []
    for index, option in enumerate(options):
        found = sealed.get(index)
        n = found.n if found else 0
        bounds = (
            option_range(metric_type, n, found.total, found.total_sq) if found else None
        )
        per_option.append(
            {
                "key": option["key"],
                "name": option["name"],
                "sealed": n,
                "mean": found.total / n if n else None,
                "low": bounds[0] if bounds else None,
                "high": bounds[1] if bounds else None,
            }
        )
    return {
        "value": lift(_sealed_per_option(sealed, options)),
        "early": early,
        "since": _iso(span.since_ms),
        "until": _iso(span.until_ms),
        "options": per_option,
    }
