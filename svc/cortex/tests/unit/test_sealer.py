"""the sealer against a ledger held in memory and redis on fakeredis: what it
seals, what each cycle learns, where it waits, and that a crash anywhere in a
pass leaves every decision learned exactly once."""

from __future__ import annotations

import asyncio
import logging
import time

import fakeredis
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from redis.asyncio.client import Pipeline

from qbrixstore.clickhouse.ledger import LedgerDecision
from qbrixstore.clickhouse.ledger import LedgerOutcome
from qbrixstore.clickhouse.ledger import OutcomeRef
from qbrixstore.clickhouse.ledger import SealedDecision
from qbrixstore.redis.client import RedisClient
from qbrixstore.stream import topology

from cortexsvc import sealer as sealer_module
from cortexsvc.sealer import Sealer

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

TENANT = "t1"
CYCLE = "cyc-1"
WINDOW = 60_000


class FakeLedger:
    """the clickhouse client's ledger calls over lists, with
    sealed_decisions replacing a row by its key as a merge would."""

    def __init__(self) -> None:
        self.decisions: list[LedgerDecision] = []
        self.outcomes: list[tuple[LedgerOutcome, OutcomeRef]] = []
        self.sealed: dict[tuple[str, str, str], SealedDecision] = {}
        self.inserted_rows = 0
        self.client = object()
        self.fail_insert = 0

    def connect(self, create_database: bool = True) -> None:
        pass

    def close(self) -> None:
        pass

    def first_decision_ms(self) -> int | None:
        return min((d.opened_ms for d in self.decisions), default=None)

    def query_window_seals(self, start_ms: int, end_ms: int) -> list[LedgerDecision]:
        return [
            d
            for d in self.decisions
            if start_ms <= max(d.closes_ms, d.ledger_ms) < end_ms
        ]

    def query_arrived_outcomes(self, start_ms: int, end_ms: int) -> list[OutcomeRef]:
        return list(
            {ref for o, ref in self.outcomes if start_ms <= o.ledger_ms < end_ms}
        )

    def query_decisions(self, refs) -> list[LedgerDecision]:
        wanted = {ref.decision_id for ref in refs}
        return [d for d in self.decisions if d.decision_id in wanted]

    def query_outcomes(self, decisions, until_ms: int) -> list[LedgerOutcome]:
        wanted = {d.decision_id for d in decisions}
        return [
            o
            for o, _ in self.outcomes
            if o.decision_id in wanted and o.ledger_ms < until_ms
        ]

    def insert_sealed_decisions(self, sealed) -> None:
        if self.fail_insert:
            self.fail_insert -= 1
            raise ConnectionError("clickhouse went away")
        for row in sealed:
            self.sealed[(row.tenant_id, row.cycle_id, row.decision_id)] = row
        self.inserted_rows += len(sealed)

    def decide(
        self, decision_id: str, option_index: int, opened_ms: int, metric_type: str
    ) -> LedgerDecision:
        decision = LedgerDecision(
            tenant_id=TENANT,
            loop_id="loop-1",
            cycle_id=CYCLE,
            decision_id=decision_id,
            option_index=option_index,
            unit=f"user-{decision_id}",
            metric_id="m-1",
            metric_version="1.0",
            metric_type=metric_type,
            opened_ms=opened_ms,
            window_ms=WINDOW,
            ledger_ms=opened_ms,
        )
        self.decisions.append(decision)
        return decision

    def answer(self, decision: LedgerDecision, value: float, ledger_ms: int, **kw):
        self.outcomes.append(
            (
                LedgerOutcome(
                    tenant_id=TENANT,
                    decision_id=decision.decision_id,
                    event_id=kw.get(
                        "event_id", f"ev-{decision.decision_id}-{ledger_ms}"
                    ),
                    value=value,
                    at_ms=kw.get("at_ms", ledger_ms),
                    received_ms=ledger_ms,
                    ledger_ms=ledger_ms,
                ),
                OutcomeRef(TENANT, CYCLE, decision.decision_id, decision.opened_ms),
            )
        )


@pytest.fixture
def redis_server(monkeypatch) -> fakeredis.FakeServer:
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda *_a, **_k: FakeRedis(server=server, decode_responses=True),
    )
    return server


@pytest.fixture
def control(redis_server) -> FakeRedis:
    return FakeRedis(server=redis_server, decode_responses=True)


@pytest_asyncio.fixture
async def store(redis_server):
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
def ledger(monkeypatch) -> FakeLedger:
    monkeypatch.setattr(sealer_module, "create_tables", lambda client: None)
    return FakeLedger()


