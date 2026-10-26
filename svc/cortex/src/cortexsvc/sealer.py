from __future__ import annotations

import asyncio
from collections import Counter
from collections import defaultdict
from typing import Callable
from typing import TypeVar

from redis.asyncio.client import Pipeline

from qbrixcore.context import Context
from qbrixlog import get_logger
from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.ledger import SealedDecision
from qbrixstore.clickhouse.migrations import create_tables
from qbrixstore.redis import LedgerProgress
from qbrixstore.redis import OutcomeDisposition
from qbrixstore.redis.client import Learning
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.streams import oldest_unfinished
from qbrixstore.redis.streams import stream_ms
from qbrixstore.stream import topology
from qbrixruntime.task import drain

from cortexsvc.seal import Classified
from cortexsvc.seal import seal_slice
from cortexsvc.trainer import POLICY_MAP
from cortexsvc.trainer import learned_state

logger = get_logger(__name__)

T = TypeVar("T")

LEDGER_WRITER = "trace"
LEDGER_STREAMS = (topology.SELECTION, topology.EVENT)

MAX_SLICE_MS = 60_000
# how long an outcome may reach the ledger before the decision it answers;
# both are published by the proxy, the decision before select returns.
DECISION_RACE_MS = 60_000

_BACKOFF_INITIAL_SEC = 0.5
_BACKOFF_MAX_SEC = 30.0


