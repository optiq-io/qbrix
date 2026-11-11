"""integration tests for a person's inbox, a qbrix next surface.

invariants verified:
  waiting holds the changes the reader's own connections asked for, oldest
  first, in the change's words with what it would change, and how often that
  connection asked for the kind and was approved in the last thirty days; an
  undo counts under the kind it undoes. no one sees another person's waiting
  changes, an admin included. an answered change leaves at once. notified
  holds what the reader's connections did at act and notify in the last
  seven days, newest first, with undo, and nothing else. alerts hold the
  workspace's loops paused by qbrix until a person resumes them, for every
  role; a person's pause is no alert. a viewer gets alerts only and a count
  of nothing. the count equals waiting and runs one statement. a source added
  to the registry lands in its section. it is never another workspace's, and
  with next off the routes don't exist.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
import pytest_asyncio
from sqlalchemy import update

import proxysvc.config
import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Change

from proxysvc.core.actor import Actor
from proxysvc.mod.change.proposal import Waiting
from proxysvc.mod.inbox import source
from proxysvc.next import next_routes

from svc.proxy.tests.integration.http.conftest import as_tenant
from svc.proxy.tests.integration.http.test_loop_read import _counting

TENANT = "dev-tenant"
ADA = "user-ada"
BEN = "user-ben"

CLAUDE = Actor.connection(ADA, connection_id="conn-claude", client_name="Claude Code")
CURSOR = Actor.connection(BEN, connection_id="conn-cursor", client_name="Cursor")

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
    "window_seconds": 172800,
}
OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
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
    resp = await client.post("/api/v1/metrics", json=PURCHASE)
    assert resp.status_code == 201, resp.text
    yield client
    app.router.routes[:] = routes


async def _draft(api, name: str = "Pricing page CTA") -> dict:
    resp = await api.post(
        "/api/v1/loops", json={"name": name, "metric": "purchase", "options": OPTIONS}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _live(api, name: str = "Pricing page CTA") -> dict:
    loop = await _draft(api, name)
    resp = await api.post(f"/api/v1/loops/{loop['key']}/launch", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _act(wired_app, actor: Actor, kind: str, loop: dict, args=None, level="own"):
    return await wired_app.svc.act(
        TENANT,
        kind,
        loop["id"],
        args or {},
        actor=replace(actor, level=level),
        reason="it is ready",
    )


async def _ask(wired_app, kind: str, loop: dict, actor: Actor = CLAUDE) -> str:
    waiting = await _act(wired_app, actor, kind, loop, level="ask")
    assert isinstance(waiting, Waiting)
    return waiting.change["id"]


async def _as(wired_app, api, path: str, user: str = ADA, role: str = "member"):
    with as_tenant(wired_app.app, tenant_id=TENANT, user_id=user, role=role):
        resp = await api.get(path)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _inbox(wired_app, api, user: str = ADA, role: str = "member") -> dict:
    return await _as(wired_app, api, "/api/v1/inbox", user, role)


async def _count(wired_app, api, user: str = ADA, role: str = "member") -> int:
    return (await _as(wired_app, api, "/api/v1/inbox/count", user, role))["waiting"]


async def _answer(wired_app, api, change_id: str, answer: str) -> None:
    with as_tenant(wired_app.app, tenant_id=TENANT, user_id=ADA, role="member"):
        resp = await api.post(f"/api/v1/changes/{change_id}/{answer}", json={})
    assert resp.status_code == 200, resp.text


async def _backdate(change_id: str, days: int) -> None:
    async with _session_module.get_session() as session:
        await session.execute(
            update(Change)
            .where(Change.id == change_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=days))
        )


async def _safety_pause(wired_app, loop: dict) -> dict:
    return (
        await wired_app.svc.loops.pause_loop(
            TENANT,
            loop["key"],
            actor=Actor.qbrix(),
            reason="decision errors",
            evidence=EVIDENCE,
        )
    ).change


class TestWaiting:

    async def test_your_connections_change_says_what_it_will_do(self, wired_app, api):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)

        inbox = await _inbox(wired_app, api)

        [item] = inbox["waiting"]
        assert item["kind"] == "change"
        assert item["change"]["id"] == change_id
        assert item["change"]["verb"] == "asks to launch"
        assert item["change"]["reason"] == "it is ready"
        assert {"field": "state", "before": "draft", "after": "live"} in item["change"][
            "diff"
        ]
        assert item["asked"]["kind"] == "loop.launch"
        assert (item["asked"]["count"], item["asked"]["approved"]) == (1, 0)
        assert inbox["notified"] == inbox["alerts"] == inbox["suggestions"] == []

    async def test_oldest_asked_first(self, wired_app, api):
        first = await _ask(wired_app, "loop.launch", await _draft(api, "A"))
        second = await _ask(wired_app, "loop.launch", await _draft(api, "B"))

        inbox = await _inbox(wired_app, api)

        assert [item["change"]["id"] for item in inbox["waiting"]] == [first, second]

    @pytest.mark.parametrize("role", ["member", "admin"])
    async def test_no_one_sees_another_persons(self, wired_app, api, role):
        loop = await _draft(api)
        bens = await _ask(wired_app, "loop.launch", loop, actor=CURSOR)

        adas = await _inbox(wired_app, api, ADA, role)
        own = await _inbox(wired_app, api, BEN)

        assert adas["waiting"] == []
        assert [item["change"]["id"] for item in own["waiting"]] == [bens]
        assert await _count(wired_app, api, ADA, role) == 0

    async def test_an_answered_change_leaves_at_once(self, wired_app, api):
        approved = await _ask(wired_app, "loop.launch", await _draft(api, "A"))
        declined = await _ask(wired_app, "loop.launch", await _draft(api, "B"))
        assert await _count(wired_app, api) == 2

        await _answer(wired_app, api, approved, "approve")
        await _answer(wired_app, api, declined, "decline")

        inbox = await _inbox(wired_app, api)
        assert inbox["waiting"] == []
        assert inbox["notified"] == []
        assert await _count(wired_app, api) == 0

    async def test_asked_counts_what_was_approved(self, wired_app, api):
        first = await _ask(wired_app, "loop.launch", await _draft(api, "A"))
        await _answer(wired_app, api, first, "approve")
        await _ask(wired_app, "loop.launch", await _draft(api, "B"))

        [item] = (await _inbox(wired_app, api))["waiting"]

        assert (item["asked"]["count"], item["asked"]["approved"]) == (2, 1)

    async def test_an_undo_counts_under_the_kind_it_undoes(self, wired_app, api):
        loop = await _live(api)
        pause = await _act(wired_app, CLAUDE, "loop.pause", loop)

        await wired_app.svc.undo_change(
            TENANT, pause.change["id"], actor=replace(CLAUDE, level="ask")
        )

        [item] = (await _inbox(wired_app, api))["waiting"]
        assert item["change"]["kind"] == "loop.resume"
        assert item["asked"]["kind"] == "loop.pause"
        assert item["asked"]["count"] == 1


class TestNotified:

    async def test_a_change_at_act_and_notify_with_undo(self, wired_app, api):
        loop = await _draft(api)
        made = await _act(
            wired_app, CLAUDE, "loop.rename", loop, {"name": "Checkout"}, "notify"
        )

        [item] = (await _inbox(wired_app, api))["notified"]
        assert item["change"]["id"] == made.change["id"]
        assert item["change"]["undoable"] is True

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id=ADA, role="member"):
            resp = await api.post(f"/api/v1/changes/{made.change['id']}/undo")
        assert resp.status_code == 200, resp.text

        [item] = (await _inbox(wired_app, api))["notified"]
        assert item["change"]["status"] == "undone"
        assert item["change"]["undone_by"] is not None

    async def test_newest_first(self, wired_app, api):
        loop = await _draft(api)
        first = await _act(
            wired_app, CLAUDE, "loop.rename", loop, {"name": "A"}, "notify"
        )
        second = await _act(
            wired_app, CLAUDE, "loop.rename", loop, {"name": "B"}, "notify"
        )

        notified = (await _inbox(wired_app, api))["notified"]

        assert [item["change"]["id"] for item in notified] == [
            second.change["id"],
            first.change["id"],
        ]

    async def test_only_your_connections_lately_at_act_and_notify(self, wired_app, api):
        loop = await _draft(api)
        old = await _act(
            wired_app, CLAUDE, "loop.rename", loop, {"name": "A"}, "notify"
        )
        await _backdate(old.change["id"], days=8)
        await _act(wired_app, CLAUDE, "loop.rename", loop, {"name": "B"}, "own")
        await _act(wired_app, CURSOR, "loop.rename", loop, {"name": "C"}, "notify")
        await wired_app.svc.loops.rename_loop(
            TENANT, loop["id"], name="D", actor=Actor.member(ADA)
        )

        assert (await _inbox(wired_app, api))["notified"] == []


class TestAlerts:

    @pytest.mark.parametrize("role", ["member", "admin", "viewer"])
    async def test_a_safety_pause_is_an_alert_for_everyone(self, wired_app, api, role):
        loop = await _live(api)
        pause = await _safety_pause(wired_app, loop)

        [item] = (await _inbox(wired_app, api, BEN, role))["alerts"]

        assert item["kind"] == "safety_pause"
        assert item["loop"] == {
            "id": loop["id"],
            "key": loop["key"],
            "name": loop["name"],
        }
        assert item["alert"]["signal"] == "decision_errors"
        assert item["alert"]["evidence"]["rate"] == 0.238
        assert item["alert"]["change_id"] == pause["id"]

    async def test_a_resumed_loop_leaves(self, wired_app, api):
        loop = await _live(api)
        await _safety_pause(wired_app, loop)

        resp = await api.post(f"/api/v1/loops/{loop['key']}/resume", json={})
        assert resp.status_code == 200, resp.text

        assert (await _inbox(wired_app, api))["alerts"] == []

    async def test_a_persons_pause_is_no_alert(self, wired_app, api):
        loop = await _live(api)

        resp = await api.post(f"/api/v1/loops/{loop['key']}/pause", json={})
        assert resp.status_code == 200, resp.text

        assert (await _inbox(wired_app, api))["alerts"] == []


class TestViewer:

    async def test_a_viewer_gets_alerts_only(self, wired_app, api):
        await _ask(wired_app, "loop.launch", await _draft(api, "A"))
        loop = await _draft(api, "B")
        await _act(wired_app, CLAUDE, "loop.rename", loop, {"name": "C"}, "notify")
        live = await _live(api, "D")
        await _safety_pause(wired_app, live)

        inbox = await _inbox(wired_app, api, ADA, "viewer")

        assert inbox["waiting"] == []
        assert inbox["notified"] == []
        assert len(inbox["alerts"]) == 1
        assert await _count(wired_app, api, ADA, "viewer") == 0


class TestCount:

    async def test_matches_waiting_and_reads_no_items(self, wired_app, api):
        await _ask(wired_app, "loop.launch", await _draft(api, "A"))
        await _ask(wired_app, "loop.launch", await _draft(api, "B"))

        with _counting() as statements:
            count = await _count(wired_app, api)

        assert count == len((await _inbox(wired_app, api))["waiting"]) == 2
        assert len(statements) == 1


class _Suggestion:
    section = "suggestions"
    needs_change = False

    async def items(self, session, reader, now):
        return [{"kind": "change", "at": now.isoformat()}]


class TestSources:

    async def test_a_registered_source_lands_in_its_section(
        self, wired_app, api, monkeypatch
    ):
        monkeypatch.setattr(source, "SOURCES", (*source.SOURCES, _Suggestion()))

        inbox = await _inbox(wired_app, api)

        assert [item["kind"] for item in inbox["suggestions"]] == ["change"]


class TestBoundaries:

    async def test_another_workspace_sees_nothing(self, wired_app, api):
        await _ask(wired_app, "loop.launch", await _draft(api))
        await _safety_pause(wired_app, await _live(api, "Live"))

        with as_tenant(wired_app.app, tenant_id="tenant-b", user_id=ADA):
            resp = await api.get("/api/v1/inbox")

        inbox = resp.json()
        assert inbox["waiting"] == inbox["alerts"] == []

    @pytest.mark.parametrize("path", ["/api/v1/inbox", "/api/v1/inbox/count"])
    async def test_with_next_off_the_routes_do_not_exist(self, client, path):
        resp = await client.get(path)

        assert resp.status_code == 404
