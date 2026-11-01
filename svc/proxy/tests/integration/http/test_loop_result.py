"""integration tests for a loop's results, a qbrix next surface.

invariants verified:
  a draft reads its calls by reason with no share and no lift. a live loop's
  share counts every decision once, in step-aligned columns picked from the
  ladder, and splits those that reached the ledger by complete up to into
  sealed and waiting. lift is absent until the cycle's first window closes,
  early until its 7 days are full, never reads the last window, and is the
  same for any engine. an ended cycle reads its whole-cycle lift and never
  mixes with the current one. health reads the cycle's counters and the
  ledger's lag. the list carries each loop's share and lift from a fixed
  number of ledger queries. a slow ledger never holds a decision.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest_asyncio

import proxysvc.config
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.session import get_session
from qbrixstore.redis import Learning
from qbrixstore.redis.health import LedgerProgress
from qbrixstore.redis.health import LoopSelectReason
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import SelectErrorReason
from qbrixstore.redis.health import SelectOutcome

from proxysvc.core.actor import Actor
from proxysvc.mod.loop.stat import DAY_MS
from proxysvc.mod.loop.stat import HOUR_MS
from proxysvc.mod.loop.stat import MINUTE_MS
from proxysvc.next import next_routes

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
ACTOR = Actor.member("user-ada")
WINDOW_MS = HOUR_MS

OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    """the client with the next routes mounted, and a one-hour conversion."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=WINDOW_MS // 1000,
        actor=ACTOR,
    )
    yield client
    app.router.routes[:] = routes


async def _loop(wired_app, *, launch: bool = True, **overrides) -> dict:
    loop = (
        await wired_app.svc.create_loop(
            TENANT,
            **{
                "name": "Checkout headline",
                "metric": "purchase",
                "options": OPTIONS,
                "actor": ACTOR,
                **overrides,
            },
        )
    ).value
    if launch:
        loop = (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)).value
    return loop


def _started_ms(loop: dict) -> int:
    started = datetime.fromisoformat(loop["cycle"]["started_at"])
    return int(
        started.replace(tzinfo=started.tzinfo or timezone.utc).timestamp() * 1000
    )


def _at(wired_app, now_ms: int) -> None:
    wired_app.svc._loop_result_service._clock = lambda: now_ms


