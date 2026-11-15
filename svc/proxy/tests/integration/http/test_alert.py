"""integration tests for alerts, a qbrix next surface.

invariants verified:
  a deciding loop whose outcomes stopped opens one outcomes_stopped warning,
  read from what the proxy received, so a stalled ledger never opens it; it
  resolves as cleared once the signal has stayed clear for 10 minutes, and
  no second one opens meanwhile. outcomes not learned opens above 10% of
  100 outcomes and waits while the ledger is behind. a person's pause opens
  nothing and leaves an open warning open; a resume restarts the clock.
  warnings change nothing and write no change. a safety pause opens one
  decision_errors alert in the pause's transaction; resuming resolves it as
  resumed and retiring as retired, both naming who. GET /api/v1/alerts and a
  loop's health read the one record, scoped to the workspace.
"""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update

import proxysvc.config
from qbrixstore.postgres.models import Alert
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.health import LedgerProgress
from qbrixstore.redis.health import LoopSelectReason
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import SelectOutcome

from proxysvc.core.actor import Actor
from proxysvc.mod.safety.alert import AlertPass
from proxysvc.mod.safety.repository import AlertRepository
from proxysvc.mod.safety.rule import DECISION_ERRORS
from proxysvc.mod.safety.rule import OUTCOMES_NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED
from proxysvc.mod.safety.service import AlertService
from proxysvc.mod.safety.watch import SafetyWatch
from svc.proxy.tests.integration.http.conftest import as_tenant
from proxysvc.next import next_routes

TENANT = "dev-tenant"
ADA = Actor.member("user-ada")
WINDOW_SEC = 60 * 60
WINDOW_MS = WINDOW_SEC * 1000
EVIDENCE = {"signal": DECISION_ERRORS, "rate": 0.07, "errors": 7, "calls": 100}

OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=WINDOW_SEC,
        actor=ADA,
    )
    yield client
    app.router.routes[:] = routes


@pytest.fixture
def now() -> float:
    return time.time()


async def _loop(wired_app, *, live_minutes: float = 120) -> dict:
    loop = (
        await wired_app.svc.create_loop(
            TENANT,
            name="Checkout headline",
            metric="purchase",
            options=OPTIONS,
            actor=ADA,
        )
    ).value
    loop = (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ADA)).value
    await _serving_since(loop["id"], minutes_ago=live_minutes)
    return loop


async def _serving_since(loop_id: str, *, minutes_ago: float) -> None:
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    async with get_session() as session:
        await session.execute(
            update(Loop).where(Loop.id == loop_id).values(live_since=when)
        )
        await session.execute(
            update(Cycle).where(Cycle.loop_id == loop_id).values(started_at=when)
        )


async def _decide(wired_app, loop: dict, n: int, now: float) -> None:
    redis = wired_app.svc.redis
    for _ in range(n):
        await redis.record_select(
            TENANT, loop["cycle"]["id"], SelectOutcome.OK, window_ms=WINDOW_MS
        )
    await redis.record_loop_select(
        TENANT, loop["id"], LoopSelectReason.LIVE, minute=int(now) // 60
    )


async def _received(wired_app, loop: dict, now: float) -> None:
    await wired_app.svc.redis.record_intake(
        TENANT, loop["cycle"]["id"], WINDOW_MS, int(now * 1000)
    )


async def _alerts(signal: str | None = None) -> list[Alert]:
    async with get_session() as session:
        stmt = select(Alert).order_by(Alert.opened_at)
        if signal is not None:
            stmt = stmt.where(Alert.signal == signal)
        return list((await session.execute(stmt)).scalars().all())


async def _changes(loop_id: str) -> int:
    async with get_session() as session:
        return await session.scalar(
            select(func.count()).select_from(Change).where(Change.target_id == loop_id)
        )


def _pass(wired_app) -> AlertPass:
    return AlertPass(wired_app.svc.redis)


