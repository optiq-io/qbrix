"""a cycle's milestones from ledger time: when its first window seals, when an
option is named as leader, and that a storm, a restart or a catch-up changes
none of it."""

from __future__ import annotations

import fakeredis
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from qbrixstore.clickhouse.ledger import TrailingCount
from qbrixstore.event import MilestoneEvent
from qbrixstore.redis import MilestoneCycle
from qbrixstore.redis import MilestoneState
from qbrixstore.redis.client import RedisClient
from qbrixstore.stream import topology

from cortexsvc.milestone import CHECK_MS
from cortexsvc.milestone import HOLD_MS
from cortexsvc.milestone import MilestoneWatch
from cortexsvc.milestone import lead

pytestmark = pytest.mark.unit

CYCLE = MilestoneCycle("t1", "loop-1", "cyc-1")
START = CHECK_MS * 1_000
WINDOW = CHECK_MS * 2


class FakeLedger:
    """answers by the check it is read at: counts[check] is that check's
    decisions per option."""

    def __init__(self) -> None:
        self.counts: dict[int, dict[int, int]] = {}
        self.fail = False

    def trailing_decisions(self, start_ms: int, end_ms: int) -> list[TrailingCount]:
        if self.fail:
            raise ConnectionError("clickhouse went away")
        return [
            TrailingCount(*_names(), option, decisions, START, WINDOW)
            for option, decisions in self.counts.get(end_ms, {}).items()
        ]


def _names() -> tuple[str, str, str]:
    return CYCLE.tenant_id, CYCLE.loop_id, CYCLE.cycle_id


@pytest_asyncio.fixture
async def store(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda *_a, **_k: FakeRedis(server=server, decode_responses=True),
    )
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
def ledger() -> FakeLedger:
    return FakeLedger()


@pytest.fixture
def watch(store, ledger) -> MilestoneWatch:
    return MilestoneWatch(store, ledger)


def checks(first: int, count: int) -> list[int]:
    return [START + CHECK_MS * (first + i) for i in range(count)]


async def run(watch: MilestoneWatch, *at: int) -> None:
    for check_ms in at:
        await watch.check(check_ms - 60_000, check_ms + 1)


async def events(store) -> list[MilestoneEvent]:
    entries = await store.client.xrange(topology.MILESTONE.name)
    return [MilestoneEvent.from_dict(fields) for _, fields in entries]


class TestLead:
    def test_a_new_option_is_not_named_before_the_hold(self):
        state = MilestoneState(first_seal=True, candidate=0, since_ms=0, seen_ms=0)
        state, change = lead(state, {1: 9, 0: 1}, CHECK_MS)

        assert state.candidate == 1
        assert state.since_ms == CHECK_MS
        assert change is None

    def test_it_is_named_after_leading_at_every_check_for_the_hold(self):
        state = MilestoneState()
        change = None
        for at in range(CHECK_MS, CHECK_MS + HOLD_MS + 1, CHECK_MS):
            state, change = lead(state, {1: 9, 0: 1}, at)

        assert change == {"from": None, "to": 1}
        assert state.leader == 1

    def test_a_tie_keeps_the_option_leading(self):
        state = MilestoneState(candidate=1, since_ms=0, seen_ms=0)
        state, _ = lead(state, {0: 5, 1: 5}, CHECK_MS)

        assert state.candidate == 1
        assert state.since_ms == 0

    def test_a_gap_in_checks_restarts_the_hold(self):
        state = MilestoneState(candidate=1, since_ms=0, seen_ms=0)
        state, change = lead(state, {1: 9}, HOLD_MS * 2)

        assert change is None
        assert state.since_ms == HOLD_MS * 2

    def test_the_named_leader_is_not_named_again(self):
        state = MilestoneState(candidate=1, since_ms=0, seen_ms=HOLD_MS, leader=1)
        state, change = lead(state, {1: 9}, HOLD_MS + CHECK_MS)

        assert change is None
        assert state.leader == 1


