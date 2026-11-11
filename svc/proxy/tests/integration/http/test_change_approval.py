"""integration tests for changes that ask first, a qbrix next surface.

invariants verified:
  a connection's change at ask is recorded waiting with its proposal, its
  reason and a before and after, and applies nothing. approving it re-runs
  the proposal against the target as it is now: the same change becomes the
  applied one, moved to when it applied, recording who approved it and where.
  when the target no longer takes it, approving is a 409 naming the change
  that moved it, and the change keeps waiting. declining keeps it, with its
  reason. only the connection's own person answers, once. one change of a
  kind waits on a target at a time. a waiting or declined change never folds,
  can't be undone, and isn't counted; the list shows them only when asked.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import pytest_asyncio

import proxysvc.config
from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeAnswerForbiddenError
from proxysvc.core.error import ChangeWaitingError
from proxysvc.core.error import LoopStateError
from proxysvc.mod.change.proposal import Waiting
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
PERSON = "dev-user"

CLAUDE = Actor.connection(
    PERSON, connection_id="conn-claude", client_name="Claude Code"
)
ASKING = replace(CLAUDE, level="ask")

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
NEW_OPTIONS = [*OPTIONS, {"name": "Social proof", "config": {"text": "Loved by 10k"}}]


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    resp = await client.post("/api/v1/metrics", json=PURCHASE)
    assert resp.status_code == 201, resp.text
    yield client
    app.router.routes[:] = routes


async def _draft(api) -> dict:
    resp = await api.post(
        "/api/v1/loops",
        json={"name": "Pricing page CTA", "metric": "purchase", "options": OPTIONS},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _live(api) -> dict:
    loop = await _draft(api)
    resp = await api.post(f"/api/v1/loops/{loop['key']}/launch", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _ask(wired_app, kind: str, loop: dict, args: dict | None = None) -> str:
    waiting = await wired_app.svc.act(
        TENANT, kind, loop["id"], args or {}, actor=ASKING, reason="it is ready"
    )
    assert isinstance(waiting, Waiting)
    return waiting.change["id"]


async def _get(api, change_id: str) -> dict:
    resp = await api.get(f"/api/v1/changes/{change_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _state(api, loop: dict) -> str:
    resp = await api.get(f"/api/v1/loops/{loop['key']}")
    return resp.json()["state"]


class TestAsking:

    async def test_a_launch_waits_and_changes_nothing(self, wired_app, api):
        loop = await _draft(api)

        change_id = await _ask(wired_app, "loop.launch", loop)

        entry = await _get(api, change_id)
        assert entry["status"] == "waiting"
        assert entry["level"] == "ask"
        assert entry["reason"] == "it is ready"
        assert entry["via"]["client"] == "Claude Code"
        assert entry["before"]["state"] == "draft"
        assert entry["after"]["state"] == "live"
        assert entry["decision"] is None
        assert entry["undoable"] is False
        assert entry["verb"] == "asks to launch"
        assert await _state(api, loop) == "draft"

    async def test_a_proposal_the_loop_refuses_now_is_not_stored(self, wired_app, api):
        loop = await _live(api)

        with pytest.raises(LoopStateError) as refused:
            await wired_app.svc.act(
                TENANT, "loop.launch", loop["id"], {}, actor=ASKING, reason="again"
            )

        assert "only a draft can be launched" in str(refused.value)
        listed = await api.get("/api/v1/changes", params={"status": "waiting"})
        assert listed.json()["changes"] == []

    async def test_a_second_change_of_the_kind_is_refused_while_one_waits(
        self, wired_app, api
    ):
        loop = await _draft(api)
        first = await _ask(wired_app, "loop.launch", loop)

        with pytest.raises(ChangeWaitingError) as refused:
            await _ask(wired_app, "loop.launch", loop)

        assert refused.value.waiting_change_id == first

    async def test_other_kinds_wait_side_by_side(self, wired_app, api):
        loop = await _live(api)

        await _ask(wired_app, "loop.retire", loop)
        await _ask(wired_app, "cycle.start", loop, {"options": NEW_OPTIONS})

        listed = await api.get("/api/v1/changes", params={"status": "waiting"})
        assert {c["kind"] for c in listed.json()["changes"]} == {
            "loop.retire",
            "cycle.start",
        }

    async def test_own_and_notify_apply_and_record_the_level(self, wired_app, api):
        loop = await _draft(api)

        made = await wired_app.svc.act(
            TENANT,
            "loop.launch",
            loop["id"],
            {},
            actor=replace(CLAUDE, level="notify"),
            reason="go",
        )

        entry = await _get(api, made.change["id"])
        assert entry["status"] == "applied"
        assert entry["level"] == "notify"
        assert await _state(api, loop) == "live"

    async def test_a_members_change_has_no_level(self, api):
        loop = await _live(api)

        resp = await api.get("/api/v1/changes", params={"kind": "loop.launch"})

        [entry] = resp.json()["changes"]
        assert entry["id"]
        assert entry["level"] is None
        assert loop["state"] == "live"


class TestApproving:

    async def test_approving_applies_the_same_change(self, wired_app, api):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)

        resp = await api.post(f"/api/v1/changes/{change_id}/approve", json={})

        assert resp.status_code == 200, resp.text
        entry = resp.json()
        assert entry["id"] == change_id
        assert entry["status"] == "applied"
        assert entry["verb"] == "launched"
        assert entry["via"]["client"] == "Claude Code"
        assert entry["decision"]["answer"] == "approved"
        assert entry["decision"]["who"]["user_id"] == PERSON
        assert entry["decision"]["where"] == "qbrix"
        assert entry["asked_at"] <= entry["at"]
        assert entry["after"]["state"] == "live"
        assert await _state(api, loop) == "live"

    async def test_the_loops_history_shows_who_asked_and_who_approved(
        self, wired_app, api
    ):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)
        await api.post(f"/api/v1/changes/{change_id}/approve")

        resp = await api.get(f"/api/v1/loops/{loop['key']}/history")

        newest = resp.json()["changes"][0]
        assert newest["id"] == change_id
        assert newest["via"]["client"] == "Claude Code"
        assert newest["decision"]["answer"] == "approved"
        assert newest["decision"]["where"] == "qbrix"

    async def test_an_approved_create_gets_its_loop(self, wired_app, api):
        made = await wired_app.svc.act(
            TENANT,
            "loop.create",
            None,
            {"name": "Banner", "metric": "purchase", "options": OPTIONS},
            actor=replace(CLAUDE, level="ask"),
            reason="a new choice",
        )
        assert made.value is None

        resp = await api.post(f"/api/v1/changes/{made.change['id']}/approve")

        assert resp.status_code == 200, resp.text
        entry = resp.json()
        assert entry["target"]["key"] == "banner"
        found = await api.get("/api/v1/loops/banner")
        assert found.json()["id"] == entry["target"]["id"]

    async def test_a_change_the_loop_moved_past_is_refused_and_keeps_waiting(
        self, wired_app, api
    ):
        loop = await _live(api)
        change_id = await _ask(wired_app, "cycle.start", loop, {"options": NEW_OPTIONS})
        committed = await api.post(
            f"/api/v1/loops/{loop['key']}/commit", json={"option": "urgency"}
        )
        assert committed.status_code == 200, committed.text
        [commit] = (
            await api.get("/api/v1/changes", params={"kind": "loop.commit"})
        ).json()["changes"]

        resp = await api.post(f"/api/v1/changes/{change_id}/approve")

        assert resp.status_code == 409
        body = resp.json()
        assert body["code"] == "CHANGE_NO_LONGER_APPLIES"
        assert body["context"]["later_change_id"] == commit["id"]
        assert "still waits" in body["detail"]
        assert (await _get(api, change_id))["status"] == "waiting"

    async def test_an_unrelated_change_in_between_doesnt_block_it(self, wired_app, api):
        loop = await _live(api)
        change_id = await _ask(wired_app, "cycle.start", loop, {"options": NEW_OPTIONS})
        renamed = await api.patch(
            f"/api/v1/loops/{loop['key']}", json={"name": "Pricing CTA"}
        )
        assert renamed.status_code == 200, renamed.text

        resp = await api.post(f"/api/v1/changes/{change_id}/approve")

        assert resp.status_code == 200, resp.text
        assert resp.json()["after"]["cycle"]["number"] == 2

    async def test_a_change_is_answered_once(self, wired_app, api):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)
        await api.post(f"/api/v1/changes/{change_id}/approve")

        again = await api.post(f"/api/v1/changes/{change_id}/approve")
        declined = await api.post(f"/api/v1/changes/{change_id}/decline")

        assert again.status_code == 409
        assert again.json()["code"] == "CHANGE_ANSWERED"
        assert declined.json()["code"] == "CHANGE_ANSWERED"

    async def test_an_approved_undo_undoes(self, wired_app, api):
        loop = await _live(api)
        paused = await api.post(f"/api/v1/loops/{loop['key']}/pause", json={})
        assert paused.status_code == 200, paused.text
        [pause] = (
            await api.get("/api/v1/changes", params={"kind": "loop.pause"})
        ).json()["changes"]
        waiting = await wired_app.svc.undo_change(
            TENANT, pause["id"], actor=ASKING, reason="it was fine"
        )
        assert waiting["status"] == "waiting"
        assert waiting["undoes_id"] == pause["id"]
        assert await _state(api, loop) == "paused"

        resp = await api.post(f"/api/v1/changes/{waiting['id']}/approve")

        assert resp.status_code == 200, resp.text
        assert await _state(api, loop) == "live"
        assert (await _get(api, pause["id"]))["undone_by"]["id"] == waiting["id"]


class TestDeclining:

    async def test_a_decline_keeps_the_change_with_its_reason(self, wired_app, api):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)

        resp = await api.post(
            f"/api/v1/changes/{change_id}/decline",
            json={"reason": "not before legal approves the copy"},
        )

        assert resp.status_code == 200, resp.text
        entry = resp.json()
        assert entry["status"] == "declined"
        assert entry["verb"] == "asked to launch"
        assert entry["decision"]["answer"] == "declined"
        assert entry["decision"]["reason"] == "not before legal approves the copy"
        assert await _state(api, loop) == "draft"

    async def test_after_a_decline_the_kind_can_be_asked_again(self, wired_app, api):
        loop = await _draft(api)
        first = await _ask(wired_app, "loop.launch", loop)
        await api.post(f"/api/v1/changes/{first}/decline")

        second = await _ask(wired_app, "loop.launch", loop)

        assert second != first


class TestWhoAnswers:

    @pytest.mark.parametrize("role", ["member", "admin"])
    async def test_another_person_is_refused(self, wired_app, api, role):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-b", role=role):
            approve = await api.post(f"/api/v1/changes/{change_id}/approve")
            decline = await api.post(f"/api/v1/changes/{change_id}/decline")

        assert approve.status_code == 403
        assert approve.json()["code"] == "CHANGE_ANSWER_FORBIDDEN"
        assert decline.status_code == 403
        assert (await _get(api, change_id))["status"] == "waiting"

    async def test_a_viewer_cant_answer_even_their_own(self, wired_app, api):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id=PERSON, role="viewer"):
            resp = await api.post(f"/api/v1/changes/{change_id}/approve")

        assert resp.status_code == 403
        assert resp.json()["code"] == "INSUFFICIENT_SCOPES"

    async def test_a_key_is_refused(self, wired_app, api):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member(PERSON, api_key_id="key-1")
        try:
            resp = await api.post(f"/api/v1/changes/{change_id}/approve")
        finally:
            overrides.pop(get_actor)

        assert resp.status_code == 403

    async def test_the_connection_itself_is_refused(self, wired_app, api):
        loop = await _draft(api)
        change_id = await _ask(wired_app, "loop.launch", loop)

        with pytest.raises(ChangeAnswerForbiddenError):
            await wired_app.svc.approve_change(
                TENANT, change_id, actor=CLAUDE, role="member", where="Claude Code"
            )

    async def test_an_unknown_change_is_404(self, api):
        resp = await api.post("/api/v1/changes/nope/approve")

        assert resp.status_code == 404


class TestReading:

    async def test_the_list_holds_what_happened_unless_status_names_more(
        self, wired_app, api
    ):
        loop = await _draft(api)
        declined = await _ask(wired_app, "loop.launch", loop)
        await api.post(f"/api/v1/changes/{declined}/decline")
        waiting = await _ask(wired_app, "loop.launch", loop)

        default = await api.get("/api/v1/changes")
        asked = await api.get(
            "/api/v1/changes", params=[("status", "waiting"), ("status", "declined")]
        )

        assert {c["id"] for c in default.json()["changes"]}.isdisjoint(
            {declined, waiting}
        )
        assert [c["id"] for c in asked.json()["changes"]] == [waiting, declined]

    async def test_waiting_and_declined_arent_counted_or_undoable(self, wired_app, api):
        loop = await _draft(api)
        declined = await _ask(wired_app, "loop.launch", loop)
        await api.post(f"/api/v1/changes/{declined}/decline")
        await _ask(wired_app, "loop.launch", loop)
        before = (await api.get("/api/v1/changes/counts")).json()

        undoable = await api.get(
            "/api/v1/changes",
            params={"undoable": "true", "status": ["waiting", "declined"]},
        )
        undo = await api.post(f"/api/v1/changes/{declined}/undo", json={})

        assert before["total"] == 2
        assert undoable.json()["changes"] == []
        assert undo.status_code == 409
        assert "never applied" in undo.json()["detail"]

    async def test_a_waiting_change_doesnt_fold_into_an_applied_one(
        self, wired_app, api
    ):
        loop = await _live(api)
        await wired_app.svc.act(
            TENANT,
            "loop.rename",
            loop["id"],
            {"name": "Pricing CTA"},
            actor=replace(CLAUDE, level="notify"),
        )
        await _ask(wired_app, "loop.rename", loop, {"name": "Pricing button"})

        resp = await api.get(
            "/api/v1/changes",
            params=[
                ("kind", "loop.rename"),
                ("status", "applied"),
                ("status", "waiting"),
            ],
        )

        changes = resp.json()["changes"]
        assert [(c["status"], c["count"]) for c in changes] == [
            ("waiting", 1),
            ("applied", 1),
        ]

    async def test_a_waiting_change_isnt_the_loops_latest(self, wired_app, api):
        loop = await _draft(api)
        await _ask(wired_app, "loop.launch", loop)

        resp = await api.get(f"/api/v1/loops/{loop['key']}")

        assert resp.json()["latest_change"]["kind"] == "loop.create"
