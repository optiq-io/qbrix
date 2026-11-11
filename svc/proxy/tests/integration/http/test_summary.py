"""integration tests for the workspace's week, a qbrix next surface.

invariants verified:
  the read carries each live, paused and committed loop, never a draft or a
  retired loop, with its share at since and now, lift as the loops list has
  it, milestones in the range and its changes grouped by who: a person by
  name, a connection as its person via its client, qbrix by itself. a safety
  pause is an open alert until a person resumes the loop, which is its
  recovery; one opened before since and still open is there too, and a
  person's own pause is never an alert. drafts are counted, and those older
  than a week named. change counts cover the range. since defaults to seven
  days, and one in the future or further back than thirty days is refused
  with what to pass. the number of queries doesn't grow with the loops. it is
  never another workspace's, and with next off the route doesn't exist.
"""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest_asyncio
from sqlalchemy import update

import proxysvc.config
import qbrixstore.postgres.session as _session_module
from qbrixstore.event import MilestoneEvent
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import User

from proxysvc.core.actor import Actor
from proxysvc.next import next_routes

from svc.proxy.tests.integration.http.conftest import as_tenant
from svc.proxy.tests.integration.http.test_loop_read import _counting

TENANT = "dev-tenant"
ADA = Actor.member("user-ada")
CLAUDE = Actor.connection(
    "user-ada", connection_id="connection-1", client_name="Claude Code"
)
DAY_MS = 24 * 60 * 60 * 1000

OPTIONS = [
    {"name": "Ships today", "config": {}},
    {"name": "Pay in one tap", "config": {}},
]

EVIDENCE = {
    "signal": "decision_errors",
    "rate": 0.238,
    "errors": 150,
    "calls": 629,
    "window_start": "2026-10-27T09:51:00+00:00",
    "window_end": "2026-10-27T10:01:12+00:00",
    "reasons": {"motor_unavailable": 150},
}


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    async with _session_module.get_session() as session:
        session.add(
            User(
                id="user-ada",
                tenant_id=TENANT,
                email="ada@example.com",
                password_hash="x",
                name="Ada",
            )
        )
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=3600,
        actor=ADA,
    )
    yield client
    app.router.routes[:] = routes


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _draft(wired_app, name: str) -> dict:
    return (
        await wired_app.svc.create_loop(
            TENANT, name=name, metric="purchase", options=OPTIONS, actor=ADA
        )
    ).value


async def _live(wired_app, name: str, started_days_ago: int = 10) -> dict:
    """a live loop whose first cycle started some days ago."""
    loop = await _draft(wired_app, name)
    launched = (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ADA)).value
    started = datetime.now(timezone.utc) - timedelta(days=started_days_ago)
    async with _session_module.get_session() as session:
        await session.execute(
            update(Cycle)
            .where(Cycle.id == launched["cycle"]["id"])
            .values(started_at=started)
        )
    return launched


async def _backdate_loop(loop_id: str, days: int) -> None:
    async with _session_module.get_session() as session:
        await session.execute(
            update(Loop)
            .where(Loop.id == loop_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=days))
        )


async def _backdate_change(change_id: str, days: int) -> None:
    async with _session_module.get_session() as session:
        await session.execute(
            update(Change)
            .where(Change.id == change_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=days))
        )


def _decide(wired_app, loop: dict, prefix: str, at_ms: int, by_option: list[int]):
    for index, n in enumerate(by_option):
        for i in range(n):
            wired_app.ledger.decide(
                loop["cycle"]["id"], f"{prefix}-{index}-{i}", index, at_ms
            )


async def _safety_pause(wired_app, ref: str) -> dict:
    return (
        await wired_app.svc.loops.pause_loop(
            TENANT,
            ref,
            actor=Actor.qbrix(),
            reason="decision errors",
            evidence=EVIDENCE,
        )
    ).change