class TestFirstSeal:
    async def test_it_waits_for_the_window_then_fires_once(self, watch, store, ledger):
        at = checks(0, 5)
        ledger.counts = {check: {0: 3} for check in at}

        await run(watch, at[0], at[1])
        assert await events(store) == []

        await run(watch, *at[2:])
        found = await events(store)
        assert [e.kind for e in found] == ["loop.first_seal"]
        assert found[0].at_ms == START + WINDOW
        assert found[0].event_id == "first_seal:cyc-1"

    async def test_it_fires_for_a_cycle_whose_traffic_stopped(
        self, watch, store, ledger
    ):
        at = checks(0, 3)
        ledger.counts = {at[0]: {0: 3}}

        await run(watch, *at)

        assert [e.kind for e in await events(store)] == ["loop.first_seal"]


class TestLeader:
    async def test_a_storm_before_the_first_seal_names_no_one(
        self, watch, store, ledger
    ):
        at = checks(0, 2)
        for i, check in enumerate(at):
            ledger.counts[check] = {i % 2: 9, 1 - i % 2: 1}

        await run(watch, *at)

        assert await events(store) == []

    async def test_options_trading_places_never_emit(self, watch, store, ledger):
        at = checks(0, 40)
        for i, check in enumerate(at):
            ledger.counts[check] = {i % 2: 9, 1 - i % 2: 1}

        await run(watch, *at)

        assert [e.kind for e in await events(store)] == ["loop.first_seal"]

    async def test_a_held_lead_names_the_leader_with_no_from(
        self, watch, store, ledger
    ):
        at = checks(0, 20)
        ledger.counts = {check: {1: 9, 0: 1} for check in at}

        await run(watch, *at)

        leaders = [e for e in await events(store) if e.kind == "loop.leader_changed"]
        assert len(leaders) == 1
        assert leaders[0].payload == {"from": None, "to": 1}

    async def test_a_new_leader_names_where_the_lead_came_from(
        self, watch, store, ledger
    ):
        first = checks(0, 20)
        second = checks(20, 20)
        ledger.counts = {check: {1: 9, 0: 1} for check in first}
        ledger.counts |= {check: {0: 9, 1: 1} for check in second}

        await run(watch, *first, *second)

        leaders = [e for e in await events(store) if e.kind == "loop.leader_changed"]
        assert [e.payload for e in leaders] == [
            {"from": None, "to": 1},
            {"from": 1, "to": 0},
        ]

    async def test_a_lead_lost_inside_the_hour_names_no_one(self, watch, store, ledger):
        first = checks(0, 20)
        ledger.counts = {check: {1: 9, 0: 1} for check in first}
        await run(watch, *first)
        before = len(await events(store))

        brief = checks(20, 6)
        back = checks(26, 20)
        ledger.counts = {check: {0: 9, 1: 1} for check in brief}
        ledger.counts |= {check: {1: 9, 0: 1} for check in back}
        await run(watch, *brief, *back)

        assert len(await events(store)) == before


class TestRepeats:
    async def test_a_restart_mid_hold_keeps_the_hold(self, store, ledger):
        at = checks(0, 20)
        ledger.counts = {check: {1: 9, 0: 1} for check in at}

        await run(MilestoneWatch(store, ledger), *at[:10])
        await run(MilestoneWatch(store, ledger), *at[10:])

        kinds = [e.kind for e in await events(store)]
        assert kinds == ["loop.first_seal", "loop.leader_changed"]

    async def test_a_repeated_pass_changes_nothing(self, watch, store, ledger):
        at = checks(0, 20)
        ledger.counts = {check: {1: 9, 0: 1} for check in at}

        for check in at:
            await run(watch, check, check)

        kinds = [e.kind for e in await events(store)]
        assert kinds == ["loop.first_seal", "loop.leader_changed"]

    async def test_a_slice_crossing_no_boundary_reads_nothing(self, watch, ledger):
        ledger.fail = True

        await watch.check(START + 1_000, START + 60_000)

    async def test_where_a_slice_ends_does_not_change_the_events(self, store, ledger):
        at = checks(0, 20)
        ledger.counts = {check: {1: 9, 0: 1} for check in at}
        watch = MilestoneWatch(store, ledger)

        for check in at:
            await watch.check(check - 7, check + 53_000)

        found = await events(store)
        assert [e.at_ms for e in found if e.kind == "loop.leader_changed"] == [
            at[0] + CHECK_MS * 2 + HOLD_MS
        ]