async def _results(api, ref: str = "checkout-headline", **params) -> dict:
    resp = await api.get(f"/api/v1/loops/{ref}/results", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _converting(ledger, cycle_id: str, since_ms: int, splits, batch: str = "") -> None:
    """sealed decisions spread over the hour after since: for each option,
    (decisions, conversions)."""
    for index, (n, converted) in enumerate(splits):
        for i in range(n):
            decision_id = f"{cycle_id}-{batch}{index}-{i}"
            opened = since_ms + i * (HOUR_MS // max(n, 1))
            ledger.decide(cycle_id, decision_id, index, opened)
            ledger.seal(
                cycle_id, decision_id, index, opened, 1.0 if i < converted else 0.0
            )


class TestDraft:
    async def test_shows_its_calls_with_no_share_or_lift(self, wired_app, api):
        await _loop(wired_app, launch=False)
        for _ in range(3):
            resp = await api.post(
                "/api/v1/select",
                json={"loop": "checkout-headline", "context": {"unit": "u-1"}},
            )
            assert resp.json()["reason"] == "draft"

        results = await _results(api)

        assert results["cycle"] is None
        assert results["share"] is None
        assert results["lift"] is None
        assert results["calls"] == {"live": 0, "draft": 3, "paused": 0}
        assert wired_app.ledger.queries == []


class TestShare:
    async def test_counts_every_decision_once_across_options(self, wired_app, api):
        loop = await _loop(wired_app)
        cycle, start = loop["cycle"]["id"], _started_ms(loop)
        ledger = wired_app.ledger
        ledger.decide(cycle, "a", 0, start + 1_000)
        ledger.decide(cycle, "a", 0, start + 1_000)
        ledger.decide(cycle, "b", 1, start + 2_000)
        ledger.decide(cycle, "c", 1, start + 3_000)
        _at(wired_app, start + 30 * MINUTE_MS)

        share = (await _results(api))["share"]

        assert [(o["key"], o["decisions"]) for o in share["options"]] == [
            ("control", 1),
            ("urgency", 2),
        ]
        assert [o["share"] for o in share["options"]] == [1 / 3, 2 / 3]
        assert sum(sum(p["decisions"]) for p in share["series"]) == 3

    async def test_a_young_cycle_reads_by_the_minute(self, wired_app, api):
        loop = await _loop(wired_app)
        _at(wired_app, _started_ms(loop) + 30 * MINUTE_MS)

        share = (await _results(api))["share"]

        assert share["step_seconds"] == 60
        assert len(share["series"]) in (30, 31)

    async def test_a_day_reads_by_the_half_hour_and_a_week_by_six_hours(
        self, wired_app, api
    ):
        loop = await _loop(wired_app)
        _at(wired_app, _started_ms(loop) + 30 * DAY_MS)

        day = (await _results(api, range="24h"))["share"]
        week = (await _results(api, range="7d"))["share"]

        assert day["step_seconds"] == 30 * 60
        assert len(day["series"]) == 48
        assert week["step_seconds"] == 6 * 60 * 60
        assert len(week["series"]) <= 48

    async def test_the_cycle_range_reads_from_the_cycles_start(self, wired_app, api):
        loop = await _loop(wired_app)
        start = _started_ms(loop)
        ledger = wired_app.ledger
        ledger.decide(loop["cycle"]["id"], "first", 0, start + 1_000)
        _at(wired_app, start + 30 * DAY_MS)

        results = await _results(api, range="cycle")
        share = results["share"]

        assert results["range"] == "cycle"
        assert share["step_seconds"] == 24 * 60 * 60
        assert len(share["series"]) in (30, 31)
        assert share["options"][0]["decisions"] == 1

    async def test_a_young_cycles_range_reads_by_the_minute(self, wired_app, api):
        loop = await _loop(wired_app)
        _at(wired_app, _started_ms(loop) + 30 * MINUTE_MS)

        share = (await _results(api, range="cycle"))["share"]

        assert share["step_seconds"] == 60
        assert len(share["series"]) in (30, 31)

    async def test_waiting_and_sealed_add_up_to_complete_up_to(self, wired_app, api):
        loop = await _loop(wired_app)
        cycle, start = loop["cycle"]["id"], _started_ms(loop)
        ledger = wired_app.ledger
        ledger.decide(cycle, "sealed", 0, start + 1_000)
        ledger.seal(cycle, "sealed", 0, start + 1_000, 1.0)
        ledger.decide(cycle, "open", 0, start + 2_000)
        ledger.decide(cycle, "not-yet", 0, start + 3_000, ledger_ms=start + 9_000)
        await wired_app.svc._redis.set_ledger_progress(
            LedgerProgress(start + 5_000, lag_ms=4_000, checked_ms=start + 9_000)
        )
        _at(wired_app, start + 10_000)

        results = await _results(api)
        control = results["share"]["options"][0]

        assert control["decisions"] == 3
        assert (control["sealed"], control["waiting"]) == (1, 1)
        assert results["health"]["ledger_lag_ms"] == 4_000

    async def test_another_workspaces_loop_is_not_found(self, wired_app, api):
        await _loop(wired_app)

        with as_tenant(wired_app.app, tenant_id="other-tenant"):
            resp = await api.get("/api/v1/loops/checkout-headline/results")

        assert resp.status_code == 404
        assert resp.json()["code"] == "LOOP_NOT_FOUND"

    async def test_a_viewer_reads_results(self, wired_app, api):
        await _loop(wired_app)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await api.get("/api/v1/loops/checkout-headline/results")

        assert resp.status_code == 200

    async def test_an_unknown_range_is_refused(self, wired_app, api):
        await _loop(wired_app)

        resp = await api.get(
            "/api/v1/loops/checkout-headline/results", params={"range": "1y"}
        )

        assert resp.status_code == 422


class TestLift:
    async def test_none_before_the_first_window_closes(self, wired_app, api):
        loop = await _loop(wired_app)
        _at(wired_app, _started_ms(loop) + WINDOW_MS - 1)

        assert (await _results(api))["lift"] is None

    async def test_the_worked_example_while_early(self, wired_app, api):
        loop = await _loop(wired_app)
        cycle, start = loop["cycle"]["id"], _started_ms(loop)
        _converting(wired_app.ledger, cycle, start, [(100, 10), (300, 60)])
        _at(wired_app, start + 2 * HOUR_MS + WINDOW_MS)

        lift = (await _results(api))["lift"]

        assert lift["early"] is True
        assert round(lift["value"] * 100, 1) == 16.7
        assert [(o["key"], o["sealed"], o["mean"]) for o in lift["options"]] == [
            ("control", 100, 0.1),
            ("urgency", 300, 0.2),
        ]

    async def test_a_thin_option_reads_wider(self, wired_app, api):
        loop = await _loop(wired_app)
        cycle, start = loop["cycle"]["id"], _started_ms(loop)
        _converting(wired_app.ledger, cycle, start, [(20, 4), (2_000, 400)])
        _at(wired_app, start + 2 * HOUR_MS + WINDOW_MS)

        thin, thick = (await _results(api))["lift"]["options"]

        assert thin["high"] - thin["low"] > 5 * (thick["high"] - thick["low"])

    async def test_ignores_decisions_inside_the_last_window(self, wired_app, api):
        loop = await _loop(wired_app)
        cycle, start = loop["cycle"]["id"], _started_ms(loop)
        _converting(wired_app.ledger, cycle, start, [(100, 10), (100, 10)])
        now = start + 3 * HOUR_MS
        wired_app.ledger.decide(cycle, "quick", 0, now - 10 * MINUTE_MS)
        wired_app.ledger.seal(cycle, "quick", 0, now - 10 * MINUTE_MS, 1.0)
        _at(wired_app, now)

        lift = (await _results(api))["lift"]

        assert lift["options"][0]["sealed"] == 100
        assert lift["value"] == 0

    async def test_no_longer_early_once_its_seven_days_are_full(self, wired_app, api):
        loop = await _loop(wired_app)
        start = _started_ms(loop)
        _at(wired_app, start + 7 * DAY_MS + WINDOW_MS)

        lift = (await _results(api))["lift"]

        assert lift["early"] is False
        assert lift["value"] is None

    async def test_reads_the_same_for_any_engine(self, wired_app, api):
        spinoza = await _loop(wired_app)
        buridan = await _loop(wired_app, name="Checkout even", engine="buridan")
        start = max(_started_ms(spinoza), _started_ms(buridan))
        for loop in (spinoza, buridan):
            _converting(
                wired_app.ledger, loop["cycle"]["id"], start, [(50, 5), (50, 9)]
            )
        _at(wired_app, start + 2 * HOUR_MS + WINDOW_MS)

        one = await _results(api, spinoza["key"])
        two = await _results(api, buridan["key"])

        assert one["share"]["options"] == two["share"]["options"]
        assert one["lift"]["value"] == two["lift"]["value"]
        assert one["lift"]["options"] == two["lift"]["options"]


class TestCycles:
    async def _second_cycle(self, loop: dict, ended_ms: int) -> str:
        async with get_session() as session:
            first = await session.get(Cycle, loop["cycle"]["id"])
            first.ended_at = datetime.fromtimestamp(ended_ms / 1000, tz=timezone.utc)
            second = Cycle(
                loop_id=first.loop_id,
                number=2,
                engine=first.engine,
                engine_version=first.engine_version,
                metric_version_id=first.metric_version_id,
                options=first.options,
                started_at=first.ended_at + timedelta(milliseconds=1),
            )
            session.add(second)
            await session.flush()
            return second.id

    async def test_an_ended_cycle_reads_its_whole_lift_apart(self, wired_app, api):
        loop = await _loop(wired_app)
        first, start = loop["cycle"]["id"], _started_ms(loop)
        ended = start + 10 * DAY_MS
        second = await self._second_cycle(loop, ended)
        _converting(wired_app.ledger, first, start, [(100, 10), (300, 60)])
        _converting(
            wired_app.ledger,
            first,
            ended - 2 * HOUR_MS,
            [(100, 10), (300, 60)],
            batch="late-",
        )
        _converting(wired_app.ledger, second, ended + HOUR_MS, [(100, 50), (100, 50)])
        _at(wired_app, ended + 3 * HOUR_MS)

        earlier = await _results(api, cycle=1)
        current = await _results(api)

        assert earlier["cycle"]["id"] == first
        assert earlier["lift"]["early"] is False
        assert [o["sealed"] for o in earlier["lift"]["options"]] == [200, 600]
        assert round(earlier["lift"]["value"] * 100, 1) == 16.7
        assert current["cycle"]["id"] == second
        assert [o["sealed"] for o in current["lift"]["options"]] == [100, 100]
        assert current["lift"]["value"] == 0

    async def test_an_unknown_cycle_is_not_found(self, wired_app, api):
        await _loop(wired_app)

        resp = await api.get(
            "/api/v1/loops/checkout-headline/results", params={"cycle": 9}
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "CYCLE_NOT_FOUND"


class TestHealth:
    async def test_reads_the_cycles_counters(self, wired_app, api):
        loop = await _loop(wired_app)
        cycle = loop["cycle"]["id"]
        redis = wired_app.svc._redis
        await redis.record_select(
            TENANT, cycle, SelectOutcome.ERROR, SelectErrorReason.MOTOR_TIMEOUT
        )
        await redis.record_select(TENANT, cycle, SelectOutcome.OK)
        pipe = redis.client.pipeline()
        redis.stage_outcomes(
            pipe,
            TENANT,
            cycle,
            {
                OutcomeDisposition.LEARNED: 5,
                OutcomeDisposition.LATE: 2,
                OutcomeDisposition.DUPLICATE: 1,
            },
            last_arrival_ms=1_767_225_600_000,
        )
        await pipe.execute()

        health = (await _results(api))["health"]

        assert health == {
            "decision_errors": 1,
            "outcomes": {"learned": 5, "late": 2, "duplicate": 1, "earlier_cycle": 0},
            "last_outcome_at": "2026-01-01T00:00:00+00:00",
            "last_learned_at": None,
            "ledger_lag_ms": None,
        }

    async def test_the_rate_reads_recent_decisions_not_the_hour(self, wired_app, api):
        loop = await _loop(wired_app)
        now = _started_ms(loop) + DAY_MS
        redis = wired_app.svc._redis
        for _ in range(600):
            await redis.record_loop_select(TENANT, loop["id"], LoopSelectReason.LIVE)
        for _ in range(60):
            await redis.record_loop_select(
                TENANT,
                loop["id"],
                LoopSelectReason.LIVE,
                minute=now // MINUTE_MS - 1,
            )
        _at(wired_app, now)

        results = await _results(api)

        assert results["calls"]["live"] == 600
        elapsed = 4 * 60 + (now % MINUTE_MS) / 1000
        assert results["decisions_per_second"] == 60 / elapsed

    async def test_a_young_cycles_rate_reads_only_what_it_has_run(self, wired_app, api):
        loop = await _loop(wired_app)
        now = _started_ms(loop) + 30_000
        for _ in range(30):
            await wired_app.svc._redis.record_loop_select(
                TENANT, loop["id"], LoopSelectReason.LIVE, minute=now // MINUTE_MS
            )
        _at(wired_app, now)

        assert (await _results(api))["decisions_per_second"] == 1.0

    async def test_reads_when_the_cycle_last_learned(self, wired_app, api):
        loop = await _loop(wired_app)
        await wired_app.svc._redis.restore_learning(
            TENANT,
            loop["cycle"]["id"],
            Learning(params={}, sealed_up_to=1_767_225_600_000),
        )

        health = (await _results(api))["health"]

        assert health["last_learned_at"] == "2026-01-01T00:00:00+00:00"


class TestReading:
    async def test_a_poll_within_seconds_reads_the_ledger_once(self, wired_app, api):
        await _loop(wired_app)

        await _results(api)
        await _results(api)

        assert len(wired_app.ledger.queries) == 3

    async def test_a_slow_ledger_never_holds_a_decision(self, wired_app, api):
        await _loop(wired_app)
        wired_app.motor_mock.select.return_value = {
            "arm": {"id": "ignored", "name": "ignored", "index": 0},
            "policy": "BetaTSPolicy",
        }
        wired_app.ledger.delay = 1.0

        async def decide() -> float:
            await asyncio.sleep(0.1)
            resp = await api.post(
                "/api/v1/select",
                json={"loop": "checkout-headline", "context": {"unit": "u-1"}},
            )
            assert resp.status_code == 200, resp.text
            return time.perf_counter() - began

        began = time.perf_counter()
        _, decided = await asyncio.gather(_results(api), decide())

        assert decided < 0.5


class TestList:
    async def test_carries_share_and_lift_from_two_queries_per_page(
        self, wired_app, api
    ):
        await _loop(wired_app, launch=False, name="Draft")
        loops = [await _loop(wired_app, name=f"Live {n}") for n in range(3)]
        start = max(_started_ms(loop) for loop in loops)
        _converting(
            wired_app.ledger, loops[0]["cycle"]["id"], start, [(100, 10), (300, 60)]
        )
        _at(wired_app, start + 2 * HOUR_MS + WINDOW_MS)

        resp = await api.get("/api/v1/loops")
        page = {item["key"]: item["results"] for item in resp.json()["loops"]}

        assert page["draft"] is None
        assert page["live-0"]["share"] == [
            {"key": "control", "share": 0.25},
            {"key": "urgency", "share": 0.75},
        ]
        assert round(page["live-0"]["lift"] * 100, 1) == 16.7
        assert page["live-0"]["early"] is True
        assert page["live-1"]["lift"] is None
        assert sorted(wired_app.ledger.queries) == ["decision_counts", "sealed_stats"]