async def _summary(api, **params) -> dict:
    resp = await api.get("/api/v1/summary", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _loop(week: dict, key: str) -> dict:
    return next(loop for loop in week["loops"] if loop["key"] == key)


class TestWeek:
    async def test_carries_live_and_paused_loops_and_counts_drafts(
        self, wired_app, api
    ):
        a = await _live(wired_app, "Checkout CTA")
        b = await _live(wired_app, "Search ranking")
        c = await _live(wired_app, "Onboarding tip")
        await _safety_pause(wired_app, c["key"])
        await _draft(wired_app, "Pricing page")
        old = await _draft(wired_app, "Old idea")
        await _backdate_loop(old["id"], 9)
        retired = await _live(wired_app, "Gone")
        await wired_app.svc.retire_loop(TENANT, retired["key"], actor=ADA)

        week = await _summary(api)

        assert {loop["key"] for loop in week["loops"]} == {
            a["key"],
            b["key"],
            c["key"],
        }
        assert _loop(week, c["key"])["state"] == "paused"
        assert week["drafts"]["count"] == 2
        assert [d["key"] for d in week["drafts"]["older_than_7_days"]] == [old["key"]]

    async def test_since_defaults_to_seven_days(self, api):
        week = await _summary(api)

        since = datetime.fromisoformat(week["since"])
        until = datetime.fromisoformat(week["until"])
        assert until - since == timedelta(days=7)

    async def test_share_then_and_now(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        now = _now_ms()
        since = now - 7 * DAY_MS
        _decide(wired_app, loop, "then", since - DAY_MS // 2, [4, 6])
        _decide(wired_app, loop, "old", since - 2 * DAY_MS, [10, 0])
        _decide(wired_app, loop, "now", now - DAY_MS // 2, [3, 1])

        found = _loop(await _summary(api), loop["key"])

        then, current = found["share"]["then"], found["share"]["now"]
        assert then["cycle"] == current["cycle"] == 1
        assert [o["share"] for o in then["options"]] == [0.4, 0.6]
        assert [o["share"] for o in current["options"]] == [0.75, 0.25]
        assert [o["name"] for o in current["options"]] == [
            "Ships today",
            "Pay in one tap",
        ]

    async def test_now_and_lift_read_as_the_loops_list(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        now = _now_ms()
        _decide(wired_app, loop, "now", now - DAY_MS // 2, [3, 1])
        for i in range(4):
            wired_app.ledger.seal(
                loop["cycle"]["id"], f"s{i}", i % 2, now - 3 * DAY_MS, float(i % 2)
            )

        found = _loop(await _summary(api), loop["key"])
        listed = (await wired_app.svc.list_loops(TENANT, limit=20))["loops"][0]

        assert [o["share"] for o in found["share"]["now"]["options"]] == [
            o["share"] for o in listed["results"]["share"]
        ]
        assert found["lift"] == listed["results"]["lift"]
        assert found["early"] == listed["results"]["early"]

    async def test_a_loop_launched_since_has_no_share_then(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA", started_days_ago=2)

        found = _loop(await _summary(api), loop["key"])

        assert found["share"]["then"] is None
        assert found["share"]["now"]["cycle"] == 1

    async def test_milestones_in_the_range(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        now = _now_ms()
        for event_id, at in (("in", now - DAY_MS), ("out", now - 9 * DAY_MS)):
            wired_app.ledger.reach(
                MilestoneEvent(
                    event_id=event_id,
                    kind="loop.leader_changed",
                    tenant_id=TENANT,
                    loop_id=loop["id"],
                    cycle_id=loop["cycle"]["id"],
                    payload={"from": 0, "to": 1},
                    at_ms=at,
                )
            )

        found = _loop(await _summary(api), loop["key"])

        assert [m["id"] for m in found["milestones"]] == ["in"]


class TestChangesByWho:
    async def test_a_person_and_a_connection_and_qbrix_each_group(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        await wired_app.svc.rename_loop(TENANT, loop["key"], name="CTA", actor=ADA)
        await wired_app.svc.loops.rename_loop(
            TENANT, loop["key"], name="CTA copy", actor=CLAUDE, reason="clearer"
        )
        await _safety_pause(wired_app, loop["key"])

        groups = _loop(await _summary(api), loop["key"])["changes"]

        by = {(g["who"]["kind"], g["who"]["name"], g["via"]): g for g in groups}
        assert set(by) == {
            ("member", "Ada", None),
            ("connection", "Ada", "Claude Code"),
            ("qbrix", None, None),
        }
        person = by[("member", "Ada", None)]
        assert [e["kind"] for e in person["changes"]] == [
            "loop.rename",
            "loop.launch",
            "loop.create",
        ]
        assert person["count"] == 3
        connection = by[("connection", "Ada", "Claude Code")]
        assert connection["changes"][0]["reason"] == "clearer"
        assert groups[0]["who"]["kind"] == "qbrix"

    async def test_changes_before_since_are_left_out(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        renamed = (
            await wired_app.svc.rename_loop(TENANT, loop["key"], name="CTA", actor=ADA)
        ).change
        await _backdate_change(renamed["id"], 8)

        week = await _summary(api)

        kinds = [
            e["kind"] for g in _loop(week, loop["key"])["changes"] for e in g["changes"]
        ]
        assert "loop.rename" not in kinds
        assert week["changes"]["total"] == len(kinds) + 1


class TestAlerts:
    async def test_a_safety_pause_is_open_until_a_person_resumes(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        pause = await _safety_pause(wired_app, loop["key"])

        opened = _loop(await _summary(api), loop["key"])["alerts"]
        resume = (
            await wired_app.svc.resume_loop(TENANT, loop["key"], actor=ADA)
        ).change
        closed = _loop(await _summary(api), loop["key"])["alerts"]

        assert opened == [
            {
                "kind": "safety_pause",
                "signal": "decision_errors",
                "opened_at": opened[0]["opened_at"],
                "evidence": EVIDENCE,
                "change_id": pause["id"],
                "recovered": None,
            }
        ]
        assert closed[0]["recovered"]["change_id"] == resume["id"]
        assert closed[0]["recovered"]["who"]["name"] == "Ada"

    async def test_a_pause_from_before_since_still_open_is_there(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        pause = await _safety_pause(wired_app, loop["key"])
        await _backdate_change(pause["id"], 9)

        alerts = _loop(await _summary(api), loop["key"])["alerts"]

        assert [(a["change_id"], a["recovered"]) for a in alerts] == [
            (pause["id"], None)
        ]

    async def test_a_persons_pause_is_no_alert(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        await wired_app.svc.pause_loop(TENANT, loop["key"], actor=ADA)

        assert _loop(await _summary(api), loop["key"])["alerts"] == []


class TestRange:
    async def test_since_further_back_than_thirty_days_is_refused(self, api):
        since = datetime.now(timezone.utc) - timedelta(days=31)

        resp = await api.get("/api/v1/summary", params={"since": since.isoformat()})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "INVALID_SUMMARY_RANGE"
        assert "30 days" in body["detail"]
        assert "on or after" in body["detail"]

    async def test_since_in_the_future_is_refused(self, api):
        since = datetime.now(timezone.utc) + timedelta(days=1)

        resp = await api.get("/api/v1/summary", params={"since": since.isoformat()})

        assert resp.status_code == 400

    async def test_a_shorter_range_leaves_older_changes_out(self, wired_app, api):
        loop = await _live(wired_app, "Checkout CTA")
        renamed = (
            await wired_app.svc.rename_loop(TENANT, loop["key"], name="CTA", actor=ADA)
        ).change
        await _backdate_change(renamed["id"], 2)
        since = datetime.now(timezone.utc) - timedelta(days=1)

        week = await _summary(api, since=since.isoformat())

        kinds = [
            e["kind"] for g in _loop(week, loop["key"])["changes"] for e in g["changes"]
        ]
        assert "loop.rename" not in kinds


class TestQueries:
    async def test_the_number_of_queries_does_not_grow_with_the_loops(
        self, wired_app, api
    ):
        first = await _live(wired_app, "Checkout CTA")
        await _safety_pause(wired_app, first["key"])
        wired_app.ledger.queries.clear()
        with _counting() as one:
            await _summary(api)
        ledger_one = list(wired_app.ledger.queries)

        for name in ("Search ranking", "Onboarding tip"):
            loop = await _live(wired_app, name)
            await wired_app.svc.rename_loop(
                TENANT, loop["key"], name=f"{name}!", actor=ADA
            )
            await wired_app.svc.loops.rename_loop(
                TENANT, loop["key"], name=name, actor=CLAUDE, reason="back"
            )
        wired_app.ledger.queries.clear()
        with _counting() as three:
            await _summary(api)

        assert len(three) == len(one)
        assert sorted(wired_app.ledger.queries) == sorted(ledger_one)


class TestBoundaries:
    async def test_another_workspaces_loops_are_not_there(self, wired_app, api):
        await _live(wired_app, "Checkout CTA")

        with as_tenant(wired_app.app, tenant_id="tenant-b"):
            week = await _summary(api)

        assert week["loops"] == []
        assert week["changes"]["total"] == 0

    async def test_with_next_off_the_route_does_not_exist(self, client):
        resp = await client.get("/api/v1/summary")

        assert resp.status_code == 404