@pytest_asyncio.fixture
async def cycle(store):
    record = {
        "id": CYCLE,
        "policy": "BetaTSPolicy",
        "policy_params": {"alpha_prior": 1.0, "beta_prior": 1.0},
        "pool": {"arms": [{"index": 0}, {"index": 1}, {"index": 2}]},
        "enabled": True,
    }
    await store.set_experiment(TENANT, CYCLE, record)
    return record


@pytest.fixture
def sealer(store, ledger) -> Sealer:
    return Sealer(store, ledger, interval_sec=0.01, stall_sec=30)


def ago(seconds: float) -> int:
    return int(time.time() * 1000) - int(seconds * 1000)


async def seal_all(sealer: Sealer) -> None:
    await sealer._connect()
    while await sealer.run_once():
        pass


async def health(store) -> dict[str, int]:
    outcomes = await store.outcome_health(TENANT, CYCLE, window_minutes=5)
    return {"learned": outcomes.learned, **outcomes.by_reason}


async def params(store) -> dict:
    return (await store.read_learning(TENANT, CYCLE)).params


class TestAPass:
    async def test_conversions_seal_and_teach_their_option(
        self, sealer, ledger, store, cycle
    ):
        converted = ledger.decide("a", 1, ago(600), "conversion")
        ledger.decide("b", 2, ago(600), "conversion")
        ledger.answer(converted, 1, converted.opened_ms + 1_000)

        await seal_all(sealer)

        learned = await params(store)
        assert learned["alpha"] == [1.0, 2.0, 1.0]
        assert learned["beta"] == [1.0, 1.0, 2.0]
        assert {k[2]: row.value for k, row in ledger.sealed.items()} == {
            "a": 1.0,
            "b": 0.0,
        }
        learning = await store.read_learning(TENANT, CYCLE)
        assert learning.applied == 2
        assert (
            max(row.sealed_ms for row in ledger.sealed.values())
            < learning.sealed_up_to
            <= await store.sealer_mark()
        )

    async def test_outcomes_are_counted_per_cycle_by_reason(
        self, sealer, ledger, store, cycle
    ):
        decision = ledger.decide("a", 0, ago(600), "count")
        ledger.answer(decision, 2, decision.opened_ms + 1_000, event_id="e1")
        ledger.answer(decision, 2, decision.opened_ms + 2_000, event_id="e1")
        ledger.answer(
            decision, 1, decision.closes_ms + 1_000, at_ms=decision.closes_ms + 1
        )

        await seal_all(sealer)

        assert await health(store) == {"learned": 1, "duplicate": 1, "late": 1}

    async def test_a_paused_loop_keeps_learning(self, sealer, ledger, store, cycle):
        await store.set_experiment(TENANT, CYCLE, {**cycle, "enabled": False})
        decision = ledger.decide("a", 0, ago(600), "conversion")
        ledger.answer(decision, 1, decision.opened_ms + 1_000)

        await seal_all(sealer)

        assert (await params(store))["alpha"][0] == 2.0

    async def test_a_score_without_an_outcome_seals_and_teaches_nothing(
        self, sealer, ledger, store, cycle
    ):
        ledger.decide("a", 0, ago(600), "score")

        await seal_all(sealer)

        assert ledger.sealed[(TENANT, CYCLE, "a")].value is None
        assert (await store.read_learning(TENANT, CYCLE)).applied == 0

    async def test_nothing_in_the_ledger_is_nothing_to_do(self, sealer, store):
        await seal_all(sealer)

        assert await store.sealer_mark() is None

    async def test_an_open_decision_waits_for_its_window(
        self, sealer, ledger, store, cycle
    ):
        ledger.decide("a", 0, ago(10), "count")

        await seal_all(sealer)

        assert ledger.sealed == {}


class TestCompleteUpTo:
    async def test_sealing_waits_for_trace_and_resumes_without_loss(
        self, sealer, ledger, store, control, cycle, caplog
    ):
        decision = ledger.decide("a", 0, ago(600), "conversion")
        ledger.answer(decision, 1, decision.opened_ms + 1_000)
        stuck = decision.opened_ms - 1
        await control.xgroup_create(
            topology.SELECTION.name, "trace", id="0", mkstream=True
        )
        await control.xadd(topology.SELECTION.name, {"x": "1"}, id=f"{stuck}-0")

        with caplog.at_level(logging.ERROR):
            await seal_all(sealer)

        assert ledger.sealed == {}
        progress = await store.ledger_progress()
        assert progress.complete_up_to_ms == stuck
        assert progress.lag_ms > 30_000
        assert "the ledger is" in caplog.text

        await control.xreadgroup("trace", "t-0", {topology.SELECTION.name: ">"})
        await control.xack(topology.SELECTION.name, "trace", f"{stuck}-0")
        await seal_all(sealer)

        assert list(ledger.sealed) == [(TENANT, CYCLE, "a")]
        assert (await params(store))["alpha"][0] == 2.0

    async def test_a_pending_entry_holds_sealing_at_its_time(
        self, sealer, store, control
    ):
        await control.xgroup_create(topology.EVENT.name, "trace", id="0", mkstream=True)
        held = ago(120)
        await control.xadd(topology.EVENT.name, {"x": "1"}, id=f"{held}-0")
        await control.xreadgroup("trace", "t-0", {topology.EVENT.name: ">"})

        assert await sealer.complete_up_to() == held


