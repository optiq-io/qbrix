"""integration tests for the workspace's changes and undo, a qbrix next surface.

invariants verified:
  the list holds every change in the workspace, newest first, and never another
  workspace's. a cursor walks it without repeats or gaps. each filter narrows it,
  and filters combine. a burst of one change by one actor within ten minutes is
  one entry with its count and ids, and fold=false returns each; a fold cut by a
  page's end goes on as its own entry. a change's diff says what changed and its
  sentence never does. a deleted target keeps its last name. undo writes the
  inverse, the original then names who undid it, and every refusal is a 409 with
  its reason, a moved change naming the later change. a viewer and a key can't
  undo.
"""

from __future__ import annotations

from datetime import timedelta

import pytest_asyncio
from sqlalchemy import select

import proxysvc.config
import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Change

from proxysvc.core.actor import Actor
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"

CLAUDE = Actor.connection(
    "dev-user", connection_id="conn-claude", client_name="Claude Code"
)
CURSOR = Actor.connection("dev-user", connection_id="conn-cursor", client_name="Cursor")

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
async def api(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    resp = await client.post("/api/v1/metrics", json=PURCHASE)
    assert resp.status_code == 201, resp.text
    yield client
    app.router.routes[:] = routes


async def _loop(api, name: str = "Pricing page CTA") -> dict:
    resp = await api.post(
        "/api/v1/loops", json={"name": name, "metric": "purchase", "options": OPTIONS}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _changes(api, **params) -> dict:
    resp = await api.get("/api/v1/changes", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _rename(wired_app, loop: dict, name: str, actor: Actor = CLAUDE) -> None:
    renamed = await wired_app.svc.loops.rename_loop(
        TENANT, loop["id"], name=name, actor=actor
    )
    assert renamed is not None


async def _kinds(api, **params) -> list[str]:
    return [entry["kind"] for entry in (await _changes(api, **params))["changes"]]


async def _spread(minutes: int) -> None:
    """moves every change apart in time, the newest staying where it is."""
    async with _session_module.get_session() as session:
        rows = await session.execute(
            select(Change)
            .where(Change.tenant_id == TENANT)
            .order_by(Change.created_at.desc(), Change.id.desc())
        )
        for position, change in enumerate(rows.scalars().all()):
            change.created_at -= timedelta(minutes=minutes * position)


class TestList:

    async def test_newest_first_with_who_and_target(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "Pricing CTA")

        changes = (await _changes(api))["changes"]

        assert [c["kind"] for c in changes] == [
            "loop.rename",
            "loop.create",
            "metric.create",
        ]
        rename = changes[0]
        assert rename["who"]["kind"] == "connection"
        assert rename["via"] == {
            "connection_id": "conn-claude",
            "client": "Claude Code",
        }
        assert rename["target"] == {
            "type": "loop",
            "id": loop["id"],
            "key": loop["key"],
            "name": "Pricing CTA",
        }
        assert rename["count"] == 1
        assert rename["first_at"] == rename["at"]
        assert rename["ids"] == [rename["id"]]

    async def test_never_another_workspaces(self, api, wired_app):
        await _loop(api)

        with as_tenant(wired_app.app, tenant_id="other-tenant"):
            assert (await _changes(api))["changes"] == []

    async def test_one_change_is_not_read_from_another_workspace(self, api, wired_app):
        await _loop(api)
        change_id = (await _changes(api))["changes"][0]["id"]

        with as_tenant(wired_app.app, tenant_id="other-tenant"):
            resp = await api.get(f"/api/v1/changes/{change_id}")

        assert resp.status_code == 404

    async def test_a_cursor_walks_every_change_once_over_three_pages(
        self, api, wired_app
    ):
        loop = await _loop(api)
        for number in range(4):
            await _rename(wired_app, loop, f"Name {number}")
        expected = [c["id"] for c in (await _changes(api, fold="false"))["changes"]]
        assert len(expected) == 6

        seen, cursor, pages = [], None, 0
        while True:
            params = {"limit": 2, "fold": "false"}
            if cursor:
                params["cursor"] = cursor
            page = await _changes(api, **params)
            seen += [c["id"] for c in page["changes"]]
            pages += 1
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert pages == 3
        assert seen == expected

    async def test_a_bad_cursor_is_refused(self, api):
        resp = await api.get("/api/v1/changes", params={"cursor": "not-a-cursor"})

        assert resp.status_code == 400


class TestFilters:

    async def test_who(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "Renamed")
        launched = await api.post(f"/api/v1/loops/{loop['key']}/launch")
        assert launched.status_code == 200
        await wired_app.svc.loops.pause_loop(TENANT, loop["id"], actor=Actor.qbrix())

        assert await _kinds(api, who="connection") == ["loop.rename"]
        assert await _kinds(api, who="qbrix") == ["loop.pause"]
        assert await _kinds(api, who="member") == [
            "loop.launch",
            "loop.create",
            "metric.create",
        ]
        assert await _kinds(api, who=["qbrix", "connection"]) == [
            "loop.pause",
            "loop.rename",
        ]

    async def test_kind(self, api):
        await _loop(api)

        assert await _kinds(api, kind="metric.create") == ["metric.create"]

    async def test_loop_by_key_or_id(self, api, wired_app):
        first = await _loop(api)
        second = await _loop(api, "Another")
        await _rename(wired_app, second, "Another still")

        assert await _kinds(api, loop=first["key"]) == ["loop.create"]
        assert await _kinds(api, loop=second["id"]) == ["loop.rename", "loop.create"]

    async def test_metric_by_name(self, api):
        await _loop(api)

        assert await _kinds(api, metric="purchase") == ["metric.create"]

    async def test_an_unknown_loop_or_metric_is_not_found(self, api):
        assert (await api.get("/api/v1/changes?loop=nope")).status_code == 404
        assert (await api.get("/api/v1/changes?metric=nope")).status_code == 404

    async def test_undoable(self, api, wired_app):
        loop = await _loop(api)
        launched = await api.post(f"/api/v1/loops/{loop['key']}/launch")
        assert launched.status_code == 200

        assert await _kinds(api, undoable="false") == ["loop.launch"]
        assert await _kinds(api, undoable="true") == ["loop.create", "metric.create"]

    async def test_an_undone_change_is_no_longer_undoable(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "Renamed")
        rename = (await _changes(api, kind="loop.rename"))["changes"][0]
        undone = await api.post(f"/api/v1/changes/{rename['id']}/undo")
        assert undone.status_code == 200

        ids = [c["id"] for c in (await _changes(api, undoable="true"))["changes"]]

        assert rename["id"] not in ids
        assert undone.json()["id"] in ids

    async def test_they_combine(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "Renamed")

        assert await _kinds(api, loop=loop["key"], who="member") == ["loop.create"]
        assert (
            await _kinds(api, loop=loop["key"], kind="loop.rename", who="member") == []
        )
        assert await _kinds(api, loop=loop["key"], metric="purchase") == []


class TestFold:

    async def test_six_renames_by_one_connection_are_one_entry(self, api, wired_app):
        loop = await _loop(api)
        for number in range(6):
            await _rename(wired_app, loop, f"Name {number}")

        fold = (await _changes(api, kind="loop.rename"))["changes"]
        raw = (await _changes(api, kind="loop.rename", fold="false"))["changes"]

        assert len(fold) == 1
        assert len(raw) == 6
        assert fold[0]["count"] == 6
        assert fold[0]["ids"] == [c["id"] for c in raw]
        assert fold[0]["at"] == raw[0]["at"]
        assert fold[0]["first_at"] == raw[-1]["at"]
        assert fold[0]["pieces"][1]["text"] == " made 6 changes to "
        assert fold[0]["diff"] == [
            {"field": "name", "before": "Pricing page CTA", "after": "Name 5"}
        ]

    async def test_another_actor_breaks_a_fold(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "One")
        await _rename(wired_app, loop, "Two", CURSOR)
        await _rename(wired_app, loop, "Three")

        changes = (await _changes(api, kind="loop.rename"))["changes"]

        assert [c["count"] for c in changes] == [1, 1, 1]

    async def test_an_undo_and_what_it_undid_stay_apart(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "One")
        await _rename(wired_app, loop, "Two")
        newest = (await _changes(api, kind="loop.rename", fold="false"))["changes"][0]
        undone = await api.post(f"/api/v1/changes/{newest['id']}/undo")
        assert undone.status_code == 200

        changes = (await _changes(api, kind="loop.rename"))["changes"]

        assert [c["id"] for c in changes][:2] == [undone.json()["id"], newest["id"]]
        assert changes[1]["undone_by"]["id"] == undone.json()["id"]
        assert [c["count"] for c in changes] == [1, 1, 1]

    async def test_more_than_ten_minutes_apart_do_not_fold(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "One")
        await _rename(wired_app, loop, "Two")
        await _spread(minutes=11)

        changes = (await _changes(api, kind="loop.rename"))["changes"]

        assert [c["count"] for c in changes] == [1, 1]

    async def test_a_fold_cut_by_a_page_goes_on_as_its_own_entry(self, api, wired_app):
        loop = await _loop(api)
        for number in range(5):
            await _rename(wired_app, loop, f"Name {number}")

        first = await _changes(api, kind="loop.rename", limit=3)
        second = await _changes(
            api, kind="loop.rename", limit=3, cursor=first["next_cursor"]
        )

        assert [c["count"] for c in first["changes"]] == [3]
        assert [c["count"] for c in second["changes"]] == [2]
        assert second["next_cursor"] is None
        assert not set(first["changes"][0]["ids"]) & set(second["changes"][0]["ids"])


class TestPiecesAndDiff:

    async def test_a_rename(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "Pricing CTA")

        rename = (await _changes(api, kind="loop.rename"))["changes"][0]

        assert rename["diff"] == [
            {"field": "name", "before": "Pricing page CTA", "after": "Pricing CTA"}
        ]
        assert rename["pieces"] == [
            {
                "kind": "actor",
                "actor": {
                    "kind": "connection",
                    "name": "Claude Code",
                    "on_behalf_of": rename["who"]["name"],
                },
                "text": None,
                "name": None,
            },
            {"kind": "text", "actor": None, "text": " renamed ", "name": None},
            {"kind": "loop", "actor": None, "text": None, "name": "Pricing CTA"},
            {"kind": "text", "actor": None, "text": ".", "name": None},
        ]

    async def test_a_pause_by_qbrix(self, api, wired_app):
        loop = await _loop(api)
        launched = await api.post(f"/api/v1/loops/{loop['key']}/launch")
        assert launched.status_code == 200
        await wired_app.svc.loops.pause_loop(TENANT, loop["id"], actor=Actor.qbrix())

        pause = (await _changes(api, kind="loop.pause"))["changes"][0]

        assert pause["diff"] == [
            {"field": "state", "before": "live", "after": "paused"}
        ]
        assert pause["who"] == {"kind": "qbrix", "user_id": None, "name": None}
        assert pause["pieces"][0]["actor"]["kind"] == "qbrix"
        assert pause["pieces"][1]["text"] == " paused "

    async def test_a_create_has_no_diff(self, api):
        await _loop(api)

        create = (await _changes(api, kind="loop.create"))["changes"][0]

        assert create["diff"] == []
        assert create["before"] is None
        assert create["after"]["name"] == "Pricing page CTA"

    async def test_a_deleted_target_keeps_its_id_and_last_name(self, api, wired_app):
        loop = await _loop(api)
        deleted = await wired_app.svc.loops.delete_loop(
            TENANT, loop["id"], actor=CLAUDE
        )
        assert deleted

        changes = (await _changes(api, who="connection"))["changes"]

        assert changes[0]["kind"] == "loop.delete"
        assert changes[0]["target"]["id"] == loop["id"]
        assert changes[0]["target"]["name"] == "Pricing page CTA"
        assert changes[0]["target"]["key"] == loop["key"]


class TestUndo:

    async def test_writes_the_inverse_and_links_both_ways(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "Renamed")
        rename = (await _changes(api, kind="loop.rename"))["changes"][0]
        assert rename["undoable"] is True
        assert rename["undone_by"] is None

        resp = await api.post(
            f"/api/v1/changes/{rename['id']}/undo", json={"reason": "wrong name"}
        )

        assert resp.status_code == 200, resp.text
        undo = resp.json()
        assert undo["undoes_id"] == rename["id"]
        assert undo["reason"] == "wrong name"
        assert undo["target"]["name"] == "Pricing page CTA"

        original = (await api.get(f"/api/v1/changes/{rename['id']}")).json()
        assert original["status"] == "undone"
        assert original["undoable"] is False
        assert original["undone_by"]["id"] == undo["id"]
        assert original["undone_by"]["who"]["kind"] == "member"
        assert original["undone_by"]["at"] == undo["at"]

    async def test_a_body_is_optional(self, api):
        await _loop(api)
        create = (await _changes(api, kind="loop.create"))["changes"][0]

        resp = await api.post(f"/api/v1/changes/{create['id']}/undo")

        assert resp.status_code == 200, resp.text
        assert resp.json()["kind"] == "loop.delete"

    async def test_a_launch_is_refused_with_its_reason(self, api):
        loop = await _loop(api)
        launched = await api.post(f"/api/v1/loops/{loop['key']}/launch")
        assert launched.status_code == 200
        launch = (await _changes(api, kind="loop.launch"))["changes"][0]
        assert launch["undoable"] is False
        assert launch["not_undoable_reason"]

        resp = await api.post(f"/api/v1/changes/{launch['id']}/undo")

        assert resp.status_code == 409
        assert resp.json()["code"] == "CHANGE_NOT_UNDOABLE"
        assert launch["not_undoable_reason"] in resp.json()["detail"]

    async def test_an_already_undone_change_is_refused(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "Renamed")
        rename = (await _changes(api, kind="loop.rename"))["changes"][0]
        first = await api.post(f"/api/v1/changes/{rename['id']}/undo")
        assert first.status_code == 200

        resp = await api.post(f"/api/v1/changes/{rename['id']}/undo")

        assert resp.status_code == 409
        assert "already undone" in resp.json()["detail"]
        assert first.json()["id"] in resp.json()["detail"]

    async def test_a_moved_change_names_the_later_one(self, api, wired_app):
        loop = await _loop(api)
        await _rename(wired_app, loop, "First")
        await _rename(wired_app, loop, "Second", CURSOR)
        first, second = (await _changes(api, kind="loop.rename", fold="false"))[
            "changes"
        ][::-1]

        resp = await api.post(f"/api/v1/changes/{first['id']}/undo")

        assert resp.status_code == 409
        assert resp.json()["context"] == {"later_change_id": second["id"]}
        assert second["id"] in resp.json()["detail"]

    async def test_an_unknown_change_is_not_found(self, api):
        resp = await api.post("/api/v1/changes/nope/undo")

        assert resp.status_code == 404
        assert resp.json()["code"] == "CHANGE_NOT_FOUND"

    async def test_a_viewer_reads_and_cannot_undo(self, api, wired_app):
        await _loop(api)
        create = (await _changes(api, kind="loop.create"))["changes"][0]

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            assert (await _changes(api))["changes"]
            resp = await api.post(f"/api/v1/changes/{create['id']}/undo")

        assert resp.status_code == 403
        current = (await api.get(f"/api/v1/changes/{create['id']}")).json()
        assert current["status"] == "applied"

    async def test_a_key_cannot_undo(self, api, wired_app):
        await _loop(api)
        create = (await _changes(api, kind="loop.create"))["changes"][0]
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("dev-user", api_key_id="key-1")
        try:
            resp = await api.post(f"/api/v1/changes/{create['id']}/undo")
        finally:
            del overrides[get_actor]

        assert resp.status_code == 403