class TestOutcomesStopped:
    async def test_a_silent_window_opens_one_warning_and_no_change(
        self, api, wired_app, now
    ):
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        changes = await _changes(loop["id"])

        await _pass(wired_app).run_once(now)
        await _pass(wired_app).run_once(now + 60)

        (alert,) = await _alerts()
        assert alert.signal == OUTCOMES_STOPPED
        assert alert.loop_id == loop["id"]
        assert alert.cycle_id == loop["cycle"]["id"]
        assert alert.evidence["decisions_since_outcome"] == 150
        assert alert.evidence["last_outcome_at"] is None
        assert await _changes(loop["id"]) == changes
        reloaded = await wired_app.svc.get_loop(TENANT, loop["key"])
        assert reloaded["state"] == "live"

    async def test_too_few_decisions_or_too_little_time_opens_nothing(
        self, api, wired_app, now
    ):
        loop = await _loop(wired_app, live_minutes=30)
        await _decide(wired_app, loop, 150, now)
        other = (
            await wired_app.svc.create_loop(
                TENANT, name="Banner", metric="purchase", options=OPTIONS, actor=ADA
            )
        ).value
        other = (await wired_app.svc.launch_loop(TENANT, other["key"], actor=ADA)).value
        await _serving_since(other["id"], minutes_ago=120)
        await _decide(wired_app, other, 99, now)

        await _pass(wired_app).run_once(now)

        assert await _alerts() == []

    async def test_an_outcome_resolves_it_after_the_hold(self, api, wired_app, now):
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        await _pass(wired_app).run_once(now)
        await _received(wired_app, loop, now + 60)

        await _pass(wired_app).run_once(now + 60)
        (alert,) = await _alerts()
        assert alert.resolved_at is None and alert.clear_since is not None

        await _pass(wired_app).run_once(now + 60 + 9 * 60)
        (alert,) = await _alerts()
        assert alert.resolved_at is None

        await _pass(wired_app).run_once(now + 60 + 10 * 60)
        (alert,) = await _alerts()
        assert alert.resolution == "cleared"
        assert alert.resolved_kind == "qbrix"

    async def test_the_signal_returning_during_the_hold_keeps_it_open(
        self, api, wired_app, now
    ):
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        await _pass(wired_app).run_once(now)
        await _received(wired_app, loop, now)
        await _pass(wired_app).run_once(now + 60)

        await _decide(wired_app, loop, 150, now + 70 * 60)
        await _pass(wired_app).run_once(now + 70 * 60)
        await _pass(wired_app).run_once(now + 90 * 60)

        (alert,) = await _alerts()
        assert alert.resolved_at is None and alert.clear_since is None

    async def test_a_paused_loop_opens_nothing_and_keeps_an_open_warning(
        self, api, wired_app, now
    ):
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        await _pass(wired_app).run_once(now)
        await wired_app.svc.loops.pause_loop(TENANT, loop["key"], actor=ADA)

        await _pass(wired_app).run_once(now + 30 * 60)

        (alert,) = await _alerts()
        assert alert.resolved_at is None and alert.clear_since is None

    async def test_a_resume_restarts_the_clock(self, api, wired_app, now):
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        await wired_app.svc.loops.pause_loop(TENANT, loop["key"], actor=ADA)
        await wired_app.svc.loops.resume_loop(TENANT, loop["key"], actor=ADA)

        await _pass(wired_app).run_once(now)

        assert await _alerts() == []

    async def test_a_committed_loop_is_watched_too(self, api, wired_app, now):
        loop = await _loop(wired_app)
        await wired_app.svc.loops.commit_loop(
            TENANT, loop["key"], option="control", actor=ADA
        )
        await _decide(wired_app, loop, 150, now)

        await _pass(wired_app).run_once(now)

        (alert,) = await _alerts()
        assert alert.signal == OUTCOMES_STOPPED

    async def test_the_safety_watch_runs_the_pass_once_a_minute(
        self, api, wired_app, now
    ):
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        alerts = _pass(wired_app)
        alerts.run_once = AsyncMock(wraps=alerts.run_once)
        watch = SafetyWatch(
            wired_app.svc.redis, wired_app.svc.loops, interval_sec=30, alerts=alerts
        )

        minute = (int(now) // 60) * 60
        await watch.run_once(minute + 1)
        await watch.run_once(minute + 31)
        await watch.run_once(minute + 61)

        assert alerts.run_once.await_count == 2
        assert len(await _alerts()) == 1


class TestOutcomesNotLearned:
    async def _late(self, wired_app, loop, now, *, learned: int, late: int):
        await _received(wired_app, loop, now)
        await wired_app.svc.redis.count_outcomes(
            TENANT,
            loop["cycle"]["id"],
            {OutcomeDisposition.LEARNED: learned, OutcomeDisposition.LATE: late},
            minute=int(now) // 60,
        )

    async def _ledger(self, wired_app, now, lag_ms: int) -> None:
        now_ms = int(now * 1000)
        await wired_app.svc.redis.set_ledger_progress(
            LedgerProgress(now_ms - lag_ms, lag_ms=lag_ms, checked_ms=now_ms)
        )

    async def test_above_a_tenth_opens_one_warning(self, api, wired_app, now):
        loop = await _loop(wired_app)
        await self._late(wired_app, loop, now, learned=85, late=15)
        await self._ledger(wired_app, now, 1_000)

        await _pass(wired_app).run_once(now)

        (alert,) = await _alerts(OUTCOMES_NOT_LEARNED)
        assert alert.evidence["rate"] == 0.15
        assert alert.evidence["reasons"] == {"late": 15}

    async def test_a_stale_ledger_holds_it_back(self, api, wired_app, now):
        loop = await _loop(wired_app)
        await self._late(wired_app, loop, now, learned=50, late=50)
        await self._ledger(wired_app, now, 6 * 60 * 1000)

        await _pass(wired_app).run_once(now)

        assert await _alerts(OUTCOMES_NOT_LEARNED) == []


class TestStalledLedger:
    async def test_outcomes_still_arriving_at_the_proxy_open_nothing(
        self, api, wired_app, now
    ):
        loop = await _loop(wired_app)
        for minute in range(0, 120, 10):
            await _decide(wired_app, loop, 20, now)
            await _received(wired_app, loop, now - (120 - minute) * 60)
        await _decide(wired_app, loop, 20, now)

        await _pass(wired_app).run_once(now)

        assert await _alerts() == []


class TestSafetyPause:
    async def test_a_safety_pause_opens_one_alert_with_its_evidence(
        self, api, wired_app
    ):
        loop = await _loop(wired_app)

        await wired_app.svc.loops.pause_loop(
            TENANT,
            loop["key"],
            actor=Actor.qbrix(),
            reason="decision errors",
            evidence=EVIDENCE,
        )

        (alert,) = await _alerts()
        assert alert.signal == DECISION_ERRORS
        assert alert.evidence == EVIDENCE
        assert alert.cycle_id == loop["cycle"]["id"]

    async def test_a_persons_pause_opens_none(self, api, wired_app):
        loop = await _loop(wired_app)

        await wired_app.svc.loops.pause_loop(TENANT, loop["key"], actor=ADA)

        assert await _alerts() == []

    async def test_resuming_resolves_it_naming_who(self, api, wired_app):
        loop = await _loop(wired_app)
        await wired_app.svc.loops.pause_loop(
            TENANT, loop["key"], actor=Actor.qbrix(), evidence=EVIDENCE
        )

        await wired_app.svc.loops.resume_loop(TENANT, loop["key"], actor=ADA)

        (alert,) = await _alerts()
        assert alert.resolution == "resumed"
        assert (alert.resolved_kind, alert.resolved_user_id) == ("member", "user-ada")

    async def test_retiring_a_paused_loop_resolves_every_open_alert(
        self, api, wired_app, now
    ):
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        await _pass(wired_app).run_once(now)
        await wired_app.svc.loops.pause_loop(
            TENANT, loop["key"], actor=Actor.qbrix(), evidence=EVIDENCE
        )

        await wired_app.svc.loops.retire_loop(TENANT, loop["key"], actor=ADA)

        alerts = await _alerts()
        assert {a.signal for a in alerts} == {OUTCOMES_STOPPED, DECISION_ERRORS}
        assert {a.resolution for a in alerts} == {"retired"}

    async def test_a_race_to_open_leaves_one_alert_and_the_transaction(
        self, api, wired_app, monkeypatch
    ):
        loop = await _loop(wired_app)
        async with get_session() as session:
            first = await AlertService(session, TENANT).open(
                loop["id"], OUTCOMES_STOPPED, {"signal": OUTCOMES_STOPPED}
            )

        found = AlertRepository.open_for
        blinded = []

        async def blind_once(self, loop_id, signal):
            if signal == OUTCOMES_STOPPED and not blinded:
                blinded.append(signal)
                return None
            return await found(self, loop_id, signal)

        monkeypatch.setattr(AlertRepository, "open_for", blind_once)
        async with get_session() as session:
            alerts = AlertService(session, TENANT)
            await alerts.open(loop["id"], DECISION_ERRORS, EVIDENCE)
            again = await alerts.open(
                loop["id"], OUTCOMES_STOPPED, {"signal": OUTCOMES_STOPPED}
            )

        assert again.id == first.id
        assert [a.signal for a in await _alerts()] == [
            OUTCOMES_STOPPED,
            DECISION_ERRORS,
        ]


class TestRead:
    async def _two(self, wired_app, now) -> dict:
        loop = await _loop(wired_app)
        await _decide(wired_app, loop, 150, now)
        await _pass(wired_app).run_once(now)
        await wired_app.svc.loops.pause_loop(
            TENANT, loop["key"], actor=Actor.qbrix(), evidence=EVIDENCE
        )
        await wired_app.svc.loops.resume_loop(TENANT, loop["key"], actor=ADA)
        return loop

    async def test_lists_newest_first_in_pieces(self, api, wired_app, now):
        loop = await self._two(wired_app, now)

        resp = await api.get("/api/v1/alerts")

        assert resp.status_code == 200, resp.text
        paused, stopped = resp.json()["alerts"]
        assert paused["signal"] == DECISION_ERRORS
        assert paused["resolution"] == "resumed"
        assert paused["resolved_by"]["kind"] == "member"
        assert paused["loop"] == {
            "id": loop["id"],
            "key": loop["key"],
            "name": "Checkout headline",
        }
        assert paused["pieces"] == [
            {"kind": "text", "text": "qbrix paused ", "name": None},
            {"kind": "loop", "text": None, "name": "Checkout headline"},
            {"kind": "text", "text": ": 7% of its decisions failed.", "name": None},
        ]
        assert stopped["signal"] == OUTCOMES_STOPPED
        assert stopped["resolved_at"] is None
        assert stopped["pieces"][1]["text"] == (
            " stopped receiving outcomes: none in its last 150 decisions."
        )

    async def test_filters_by_loop_and_open(self, api, wired_app, now):
        loop = await self._two(wired_app, now)

        opened = await api.get("/api/v1/alerts", params={"open": "true"})
        ended = await api.get(
            "/api/v1/alerts", params={"open": "false", "loop": loop["key"]}
        )
        missing = await api.get("/api/v1/alerts", params={"loop": "no-such-loop"})

        assert [a["signal"] for a in opened.json()["alerts"]] == [OUTCOMES_STOPPED]
        assert [a["signal"] for a in ended.json()["alerts"]] == [DECISION_ERRORS]
        assert missing.status_code == 404

    async def test_another_workspace_sees_none(self, api, wired_app, now):
        await self._two(wired_app, now)

        with as_tenant(wired_app.app, "other-tenant"):
            resp = await api.get("/api/v1/alerts")

        assert resp.json() == {"alerts": []}

    async def test_a_loops_health_carries_its_open_alerts(self, api, wired_app, now):
        loop = await self._two(wired_app, now)

        resp = await api.get(f"/api/v1/loops/{loop['key']}/results")

        assert resp.status_code == 200, resp.text
        (alert,) = resp.json()["health"]["alerts"]
        assert alert["signal"] == OUTCOMES_STOPPED


class TestSwitchedOff:
    async def test_the_route_is_absent(self, client):
        resp = await client.get("/api/v1/alerts")

        assert resp.status_code == 404


class TestIntake:
    async def _decision(self, wired_app, loop) -> str:
        wired_app.motor_mock.select = AsyncMock(
            return_value={"arm": {"index": 0}, "policy": "BetaTSPolicy"}
        )
        answer = await wired_app.svc.select_loop(TENANT, loop["key"], "unit-1")
        await wired_app.events.drain()
        return answer["request_id"]

    async def test_select_and_outcome_stamp_the_cycle(self, api, wired_app):
        loop = await _loop(wired_app)
        request_id = await self._decision(wired_app, loop)

        await wired_app.svc.outcome(TENANT, request_id, 1)
        await wired_app.events.drain()

        cycle = (TENANT, loop["cycle"]["id"])
        intake = (await wired_app.svc.redis.intakes([cycle]))[cycle]
        assert (intake.decisions, intake.outcomes, intake.since_outcome) == (1, 1, 0)
        assert intake.last_outcome_ms is not None

    async def test_an_invalid_outcome_still_counts_as_arrived(self, api, wired_app):
        loop = await _loop(wired_app)
        request_id = await self._decision(wired_app, loop)

        with pytest.raises(Exception):
            await wired_app.svc.outcome(TENANT, request_id, 7)
        await wired_app.events.drain()

        cycle = (TENANT, loop["cycle"]["id"])
        assert (await wired_app.svc.redis.intakes([cycle]))[cycle].outcomes == 1

    async def test_a_redis_failure_loses_the_stamp_not_the_outcome(
        self, api, wired_app, monkeypatch
    ):
        loop = await _loop(wired_app)
        request_id = await self._decision(wired_app, loop)
        monkeypatch.setattr(
            wired_app.svc.redis,
            "record_intake",
            AsyncMock(side_effect=ConnectionError("redis down")),
        )

        found = await wired_app.svc.outcome(TENANT, request_id, 1)
        await wired_app.events.drain()

        assert found["id"]
        assert len(wired_app.metric_spy.events) == 1