class TestExactlyOnce:
    """applied always equals the number of sealed decisions with a value."""

    def three_decisions(self, ledger):
        for name, option in (("a", 0), ("b", 1), ("c", 2)):
            decision = ledger.decide(name, option, ago(600), "conversion")
            ledger.answer(decision, 1, decision.opened_ms + 1_000)

    async def test_a_crash_before_recording_repeats_the_pass(
        self, sealer, ledger, store, cycle
    ):
        self.three_decisions(ledger)
        ledger.fail_insert = 1

        await sealer._connect()
        with pytest.raises(ConnectionError):
            await sealer.run_once()
        await seal_all(sealer)

        assert (await store.read_learning(TENANT, CYCLE)).applied == 3
        assert (await params(store))["alpha"] == [2.0, 2.0, 2.0]

    async def test_a_crash_between_recording_and_learning_learns_once(
        self, sealer, ledger, store, cycle, monkeypatch
    ):
        self.three_decisions(ledger)
        execute = Pipeline.execute

        async def crash(self, *args, **kwargs):
            raise ConnectionError("cortex lost redis at exec")

        monkeypatch.setattr(Pipeline, "execute", crash)
        await sealer._connect()
        with pytest.raises(ConnectionError):
            await sealer.run_once()
        monkeypatch.setattr(Pipeline, "execute", execute)

        assert len(ledger.sealed) == 3
        assert await store.sealer_mark() is None

        await seal_all(sealer)

        assert (await store.read_learning(TENANT, CYCLE)).applied == 3
        assert len(ledger.sealed) == 3
        assert ledger.inserted_rows == 6

    async def test_a_crash_after_learning_before_the_mark_learns_once(
        self, sealer, ledger, store, cycle, monkeypatch
    ):
        self.three_decisions(ledger)

        async def crash(sealed_up_to):
            raise ConnectionError("cortex died before moving the mark")

        monkeypatch.setattr(store, "set_sealer_mark", crash)
        await sealer._connect()
        with pytest.raises(ConnectionError):
            await sealer.run_once()
        monkeypatch.undo()

        assert (await store.read_learning(TENANT, CYCLE)).applied == 3

        more = ledger.decide("d", 0, ago(500), "conversion")
        ledger.answer(more, 1, more.opened_ms + 1_000)
        await seal_all(sealer)

        learning = await store.read_learning(TENANT, CYCLE)
        assert learning.applied == 4
        assert (await params(store))["alpha"] == [3.0, 2.0, 2.0]
        assert await health(store) == {"learned": 4}


class TestCycles:
    async def test_a_cycle_without_a_record_learns_nothing_and_does_not_block(
        self, sealer, ledger, store
    ):
        decision = ledger.decide("a", 0, ago(600), "conversion")
        ledger.answer(decision, 1, decision.opened_ms + 1_000)

        await seal_all(sealer)

        assert await store.sealer_mark() is not None
        assert (await store.read_learning(TENANT, CYCLE)).params is None

    async def test_a_policy_that_fails_to_train_counts_a_train_error(
        self, sealer, ledger, store, cycle, monkeypatch
    ):
        decision = ledger.decide("a", 0, ago(600), "conversion")
        ledger.answer(decision, 1, decision.opened_ms + 1_000)

        def broken(**kwargs):
            raise ValueError("bad state")

        monkeypatch.setattr(
            sealer_module.POLICY_MAP["BetaTSPolicy"], "train", staticmethod(broken)
        )
        await seal_all(sealer)

        assert await health(store) == {"learned": 0, "train_error": 1}
        assert await store.sealer_mark() is not None


class TestRunLoop:
    async def test_runs_in_the_background_and_stops(self, sealer, ledger, store, cycle):
        decision = ledger.decide("a", 0, ago(600), "conversion")
        ledger.answer(decision, 1, decision.opened_ms + 1_000)

        await sealer.start()
        for _ in range(100):
            if ledger.sealed:
                break
            await asyncio.sleep(0.01)
        await sealer.stop()

        assert (await params(store))["alpha"][0] == 2.0