class Sealer:
    """seals decisions from the ledger and teaches each cycle what sealed.

    a pass covers the ledger time from the stored mark up to "complete up
    to", the time before which trace has written every decision and outcome.
    sealed decisions are recorded first, then learned per cycle; each cycle's
    own mark moves in the transaction that stores its learning, so a pass
    repeated after a crash records the same rows again and learns nothing
    twice.
    """

    def __init__(
        self,
        redis: RedisClient,
        clickhouse: ClickHouseClient,
        *,
        interval_sec: float,
        stall_sec: float,
    ):
        for spec in LEDGER_STREAMS:
            spec.require_group(LEDGER_WRITER)
        self._redis = redis
        self._clickhouse = clickhouse
        self._interval_sec = interval_sec
        self._stall_ms = int(stall_sec * 1000)
        self._connected = False
        self._stalled = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sealer")

    async def stop(self) -> None:
        if self._task:
            await drain(self._task)
            self._task = None
        if self._connected:
            self._clickhouse.close()
            self._connected = False

    async def _ch(self, call: Callable[..., T], *args) -> T:
        return await asyncio.to_thread(call, *args)

    async def _connect(self) -> None:
        if self._connected:
            return
        await self._ch(self._clickhouse.connect)
        await self._ch(create_tables, self._clickhouse.client)
        self._connected = True
        logger.info("sealer connected to the ledger")

    async def _run(self) -> None:
        backoff = _BACKOFF_INITIAL_SEC
        while True:
            try:
                await self._connect()
                behind = await self.run_once()
                backoff = _BACKOFF_INITIAL_SEC
            except Exception as e:
                logger.error("sealing pass failed, retrying in %.1fs: %s", backoff, e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
                continue
            if not behind:
                await asyncio.sleep(self._interval_sec)

    async def complete_up_to(self) -> int:
        """the ledger time before which every decision and outcome is written.

        redis's clock is read before the groups, so an entry added after the
        check has an id at or past it.
        """
        now = await self._redis.server_time_ms()
        complete = now
        for spec in LEDGER_STREAMS:
            unfinished = await oldest_unfinished(
                self._redis.client, spec, LEDGER_WRITER
            )
            if unfinished is not None:
                complete = min(complete, stream_ms(unfinished))

        lag_ms = now - complete
        await self._redis.set_ledger_progress(LedgerProgress(complete, lag_ms, now))
        if lag_ms > self._stall_ms and not self._stalled:
            logger.error(
                "the ledger is %.1fs behind: trace is not writing, so sealing "
                "and learning wait",
                lag_ms / 1000,
            )
        elif lag_ms <= self._stall_ms and self._stalled:
            logger.info("the ledger is written again, sealing resumes")
        self._stalled = lag_ms > self._stall_ms
        return complete

    async def run_once(self) -> bool:
        """seal one slice; returns whether the ledger holds more to seal."""
        complete = await self.complete_up_to()
        mark = await self._redis.sealer_mark()
        if mark is None:
            mark = await self._ch(self._clickhouse.first_decision_ms)
            if mark is None:
                return False

        end = min(complete, mark + MAX_SLICE_MS)
        if end <= mark:
            return False
        await self.seal(mark, end)
        await self._redis.set_sealer_mark(end)
        return end < complete

    async def seal(self, start_ms: int, end_ms: int) -> None:
        closing = await self._ch(self._clickhouse.query_window_seals, start_ms, end_ms)
        refs = await self._ch(
            self._clickhouse.query_arrived_outcomes,
            start_ms - DECISION_RACE_MS,
            end_ms,
        )
        known = {decision.decision_id for decision in closing}
        answered = await self._ch(
            self._clickhouse.query_decisions,
            [ref for ref in refs if ref.decision_id not in known],
        )
        decisions = closing + answered
        outcomes = await self._ch(self._clickhouse.query_outcomes, decisions, end_ms)

        result = seal_slice(decisions, outcomes, start_ms, end_ms)
        await self._ch(self._clickhouse.insert_sealed_decisions, result.sealed)

        sealed: dict[tuple[str, str], list[SealedDecision]] = defaultdict(list)
        for decision in result.sealed:
            sealed[(decision.tenant_id, decision.cycle_id)].append(decision)
        classified: dict[tuple[str, str], list[Classified]] = defaultdict(list)
        for outcome in result.classified:
            classified[(outcome.tenant_id, outcome.cycle_id)].append(outcome)

        for tenant_id, cycle_id in sorted(set(sealed) | set(classified)):
            await self._learn(
                tenant_id,
                cycle_id,
                sealed[(tenant_id, cycle_id)],
                classified[(tenant_id, cycle_id)],
                end_ms,
            )

        if result.sealed or result.classified:
            logger.info(
                "sealed %d decisions and counted %d outcomes up to %d",
                len(result.sealed),
                len(result.classified),
                end_ms,
            )

    async def _learn(
        self,
        tenant_id: str,
        cycle_id: str,
        sealed: list[SealedDecision],
        classified: list[Classified],
        end_ms: int,
    ) -> None:
        """teach one cycle what sealed in the slice, with the slice's outcome
        counts, in one transaction. the cycle's mark keeps a repeated slice
        from teaching or counting anything twice."""
        counts: dict[OutcomeDisposition, int] = {}
        last_arrival_ms: int | None = None

        def train(record: dict | None, current: Learning) -> Learning | None:
            nonlocal counts, last_arrival_ms
            fresh = [
                decision
                for decision in sealed
                if decision.sealed_ms >= current.sealed_up_to
                and decision.value is not None
            ]
            arrived = [o for o in classified if o.ledger_ms >= current.sealed_up_to]
            counts = dict(Counter(outcome.disposition for outcome in arrived))
            last_arrival_ms = max((o.ledger_ms for o in arrived), default=None)

            if record is None:
                logger.warning(
                    "%s/%s: cycle has no record, %d sealed decisions not learned",
                    tenant_id,
                    cycle_id,
                    len(fresh),
                )
                counts = {}
                return None
            policy_cls = POLICY_MAP.get(record["policy"])
            if policy_cls is None:
                counts[OutcomeDisposition.UNKNOWN_POLICY] = counts.pop(
                    OutcomeDisposition.LEARNED, 0
                )
                return None

            state = learned_state(policy_cls, record, current)
            try:
                for decision in fresh:
                    state = policy_cls.train(
                        ps=state,
                        context=Context(id=decision.unit),
                        choice=decision.option_index,
                        reward=decision.value,
                    )
            except Exception as e:
                logger.error(
                    "%s/%s: training on sealed decisions failed: %s",
                    tenant_id,
                    cycle_id,
                    e,
                )
                counts[OutcomeDisposition.TRAIN_ERROR] = counts.pop(
                    OutcomeDisposition.LEARNED, 0
                )
                return None

            return current.seal(
                state.model_dump(),
                len(fresh),
                max(current.sealed_up_to, end_ms),
            )

        def ack(pipe: Pipeline) -> None:
            self._redis.stage_outcomes(
                pipe, tenant_id, cycle_id, counts, last_arrival_ms
            )

        await self._redis.apply_learning(tenant_id, cycle_id, train, ack)
