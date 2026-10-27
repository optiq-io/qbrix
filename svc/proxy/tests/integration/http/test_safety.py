"""integration tests for the safety watch, a qbrix next surface.

invariants verified:
  a live loop pauses when more than 5% of its select calls over 10 minutes
  failed on qbrix's side, with at least 100 of them; caller errors and
  unknown ids neither count nor hide errors. the pause is one loop.pause
  change by qbrix with its evidence, and select answers the fallback after
  it. only the lease holder evaluates, another replica takes over once the
  lease lapses, and a pause that loses a race records nothing. errors from
  before the loop went live never count, a quiet install reads no counters,
  and draft and paused loops are never evaluated.
"""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
import pytest_asyncio
from sqlalchemy import update

import proxysvc.config
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.health import SelectErrorReason
from qbrixstore.redis.health import SelectOutcome

from proxysvc.core.actor import Actor
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.safety.watch import LEASE
from proxysvc.mod.safety.watch import SafetyWatch
from proxysvc.next import next_routes

TENANT = "dev-tenant"
ACTOR = Actor.member("user-ada")

OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    """the client with the next routes mounted, and a metric to improve."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=2 * 24 * 60 * 60,
        actor=ACTOR,
    )
    yield client
    app.router.routes[:] = routes


@pytest.fixture
def now() -> float:
    return time.time()


@pytest.fixture
def minute(now) -> int:
    return int(now) // 60


def _watch(wired_app) -> SafetyWatch:
    return SafetyWatch(wired_app.svc.redis, wired_app.svc.loops, interval_sec=30)


async def _loop(wired_app, *, launch: bool = True, live_minutes: int = 60) -> dict:
    loop = (
        await wired_app.svc.create_loop(
            TENANT,
            name="Checkout headline",
            metric="purchase",
            options=OPTIONS,
            actor=ACTOR,
        )
    ).value
    if launch:
        loop = (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)).value
        await _live_since(loop["id"], minutes_ago=live_minutes)
    return loop


async def _live_since(loop_id: str, *, minutes_ago: float) -> None:
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    async with get_session() as session:
        await session.execute(
            update(Loop).where(Loop.id == loop_id).values(live_since=when)
        )


async def _calls(
    wired_app,
    loop: dict,
    minute: int,
    *,
    ok: int = 0,
    error: int = 0,
    client: int = 0,
    not_found: int = 0,
) -> None:
    redis = wired_app.svc.redis
    cycle_id = loop["cycle"]["id"]
    for outcome, count in (
        (SelectOutcome.OK, ok),
        (SelectOutcome.CLIENT, client),
        (SelectOutcome.NOT_FOUND, not_found),
    ):
        for _ in range(count):
            await redis.record_select(TENANT, cycle_id, outcome, minute=minute)
    for _ in range(error):
        await redis.record_select(
            TENANT,
            cycle_id,
            SelectOutcome.ERROR,
            SelectErrorReason.MOTOR_UNAVAILABLE,
            minute=minute,
        )


async def _state(wired_app, loop: dict) -> str:
    return (await wired_app.svc.get_loop(TENANT, loop["key"]))["state"]


async def _pauses(wired_app, loop: dict) -> list[dict]:
    changes = await wired_app.svc.list_changes(TENANT, "loop", loop["id"])
    return [c for c in changes if c["kind"] == "loop.pause"]


@pytest.fixture
def health_reads(wired_app, monkeypatch) -> list[str]:
    redis = wired_app.svc.redis
    reads = []
    select_health = redis.select_health

    async def counted(tenant_id, experiment_id, *args, **kwargs):
        reads.append(experiment_id)
        return await select_health(tenant_id, experiment_id, *args, **kwargs)

    monkeypatch.setattr(redis, "select_health", counted)
    return reads


class TestRule:
    @pytest.mark.parametrize(
        ("ok", "error", "state"),
        [(95, 5, "live"), (94, 6, "paused"), (80, 10, "live")],
    )
    async def test_pauses_above_5_percent_of_at_least_100_calls(
        self, wired_app, api, now, minute, ok, error, state
    ):
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute - 3, ok=ok, error=error)

        await _watch(wired_app).run_once(now)

        assert await _state(wired_app, loop) == state

    async def test_sums_the_window_and_nothing_older(self, wired_app, api, now, minute):
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute - 10, error=100)
        await _calls(wired_app, loop, minute - 9, ok=47, error=3)
        await _calls(wired_app, loop, minute, ok=47, error=3)

        await _watch(wired_app).run_once(now)

        assert await _state(wired_app, loop) == "paused"
        (pause,) = await _pauses(wired_app, loop)
        assert (pause["evidence"]["errors"], pause["evidence"]["calls"]) == (6, 100)

    async def test_caller_errors_and_unknown_ids_count_for_nothing(
        self, wired_app, api, now, minute
    ):
        unhealthy = await _loop(wired_app)
        too_few = await _loop(wired_app)
        await _calls(
            wired_app, unhealthy, minute, ok=94, error=6, client=900, not_found=900
        )
        await _calls(wired_app, too_few, minute, error=10, client=500, not_found=500)

        await _watch(wired_app).run_once(now)

        assert await _state(wired_app, unhealthy) == "paused"
        assert await _state(wired_app, too_few) == "live"


class TestPause:
    async def test_is_one_change_by_qbrix_with_its_evidence(
        self, wired_app, api, now, minute
    ):
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute - 1, ok=90, error=10)

        await _watch(wired_app).run_once(now)

        (pause,) = await _pauses(wired_app, loop)
        assert pause["actor"]["kind"] == "qbrix"
        assert pause["reason"] == "decision errors"
        found = pause["evidence"]
        assert {k: found[k] for k in ("signal", "rate", "errors", "calls")} == {
            "signal": "decision_errors",
            "rate": 0.1,
            "errors": 10,
            "calls": 100,
        }
        assert found["reasons"] == {"motor_unavailable": 10}
        start = datetime.fromisoformat(found["window_start"])
        end = datetime.fromisoformat(found["window_end"])
        assert start.timestamp() == (minute - 9) * 60
        assert end.timestamp() == pytest.approx(now)

    async def test_select_answers_the_fallback_after_it(
        self, wired_app, api, now, minute
    ):
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute, ok=90, error=10)

        await _watch(wired_app).run_once(now)
        resp = await api.post(
            "/api/v1/select", json={"loop": loop["key"], "context": {"unit": "u"}}
        )

        assert resp.json()["reason"] == "paused"
        assert resp.json()["request_id"] is None

    async def test_a_second_pass_records_nothing_more(
        self, wired_app, api, now, minute
    ):
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute, ok=90, error=10)
        watch = _watch(wired_app)

        await watch.run_once(now)
        await watch.run_once(now)

        assert len(await _pauses(wired_app, loop)) == 1

    async def test_a_pause_that_loses_the_race_records_nothing(
        self, wired_app, api, now, minute, monkeypatch
    ):
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute, ok=90, error=10)
        resolve = LoopRepository.resolve

        async def another_watch_pauses_first(repo, ref):
            found = await resolve(repo, ref)
            await repo.transition(
                found.id, from_state="live", state="paused", paused_from="live"
            )
            return found

        monkeypatch.setattr(LoopRepository, "resolve", another_watch_pauses_first)
        await _watch(wired_app).run_once(now)

        assert await _pauses(wired_app, loop) == []


class TestLease:
    async def test_only_the_holder_evaluates(self, wired_app, api, now, minute):
        holder, other = _watch(wired_app), _watch(wired_app)
        await holder.run_once(now)
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute, ok=90, error=10)

        await other.run_once(now)

        assert await _state(wired_app, loop) == "live"

    async def test_another_replica_takes_over_once_it_lapses(
        self, wired_app, api, now, minute
    ):
        holder, other = _watch(wired_app), _watch(wired_app)
        await holder.run_once(now)
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute, ok=90, error=10)
        await other.run_once(now)

        await wired_app.fake_redis.delete(f"qbrix:lease:{LEASE}")
        await other.run_once(now)

        assert await _state(wired_app, loop) == "paused"

    async def test_stopping_hands_it_over(self, wired_app, api, now):
        holder = _watch(wired_app)
        await holder.start()
        await holder.run_once(now)

        await holder.stop()

        assert await wired_app.fake_redis.get(f"qbrix:lease:{LEASE}") is None


class TestWindow:
    async def test_errors_from_before_live_since_never_count(
        self, wired_app, api, now, minute
    ):
        loop = await _loop(wired_app)
        await _live_since(loop["id"], minutes_ago=(now % 60) / 60 + 4.5)
        await _calls(wired_app, loop, minute - 5, ok=0, error=100)
        await _calls(wired_app, loop, minute - 4, ok=95, error=5)

        await _watch(wired_app).run_once(now)

        assert await _state(wired_app, loop) == "live"

    async def test_errors_after_a_resume_still_pause(self, wired_app, api, now, minute):
        loop = await _loop(wired_app)
        await _live_since(loop["id"], minutes_ago=(now % 60) / 60 + 4.5)
        await _calls(wired_app, loop, minute - 4, ok=94, error=6)

        await _watch(wired_app).run_once(now)

        assert await _state(wired_app, loop) == "paused"

    async def test_a_quiet_install_reads_no_counters(
        self, wired_app, api, now, minute, health_reads
    ):
        loop = await _loop(wired_app)
        await _calls(wired_app, loop, minute, ok=500)

        await _watch(wired_app).run_once(now)

        assert health_reads == []

    async def test_draft_and_paused_loops_are_never_evaluated(
        self, wired_app, api, now, minute, health_reads
    ):
        draft = await _loop(wired_app, launch=False)
        paused = await _loop(wired_app)
        await wired_app.svc.loops.pause_loop(TENANT, paused["key"], actor=ACTOR)
        await _calls(wired_app, paused, minute, ok=50, error=50)
        await wired_app.svc.redis.record_select(
            TENANT, draft["id"], SelectOutcome.ERROR, minute=minute
        )

        await _watch(wired_app).run_once(now)

        assert health_reads == []
        assert await _state(wired_app, paused) == "paused"
        assert len(await _pauses(wired_app, paused)) == 1
