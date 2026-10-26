"""integration tests for reading loops, a qbrix next surface.

invariants verified:
  a loop is found by its key or its id, only in its own workspace, with its
  owner's name, its metric's type and window, and its current cycle once
  launched. the list filters by state, pages newest first by an opaque cursor
  that neither repeats nor skips a loop when others are created between pages,
  and carries each loop's latest change in a fixed number of queries. a loop's
  cycles list newest first with their options as they were. its history lists
  every change newest first with who, via and why: a connection reads as its
  person via its client, a change by qbrix has no person, and a deleted user is
  a former member. every role can read.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest_asyncio
from sqlalchemy import event

import proxysvc.config
import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import User

from proxysvc.core.actor import Actor
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.next import next_routes

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"

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


@pytest_asyncio.fixture
async def loops(wired_app, client, next_enabled):
    """the client, with the next routes mounted and a metric to improve."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    resp = await client.post("/api/v1/metrics", json=PURCHASE)
    assert resp.status_code == 201, resp.text
    yield client
    app.router.routes[:] = routes


async def _create(client, name: str = "Checkout headline") -> dict:
    resp = await client.post(
        "/api/v1/loops", json={"name": name, "metric": "purchase", "options": OPTIONS}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _launch(client, ref: str) -> dict:
    resp = await client.post(f"/api/v1/loops/{ref}/launch")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _get(client, path: str, **params) -> dict:
    resp = await client.get(f"/api/v1/loops{path}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _add_user(user_id: str, name: str | None, email: str) -> None:
    async with _session_module.get_session() as session:
        session.add(
            User(
                id=user_id,
                tenant_id=TENANT,
                email=email,
                password_hash="x",
                name=name,
            )
        )


async def _record(loop_id: str, kind: str, actor: Actor, reason: str) -> None:
    async with _session_module.get_session() as session:
        await ChangeRepository(session, TENANT).record(
            kind, "loop", loop_id, actor, reason=reason
        )


@contextmanager
def _counting():
    """counts the sql statements run inside the block."""
    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    engine = _session_module._engine.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", count)


class TestGet:
    async def test_finds_a_loop_by_key_and_by_id(self, loops):
        created = await _create(loops)

        by_key = await _get(loops, "/checkout-headline")
        by_id = await _get(loops, f"/{created['id']}")

        assert by_key == by_id
        assert by_key["id"] == created["id"]

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.get("/api/v1/loops/nope")

        assert resp.status_code == 404
        assert resp.json()["code"] == "LOOP_NOT_FOUND"

    async def test_another_workspaces_loop_is_not_found(self, wired_app, loops):
        created = await _create(loops)

        with as_tenant(wired_app.app, tenant_id="tenant-b"):
            by_key = await loops.get("/api/v1/loops/checkout-headline")
            by_id = await loops.get(f"/api/v1/loops/{created['id']}")
            cycles = await loops.get(f"/api/v1/loops/{created['id']}/cycles")
            history = await loops.get(f"/api/v1/loops/{created['id']}/history")
            listed = await loops.get("/api/v1/loops")

        assert [r.status_code for r in (by_key, by_id, cycles, history)] == [404] * 4
        assert listed.json()["loops"] == []

    async def test_a_draft_has_no_current_cycle(self, loops):
        await _create(loops)

        loop = await _get(loops, "/checkout-headline")

        assert loop["state"] == "draft"
        assert loop["cycle"] is None

    async def test_a_launched_loop_shows_its_first_cycle(self, loops):
        await _create(loops)
        await _launch(loops, "checkout-headline")

        loop = await _get(loops, "/checkout-headline")

        assert loop["state"] == "live"
        assert loop["cycle"]["number"] == 1
        assert loop["cycle"]["engine"] == "spinoza:1"
        assert loop["cycle"]["engine_version"] == "1.0"
        assert loop["cycle"]["metric_version"] == "1.0"
        assert loop["cycle"]["ended_at"] is None

    async def test_carries_the_metric_terms_options_and_fallback(self, loops):
        await _create(loops)

        loop = await _get(loops, "/checkout-headline")

        assert {k: v for k, v in loop["metric"].items() if k != "id"} == {
            "name": "purchase",
            "type": "conversion",
            "window_seconds": 172800,
        }
        assert [(o["key"], o["config"]) for o in loop["options"]] == [
            ("control", {"text": "Buy now"}),
            ("urgency", {"text": "Only today"}),
        ]
        assert loop["fallback"] == "control"

    async def test_the_owner_has_a_name(self, loops):
        created = await _create(loops)
        await _add_user(created["owner"]["id"], "Ada", "ada@example.com")

        loop = await _get(loops, "/checkout-headline")

        assert loop["owner"] == {"id": created["owner"]["id"], "name": "Ada"}

    async def test_an_owner_without_a_name_reads_as_their_email(self, loops):
        created = await _create(loops)
        await _add_user(created["owner"]["id"], None, "ada@example.com")

        loop = await _get(loops, "/checkout-headline")

        assert loop["owner"]["name"] == "ada@example.com"


class TestList:
    async def test_lists_newest_first_without_option_config(self, loops):
        first = await _create(loops, "First")
        second = await _create(loops, "Second")

        page = await _get(loops, "")

        assert [loop["id"] for loop in page["loops"]] == [second["id"], first["id"]]
        assert page["next_cursor"] is None
        assert "config" not in page["loops"][0]["options"][0]

    async def test_filters_by_state(self, loops):
        await _create(loops, "Draft")
        await _create(loops, "Live")
        await _launch(loops, "live")

        live = await _get(loops, "", state="live")
        both = await _get(loops, "", state=["live", "draft"])

        assert [loop["key"] for loop in live["loops"]] == ["live"]
        assert {loop["key"] for loop in both["loops"]} == {"live", "draft"}

    async def test_an_unknown_state_is_refused(self, loops):
        resp = await loops.get("/api/v1/loops", params={"state": "finished"})

        assert resp.status_code == 422

    async def test_pages_without_repeats_or_gaps_while_loops_are_created(self, loops):
        made = [(await _create(loops, f"Loop {n}"))["id"] for n in range(3)]

        first = await _get(loops, "", limit=2)
        await _create(loops, "Later 1")
        await _create(loops, "Later 2")
        second = await _get(loops, "", limit=2, cursor=first["next_cursor"])

        seen = [loop["id"] for loop in first["loops"] + second["loops"]]
        assert seen == list(reversed(made))
        assert second["next_cursor"] is None

    async def test_a_limit_above_200_is_refused(self, loops):
        resp = await loops.get("/api/v1/loops", params={"limit": 201})

        assert resp.status_code == 422

    async def test_a_cursor_no_page_returned_is_refused(self, loops):
        resp = await loops.get("/api/v1/loops", params={"cursor": "not-a-cursor"})

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_CURSOR"

    async def test_each_loop_carries_its_latest_change_and_actor(self, loops):
        await _create(loops, "Draft")
        await _create(loops, "Live")
        await _launch(loops, "live")

        page = await _get(loops, "")
        latest = {loop["key"]: loop["latest_change"] for loop in page["loops"]}

        assert latest["live"]["kind"] == "loop.launch"
        assert latest["draft"]["kind"] == "loop.create"
        assert latest["live"]["who"]["kind"] == "member"
        assert latest["live"]["who"]["user_id"]

    async def test_reads_the_same_number_of_queries_for_one_loop_or_many(self, loops):
        await _create(loops, "Only")
        await _launch(loops, "only")
        with _counting() as one:
            await _get(loops, "")

        for n in range(5):
            await _create(loops, f"More {n}")
            await _launch(loops, f"more-{n}")
        with _counting() as many:
            page = await _get(loops, "")

        assert len(page["loops"]) == 6
        assert len(many) == len(one)


class TestCycles:
    async def test_a_draft_has_no_cycles(self, loops):
        await _create(loops)

        page = await _get(loops, "/checkout-headline/cycles")

        assert page["cycles"] == []

    async def test_lists_cycles_with_their_options_as_they_were(self, loops):
        await _create(loops)
        await _launch(loops, "checkout-headline")

        (cycle,) = (await _get(loops, "/checkout-headline/cycles"))["cycles"]

        assert cycle["number"] == 1
        assert cycle["engine"] == "spinoza:1"
        assert cycle["metric_version"] == "1.0"
        assert [(o["key"], o["config"]) for o in cycle["options"]] == [
            ("control", {"text": "Buy now"}),
            ("urgency", {"text": "Only today"}),
        ]

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.get("/api/v1/loops/nope/cycles")

        assert resp.status_code == 404


class TestHistory:
    async def test_lists_every_change_newest_first(self, loops):
        await _create(loops)
        await loops.patch("/api/v1/loops/checkout-headline", json={"name": "Hero"})
        await _launch(loops, "checkout-headline")

        page = await _get(loops, "/checkout-headline/history")

        assert [c["kind"] for c in page["changes"]] == [
            "loop.launch",
            "loop.rename",
            "loop.create",
        ]
        assert page["next_cursor"] is None

    async def test_a_member_reads_as_themself_with_no_via(self, loops):
        created = await _create(loops)
        await _add_user(created["owner"]["id"], "Ada", "ada@example.com")

        (change,) = (await _get(loops, "/checkout-headline/history"))["changes"]

        assert change["who"] == {
            "kind": "member",
            "user_id": created["owner"]["id"],
            "name": "Ada",
        }
        assert change["via"] is None
        assert change["status"] == "applied"
        assert "before" not in change and "after" not in change

    async def test_a_connection_reads_as_its_person_via_its_client(self, loops):
        created = await _create(loops)
        await _add_user("user-ada", "Ada", "ada@example.com")
        via = Actor(
            kind="connection",
            user_id="user-ada",
            connection_id="conn-1",
            client_name="Claude Code",
        )
        await _record(created["id"], "loop.rename", via, "a clearer name")

        change = (await _get(loops, "/checkout-headline/history"))["changes"][0]

        assert change["who"] == {
            "kind": "connection",
            "user_id": "user-ada",
            "name": "Ada",
        }
        assert change["via"] == {"connection_id": "conn-1", "client": "Claude Code"}
        assert change["reason"] == "a clearer name"

    async def test_a_change_by_qbrix_has_no_person(self, loops):
        created = await _create(loops)
        await _record(
            created["id"], "loop.pause", Actor(kind="qbrix", user_id=""), "errors"
        )

        change = (await _get(loops, "/checkout-headline/history"))["changes"][0]

        assert change["who"] == {"kind": "qbrix", "user_id": None, "name": None}
        assert change["via"] is None

    async def test_a_deleted_user_reads_as_a_former_member(self, loops):
        created = await _create(loops)
        await _record(
            created["id"], "loop.rename", Actor.member("user-gone"), "before leaving"
        )

        change = (await _get(loops, "/checkout-headline/history"))["changes"][0]

        assert change["who"]["user_id"] == "user-gone"
        assert change["who"]["name"] == "former member"

    async def test_pages_by_cursor(self, loops):
        await _create(loops)
        for n in range(3):
            await loops.patch(
                "/api/v1/loops/checkout-headline", json={"name": f"Name {n}"}
            )

        first = await _get(loops, "/checkout-headline/history", limit=3)
        second = await _get(
            loops, "/checkout-headline/history", limit=3, cursor=first["next_cursor"]
        )

        assert len(first["changes"]) == 3
        assert [c["kind"] for c in second["changes"]] == ["loop.create"]
        assert second["next_cursor"] is None

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.get("/api/v1/loops/nope/history")

        assert resp.status_code == 404


class TestRoles:
    async def test_a_viewer_can_read_every_route(self, wired_app, loops):
        await _create(loops)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            responses = [
                await loops.get(path)
                for path in (
                    "/api/v1/loops",
                    "/api/v1/loops/checkout-headline",
                    "/api/v1/loops/checkout-headline/cycles",
                    "/api/v1/loops/checkout-headline/history",
                )
            ]

        assert [r.status_code for r in responses] == [200] * 4
