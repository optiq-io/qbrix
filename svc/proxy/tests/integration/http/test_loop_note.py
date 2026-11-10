"""integration tests for notes in a loop's history, a qbrix next surface.

invariants verified:
  a person adds a note to a loop in any state, recorded as a note.add change
  with who and the text, which reads in the loop's history and the workspace's
  changes. a note is plain text, never empty and at most 4000 characters. a
  viewer and an api key are refused. notes never fold together. history shows
  everything, only changes, or only notes. a note can't be undone, and an undo
  looks past notes: one written after a change neither refuses its undo nor is
  named as the later change that does.
"""

from __future__ import annotations

import pytest_asyncio

import proxysvc.config

from proxysvc.core.actor import Actor
from proxysvc.mod.change.note import NOTE_MAX_LENGTH
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
}

HEADLINE = {
    "name": "Checkout headline",
    "metric": "purchase",
    "options": [
        {"name": "Control", "config": {"text": "Buy now"}},
        {"name": "Urgency", "config": {"text": "Only today"}},
    ],
}


@pytest_asyncio.fixture
async def loops(wired_app, client, next_enabled):
    """the client, with the next routes mounted and a draft loop."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    assert (await client.post("/api/v1/metrics", json=PURCHASE)).status_code == 201
    assert (await client.post("/api/v1/loops", json=HEADLINE)).status_code == 201
    yield client
    app.router.routes[:] = routes


async def _note(client, text: str, loop: str = "checkout-headline"):
    return await client.post(f"/api/v1/loops/{loop}/notes", json={"text": text})


async def _added(client, text: str) -> dict:
    resp = await _note(client, text)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _history(client, **params) -> list[dict]:
    resp = await client.get("/api/v1/loops/checkout-headline/history", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["changes"]


async def _post(client, path: str, json: dict | None = None) -> dict:
    resp = await client.post(f"/api/v1/loops/checkout-headline{path}", json=json)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _undo(client, change_id: str):
    return await client.post(f"/api/v1/changes/{change_id}/undo")


class TestAdd:
    async def test_is_recorded_with_who_and_its_text(self, loops):
        note = await _added(loops, "  checkout copy is frozen until the 20th  ")

        assert note["kind"] == "note.add"
        assert note["verb"] == "added a note to"
        assert note["note"] == "checkout copy is frozen until the 20th"
        assert note["who"]["kind"] == "member"
        assert note["reason"] is None

    async def test_reads_in_the_loops_history(self, loops):
        note = await _added(loops, "frozen until the 20th")

        latest = (await _history(loops))[0]

        assert latest["id"] == note["id"]
        assert latest["note"] == "frozen until the 20th"

    async def test_reads_in_the_workspaces_changes(self, loops):
        await _added(loops, "frozen until the 20th")

        resp = await loops.get("/api/v1/changes", params={"kind": "note.add"})

        (entry,) = resp.json()["changes"]
        assert entry["note"] == "frozen until the 20th"
        assert entry["diff"] == []
        assert entry["undoable"] is False
        assert entry["pieces"][1:] == [
            {"kind": "text", "text": " added a note to ", "actor": None, "name": None},
            {"kind": "loop", "name": "Checkout headline", "actor": None, "text": None},
            {"kind": "text", "text": ".", "actor": None, "name": None},
        ]

    async def test_notes_in_a_row_never_fold(self, loops):
        await _added(loops, "first")
        await _added(loops, "second")

        resp = await loops.get("/api/v1/changes", params={"kind": "note.add"})

        assert [e["note"] for e in resp.json()["changes"]] == ["second", "first"]
        assert [e["count"] for e in resp.json()["changes"]] == [1, 1]

    async def test_a_live_paused_or_retired_loop_takes_notes(self, loops):
        await _post(loops, "/launch")
        await _post(loops, "/pause")
        paused = await _note(loops, "paused for the rebuild")
        await _post(loops, "/retire")
        retired = await _note(loops, "the rebuild shipped the urgency copy")

        assert [paused.status_code, retired.status_code] == [201, 201]

    async def test_empty_or_too_long_text_is_refused(self, loops):
        empty = await _note(loops, "")
        blank = await _note(loops, "   ")
        long = await _note(loops, "x" * (NOTE_MAX_LENGTH + 1))

        assert [r.status_code for r in (empty, blank, long)] == [422, 400, 422]
        assert "a note needs some text" in blank.text
        assert [c["kind"] for c in await _history(loops)] == ["loop.create"]

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await _note(loops, "hello", loop="nope")

        assert resp.status_code == 404

    async def test_a_viewer_is_refused(self, wired_app, loops):
        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await _note(loops, "hello")

        assert resp.status_code == 403
        assert [c["kind"] for c in await _history(loops)] == ["loop.create"]

    async def test_an_api_key_is_refused(self, wired_app, loops):
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-x", api_key_id="key-1")
        try:
            resp = await _note(loops, "hello")
        finally:
            del overrides[get_actor]

        assert resp.status_code == 403
        assert "api key" in resp.text


class TestShow:
    async def test_shows_changes_and_notes_by_default(self, loops):
        await _added(loops, "a note")

        kinds = [c["kind"] for c in await _history(loops)]

        assert kinds == ["note.add", "loop.create"]

    async def test_notes_shows_only_notes(self, loops):
        await _added(loops, "a note")

        kinds = [c["kind"] for c in await _history(loops, show="notes")]

        assert kinds == ["note.add"]

    async def test_changes_leaves_notes_out(self, loops):
        await _added(loops, "a note")

        kinds = [c["kind"] for c in await _history(loops, show="changes")]

        assert kinds == ["loop.create"]

    async def test_an_unknown_show_is_refused(self, loops):
        resp = await loops.get(
            "/api/v1/loops/checkout-headline/history", params={"show": "declined"}
        )

        assert resp.status_code == 422


class TestUndo:
    async def test_a_note_cant_be_undone(self, loops):
        note = await _added(loops, "a note")

        resp = await _undo(loops, note["id"])

        assert resp.status_code == 409
        assert "a note stays in history; add another note to correct it" in resp.text

    async def test_a_note_after_a_change_doesnt_refuse_its_undo(self, wired_app, loops):
        await _post(loops, "/launch")
        await _post(loops, "/pause")
        pause = (await _history(loops))[0]
        await _added(loops, "paused for the rebuild")

        resp = await _undo(loops, pause["id"])

        assert resp.status_code == 200, resp.text
        assert (await wired_app.svc.get_loop(TENANT, "checkout-headline"))[
            "state"
        ] == "live"

    async def test_a_refused_undo_names_the_change_not_the_note(self, loops):
        await _post(loops, "/launch")
        await _post(loops, "/pause")
        pause = (await _history(loops))[0]
        await _post(loops, "/resume")
        resume = (await _history(loops))[0]
        await _added(loops, "resumed after the rebuild")

        resp = await _undo(loops, pause["id"])

        assert resp.status_code == 409
        assert resp.json()["context"]["later_change_id"] == resume["id"]
