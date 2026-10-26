"""integration tests for loops, a qbrix next surface.

invariants verified:
  a loop is created as a draft owned by the person behind the actor, with a
  key generated from its name (suffixed when taken) or a given one, at least
  two options, a metric, an engine and a fallback that defaults to the first
  option. launching a draft starts cycle 1 with the pinned engine, its exact
  version and the metric's version, goes live, and writes the cycle's runtime
  record under the cycle's id. the name changes at any time, the key only
  while draft. create, launch and rename are one change each; create and
  rename undo through the change log, and a metric a loop uses is kept.
  a live loop pauses (qbrix pauses it, with its evidence) and a person resumes
  it to the state it was paused from; each is one change, only the call that
  moves the state records one, both undo into the other, and live_since moves
  at launch and resume.
"""

from __future__ import annotations

import json
import math

import pytest
import pytest_asyncio

import proxysvc.config
from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.core.error import LoopStateError
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
UNDOER = Actor.member("user-undo", request_id="req-undo")
QBRIX = Actor(kind="qbrix", user_id="qbrix")
EVIDENCE = {"signal": "decision_errors", "value": 0.07, "calls": 412}

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
}

HEADLINE = {
    "name": "Checkout headline",
    "purpose": "find the headline that converts",
    "metric": "purchase",
    "options": [
        {"name": "Control", "config": {"text": "Buy now"}},
        {"name": "Urgency", "config": {"text": "Only today"}},
    ],
}


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


async def _create(client, **overrides) -> dict:
    resp = await client.post("/api/v1/loops", json={**HEADLINE, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _launch(client, ref: str) -> dict:
    resp = await client.post(f"/api/v1/loops/{ref}/launch")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _changes(wired_app, loop_id: str) -> list[dict]:
    return await wired_app.svc.list_changes(TENANT, "loop", loop_id)


def _unstamped(loop: dict) -> dict:
    """a loop without its timestamps, which sqlite reads back without a zone."""
    stripped = {k: v for k, v in loop.items() if k not in ("created_at", "updated_at")}
    if stripped.get("cycle"):
        stripped["cycle"] = {
            k: v for k, v in stripped["cycle"].items() if k != "started_at"
        }
    return stripped


class TestCreate:
    async def test_is_a_draft_with_a_key_from_its_name(self, loops):
        loop = await _create(loops)

        assert loop["state"] == "draft"
        assert loop["key"] == "checkout-headline"
        assert loop["name"] == "Checkout headline"
        assert loop["purpose"] == "find the headline that converts"
        assert loop["metric"]["name"] == "purchase"
        assert loop["engine"] == "spinoza"
        assert loop["cycle"] is None
        assert loop["paused_from"] is None

    async def test_options_keep_their_order_keys_and_config(self, loops):
        loop = await _create(loops)

        assert [(o["key"], o["name"], o["config"]) for o in loop["options"]] == [
            ("control", "Control", {"text": "Buy now"}),
            ("urgency", "Urgency", {"text": "Only today"}),
        ]

    async def test_the_fallback_is_the_first_option_unless_given(self, loops):
        default = await _create(loops)
        given = await _create(loops, fallback="urgency")

        assert default["fallback"] == "control"
        assert given["fallback"] == "urgency"

    async def test_a_second_loop_with_the_same_name_gets_a_suffix(self, loops):
        await _create(loops)
        second = await _create(loops)
        third = await _create(loops)

        assert second["key"] == "checkout-headline-2"
        assert third["key"] == "checkout-headline-3"

    async def test_keeps_a_given_key(self, loops):
        loop = await _create(loops, key="headline")

        assert loop["key"] == "headline"

    async def test_generated_option_keys_are_unique_in_order(self, loops):
        loop = await _create(
            loops,
            options=[{"name": "Variant"}, {"name": "Variant"}, {"name": "variant-2"}],
        )

        assert [o["key"] for o in loop["options"]] == [
            "variant",
            "variant-2",
            "variant-2-2",
        ]

    async def test_takes_the_metric_by_id(self, loops):
        metric = (await loops.get("/api/v1/metrics/purchase")).json()

        loop = await _create(loops, metric=metric["id"])

        assert loop["metric"] == {
            "id": metric["id"],
            "name": "purchase",
            "type": "conversion",
            "window_seconds": 86400,
        }

    async def test_the_owner_is_the_person_behind_the_actor(self, wired_app, loops):
        loop = await _create(loops)
        (change,) = await _changes(wired_app, loop["id"])

        assert loop["owner"]["id"] == change["actor"]["user_id"]

    async def test_the_owner_through_a_connection_is_its_member(self, wired_app, loops):
        via = Actor(
            kind="connection",
            user_id="user-ada",
            connection_id="conn-1",
            client_name="claude",
        )

        loop = (
            await wired_app.svc.create_loop(
                TENANT,
                name="Pricing page",
                metric="purchase",
                options=[{"name": "A"}, {"name": "B"}],
                actor=via,
            )
        ).value
        (change,) = await _changes(wired_app, loop["id"])

        assert loop["owner"] == {"id": "user-ada", "name": "former member"}
        assert change["actor"]["kind"] == "connection"
        assert change["actor"]["connection_id"] == "conn-1"


class TestRefusals:
    @pytest.mark.parametrize(
        "overrides, names",
        [
            ({"metric": None}, "a loop needs a metric"),
            ({"metric": "revenue"}, "no metric named or with id 'revenue'"),
            ({"options": [{"name": "Only"}]}, "at least 2 options, got 1"),
            ({"options": []}, "at least 2 options, got 0"),
            ({"key": "Checkout"}, "a loop key is what code calls"),
            ({"key": "-checkout"}, "a loop key is what code calls"),
            ({"key": "c" * 65}, "a loop key is what code calls"),
            ({"name": "  "}, "a loop needs a name"),
            (
                {"options": [{"name": "A", "key": "a"}, {"name": "B", "key": "a"}]},
                "two options have the key 'a'",
            ),
            (
                {"options": [{"name": "A", "key": "A!"}, {"name": "B"}]},
                "an option key is what code calls",
            ),
            (
                {"options": [{"name": "A"}, {"name": " "}]},
                "every option needs a name",
            ),
            ({"fallback": "missing"}, "the fallback 'missing' is not one of"),
            ({"engine": "thompson"}, "unknown engine 'thompson'"),
            ({"engine": "spinoza:9"}, "spinoza has no major 9"),
            ({"engine": "leibniz"}, "declare a context schema"),
        ],
    )
    async def test_names_the_problem(self, loops, overrides, names):
        resp = await loops.post("/api/v1/loops", json={**HEADLINE, **overrides})

        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "INVALID_LOOP"
        assert names in resp.json()["detail"]

    async def test_a_taken_key(self, loops):
        await _create(loops, key="headline")

        resp = await loops.post("/api/v1/loops", json={**HEADLINE, "key": "headline"})

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_KEY_TAKEN"
        assert "'headline' already exists" in resp.json()["detail"]

    async def test_a_refusal_writes_nothing(self, wired_app, loops):
        await loops.post("/api/v1/loops", json={**HEADLINE, "options": []})

        assert await wired_app.svc.get_loop(TENANT, "checkout-headline") is None


class TestLaunch:
    async def test_starts_cycle_one_pinned_to_the_major(self, loops):
        draft = await _create(loops)

        loop = await _launch(loops, draft["key"])

        assert loop["state"] == "live"
        assert loop["cycle"]["number"] == 1
        assert loop["cycle"]["engine"] == "spinoza:1"
        assert loop["cycle"]["engine_version"] == "1.0"
        assert loop["cycle"]["metric_version"] == "1.0"
        assert loop["cycle"]["ended_at"] is None

    async def test_an_exact_minor_stays_pinned(self, loops):
        draft = await _create(loops, engine="spinoza:1.0")

        loop = await _launch(loops, draft["id"])

        assert loop["cycle"]["engine"] == "spinoza:1.0"
        assert loop["cycle"]["engine_version"] == "1.0"

    async def test_records_the_metric_version_row(self, wired_app, loops):
        from qbrixstore.postgres.models import Cycle
        from qbrixstore.postgres.models import MetricVersion
        from qbrixstore.postgres.session import get_session
        from sqlalchemy import select

        loop = await _launch(loops, (await _create(loops))["key"])

        async with get_session() as session:
            cycle = await session.get(Cycle, loop["cycle"]["id"])
            version = (
                await session.execute(
                    select(MetricVersion).where(
                        MetricVersion.metric_id == loop["metric"]["id"]
                    )
                )
            ).scalar_one()
        assert cycle.metric_version_id == version.id
        assert [o["key"] for o in cycle.options] == ["control", "urgency"]

    async def test_writes_the_runtime_record_under_the_cycle(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])
        cycle_id = loop["cycle"]["id"]

        raw = await wired_app.fake_redis.get(
            f"qbrix:tenant:{TENANT}:experiment:{cycle_id}"
        )
        record = json.loads(raw)

        assert record["id"] == cycle_id
        assert record["loop_id"] == loop["id"]
        assert record["policy"] == "BetaTSPolicy"
        assert record["policy_params"] == {"alpha_prior": 1.0, "beta_prior": 1.0}
        assert record["enabled"] is True
        assert [
            (a["id"], a["name"], a["index"], a["metadata"])
            for a in record["pool"]["arms"]
        ] == [
            (loop["options"][0]["id"], "control", 0, {"text": "Buy now"}),
            (loop["options"][1]["id"], "urgency", 1, {"text": "Only today"}),
        ]

    async def test_a_draft_writes_no_runtime_record(self, wired_app, loops):
        await _create(loops)

        assert await wired_app.fake_redis.keys("qbrix:tenant:*:experiment:*") == []

    async def test_a_live_loop_is_refused(self, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/launch")

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_DRAFT"
        assert "only a draft can be launched" in resp.json()["detail"]

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.post("/api/v1/loops/nothing/launch")

        assert resp.status_code == 404
        assert resp.json()["code"] == "LOOP_NOT_FOUND"


class TestRename:
    async def test_the_name_and_key_of_a_draft(self, loops):
        draft = await _create(loops)

        resp = await loops.patch(
            f"/api/v1/loops/{draft['key']}",
            json={"name": "Checkout title", "key": "checkout-title"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Checkout title"
        assert resp.json()["key"] == "checkout-title"

    async def test_the_name_of_a_live_loop(self, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.patch(
            f"/api/v1/loops/{loop['id']}", json={"name": "Checkout title"}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Checkout title"
        assert resp.json()["key"] == "checkout-headline"

    async def test_the_key_of_a_live_loop_is_locked(self, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.patch(
            f"/api/v1/loops/{loop['key']}", json={"key": "checkout-title"}
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_DRAFT"
        assert "the key locks when the loop is launched" in resp.json()["detail"]

    async def test_the_same_key_on_a_live_loop_is_not_a_change_of_key(self, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.patch(
            f"/api/v1/loops/{loop['key']}",
            json={"name": "Checkout title", "key": loop["key"]},
        )

        assert resp.status_code == 200, resp.text

    async def test_a_taken_key(self, loops):
        await _create(loops, key="taken")
        draft = await _create(loops)

        resp = await loops.patch(f"/api/v1/loops/{draft['key']}", json={"key": "taken"})

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_KEY_TAKEN"

    @pytest.mark.parametrize(
        "body, names",
        [
            ({}, "a rename needs a new name, a new key or both"),
            ({"name": " "}, "a loop needs a name"),
            ({"key": "Not A Key"}, "a loop key is what code calls"),
        ],
    )
    async def test_names_the_problem(self, loops, body, names):
        draft = await _create(loops)

        resp = await loops.patch(f"/api/v1/loops/{draft['key']}", json=body)

        assert resp.status_code == 400
        assert names in resp.json()["detail"]

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.patch("/api/v1/loops/nothing", json={"name": "x"})

        assert resp.status_code == 404


class TestChange:
    async def test_create_is_one_change_with_its_actor_and_after(
        self, wired_app, loops
    ):
        resp = await loops.post(
            "/api/v1/loops", json=HEADLINE, headers={"X-Request-ID": "req-loop"}
        )
        loop = resp.json()

        (change,) = await _changes(wired_app, loop["id"])

        assert change["kind"] == "loop.create"
        assert change["target_type"] == "loop"
        assert change["actor"]["kind"] == "member"
        assert change["request_id"] == "req-loop"
        assert change["before"] is None
        assert change["after"] == loop
        assert change["undoable"] is True

    async def test_launch_is_one_change_with_before_and_after(self, wired_app, loops):
        draft = await _create(loops)
        loop = await _launch(loops, draft["key"])

        launch, _ = await _changes(wired_app, loop["id"])

        assert launch["kind"] == "loop.launch"
        assert launch["before"]["state"] == "draft"
        assert launch["after"] == loop
        assert launch["undoable"] is False

    async def test_rename_is_one_change_with_before_and_after(self, wired_app, loops):
        draft = await _create(loops)
        resp = await loops.patch(
            f"/api/v1/loops/{draft['key']}", json={"name": "Checkout title"}
        )

        rename, _ = await _changes(wired_app, draft["id"])

        assert rename["kind"] == "loop.rename"
        assert rename["before"]["name"] == "Checkout headline"
        assert rename["after"] == resp.json()

    async def test_a_refused_launch_records_nothing(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])
        await loops.post(f"/api/v1/loops/{loop['key']}/launch")

        assert len(await _changes(wired_app, loop["id"])) == 2


class TestUndo:
    async def test_undo_of_create_deletes_the_draft(self, wired_app, loops):
        draft = await _create(loops)
        (create,) = await _changes(wired_app, draft["id"])

        undo = await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        assert undo["kind"] == "loop.delete"
        assert undo["undoes_id"] == create["id"]
        assert _unstamped(undo["before"]) == _unstamped(draft)
        assert await wired_app.svc.get_loop(TENANT, draft["id"]) is None

    async def test_the_key_is_free_again_after_undo(self, wired_app, loops):
        draft = await _create(loops)
        (create,) = await _changes(wired_app, draft["id"])
        await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        again = await _create(loops)

        assert again["key"] == "checkout-headline"

    async def test_undo_of_create_after_launch_is_refused(self, wired_app, loops):
        draft = await _create(loops)
        await _launch(loops, draft["key"])
        _, create = await _changes(wired_app, draft["id"])

        with pytest.raises(ChangeConflictError, match="loop.launch"):
            await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

    async def test_undo_of_rename_restores_the_name_and_key(self, wired_app, loops):
        draft = await _create(loops)
        await loops.patch(
            f"/api/v1/loops/{draft['key']}",
            json={"name": "Checkout title", "key": "checkout-title"},
        )
        rename, _ = await _changes(wired_app, draft["id"])

        undo = await wired_app.svc.undo_change(TENANT, rename["id"], actor=UNDOER)
        loop = await wired_app.svc.get_loop(TENANT, draft["id"])

        assert undo["kind"] == "loop.rename"
        assert undo["undoes_id"] == rename["id"]
        assert (loop["name"], loop["key"]) == ("Checkout headline", "checkout-headline")

    async def test_undo_of_rename_on_a_live_loop(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])
        await loops.patch(f"/api/v1/loops/{loop['key']}", json={"name": "Title"})
        rename, *_ = await _changes(wired_app, loop["id"])

        await wired_app.svc.undo_change(TENANT, rename["id"], actor=UNDOER)

        restored = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert restored["name"] == "Checkout headline"

    async def test_undo_of_a_draft_rename_after_launch_is_refused(
        self, wired_app, loops
    ):
        draft = await _create(loops)
        await loops.patch(f"/api/v1/loops/{draft['key']}", json={"key": "headline"})
        await _launch(loops, "headline")
        _, rename, _ = await _changes(wired_app, draft["id"])

        with pytest.raises(ChangeConflictError, match="loop.launch"):
            await wired_app.svc.undo_change(TENANT, rename["id"], actor=UNDOER)

    async def test_launch_cannot_be_undone(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])
        launch, _ = await _changes(wired_app, loop["id"])

        with pytest.raises(ChangeNotUndoableError, match="launching a loop"):
            await wired_app.svc.undo_change(TENANT, launch["id"], actor=UNDOER)

    async def test_the_delete_cannot_be_undone(self, wired_app, loops):
        draft = await _create(loops)
        (create,) = await _changes(wired_app, draft["id"])
        delete = await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        with pytest.raises(ChangeNotUndoableError, match="deleting a loop"):
            await wired_app.svc.undo_change(TENANT, delete["id"], actor=UNDOER)


async def _pause(wired_app, ref: str, actor: Actor = QBRIX, **kwargs) -> dict:
    return await wired_app.svc._loop_service.pause_loop(
        TENANT, ref, actor=actor, **kwargs
    )


async def _paused(wired_app, loops) -> dict:
    loop = await _launch(loops, (await _create(loops))["key"])
    return await _pause(wired_app, loop["key"], evidence=EVIDENCE)


class TestPause:
    async def test_a_live_loop_pauses_from_live(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        paused = await _pause(wired_app, loop["key"])

        assert (paused["state"], paused["paused_from"]) == ("paused", "live")
        assert paused["live_since"] == loop["live_since"]

    async def test_is_a_change_by_qbrix_with_its_evidence(self, wired_app, loops):
        loop = await _paused(wired_app, loops)

        pause, *_ = await _changes(wired_app, loop["id"])

        assert pause["kind"] == "loop.pause"
        assert pause["actor"]["kind"] == "qbrix"
        assert pause["evidence"] == EVIDENCE
        assert pause["before"]["state"] == "live"
        assert pause["after"] == loop
        assert pause["undoable"] is True

    async def test_a_pause_that_loses_the_race_records_nothing(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launch(loops, (await _create(loops))["key"])
        resolve = LoopRepository.resolve
        read = []

        async def another_pause_lands(repo, ref):
            found = await resolve(repo, ref)
            read.append(found.state)
            await repo.transition(
                found.id, from_state="live", state="paused", paused_from="live"
            )
            return found

        with monkeypatch.context() as patch:
            patch.setattr(LoopRepository, "resolve", another_pause_lands)
            with pytest.raises(LoopStateError, match="is paused"):
                await _pause(wired_app, loop["key"])

        assert read == ["live"]
        kinds = [c["kind"] for c in await _changes(wired_app, loop["id"])]
        assert "loop.pause" not in kinds

    @pytest.mark.parametrize("launch", [False, True])
    async def test_only_a_live_loop_pauses(self, wired_app, loops, launch):
        loop = await _create(loops)
        if launch:
            loop = await _pause(wired_app, (await _launch(loops, loop["key"]))["key"])

        with pytest.raises(LoopStateError, match=f"is {loop['state']}"):
            await _pause(wired_app, loop["key"])

    async def test_writes_the_paused_route(self, wired_app, loops):
        loop = await _paused(wired_app, loops)

        route = await wired_app.svc._loop_select_service._routes.get(
            TENANT, loop["key"]
        )

        assert route.state == "paused"


class TestResume:
    async def test_returns_to_where_it_was_paused_from(self, wired_app, loops):
        loop = await _paused(wired_app, loops)

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/resume")

        assert resp.status_code == 200, resp.text
        resumed = resp.json()["loop"]
        assert (resumed["state"], resumed["paused_from"]) == ("live", None)
        assert resumed["live_since"] > loop["live_since"]

    async def test_says_when_serving_moves(self, wired_app, loops):
        loop = await _paused(wired_app, loops)

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/resume")

        expected = math.ceil(proxysvc.config.settings.experiment_cache_ttl)
        assert resp.json()["serving_within_seconds"] == expected

    async def test_is_a_change_by_the_person_with_their_reason(self, wired_app, loops):
        loop = await _paused(wired_app, loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/resume",
            json={"reason": "motor is back"},
            headers={"X-Request-ID": "req-resume"},
        )
        resume, *_ = await _changes(wired_app, loop["id"])

        assert resume["kind"] == "loop.resume"
        assert resume["actor"]["kind"] == "member"
        assert resume["reason"] == "motor is back"
        assert resume["request_id"] == "req-resume"
        assert resume["before"]["state"] == "paused"
        assert resume["after"] == resp.json()["loop"]

    async def test_needs_no_body(self, wired_app, loops):
        loop = await _paused(wired_app, loops)

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/resume")
        resume, *_ = await _changes(wired_app, loop["id"])

        assert resp.status_code == 200
        assert resume["reason"] is None

    async def test_writes_the_live_route(self, wired_app, loops):
        loop = await _paused(wired_app, loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/resume")

        route = await wired_app.svc._loop_select_service._routes.get(
            TENANT, loop["key"]
        )

        assert route.state == "live"

    @pytest.mark.parametrize("launch", [False, True])
    async def test_a_loop_that_isnt_paused_is_refused(self, wired_app, loops, launch):
        loop = await _create(loops)
        if launch:
            loop = await _launch(loops, loop["key"])

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/resume")

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_PAUSED"
        assert f"is {loop['state']}" in resp.text
        assert len(await _changes(wired_app, loop["id"])) == (2 if launch else 1)

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.post("/api/v1/loops/nothing/resume")

        assert resp.status_code == 404

    async def test_a_viewer_is_refused(self, wired_app, loops):
        loop = await _paused(wired_app, loops)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/resume")

        assert resp.status_code == 403
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "paused"

    async def test_an_api_key_is_refused(self, wired_app, loops):
        loop = await _paused(wired_app, loops)
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-x", api_key_id="key-1")
        try:
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/resume")
        finally:
            del overrides[get_actor]

        assert resp.status_code == 403
        assert "api key" in resp.text
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "paused"


class TestLiveSince:
    async def test_a_draft_has_none(self, loops):
        assert (await _create(loops))["live_since"] is None

    async def test_is_set_at_launch(self, loops):
        assert (await _launch(loops, (await _create(loops))["key"]))["live_since"]


class TestUndoPauseResume:
    async def test_undo_of_resume_pauses_again_as_the_undoers_change(
        self, wired_app, loops
    ):
        loop = await _paused(wired_app, loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/resume")
        resume, *_ = await _changes(wired_app, loop["id"])

        undo = await wired_app.svc.undo_change(
            TENANT, resume["id"], actor=UNDOER, reason="not yet"
        )
        after = await wired_app.svc.get_loop(TENANT, loop["id"])

        assert undo["kind"] == "loop.pause"
        assert undo["undoes_id"] == resume["id"]
        assert undo["actor"]["kind"] == "member"
        assert undo["actor"]["user_id"] == UNDOER.user_id
        assert undo["reason"] == "not yet"
        assert (after["state"], after["paused_from"]) == ("paused", "live")

    async def test_undo_of_pause_resumes(self, wired_app, loops):
        loop = await _paused(wired_app, loops)
        pause, *_ = await _changes(wired_app, loop["id"])

        undo = await wired_app.svc.undo_change(TENANT, pause["id"], actor=UNDOER)
        after = await wired_app.svc.get_loop(TENANT, loop["id"])

        assert undo["kind"] == "loop.resume"
        assert undo["undoes_id"] == pause["id"]
        assert after["state"] == "live"
        assert after["live_since"] > loop["live_since"]

    async def test_each_undo_is_its_own_change(self, wired_app, loops):
        loop = await _paused(wired_app, loops)
        pause, *_ = await _changes(wired_app, loop["id"])
        resume = await wired_app.svc.undo_change(TENANT, pause["id"], actor=UNDOER)

        await wired_app.svc.undo_change(TENANT, resume["id"], actor=UNDOER)

        kinds = [c["kind"] for c in await _changes(wired_app, loop["id"])]
        assert kinds == [
            "loop.pause",
            "loop.resume",
            "loop.pause",
            "loop.launch",
            "loop.create",
        ]

    async def test_undo_of_a_pause_after_a_resume_is_refused(self, wired_app, loops):
        loop = await _paused(wired_app, loops)
        pause, *_ = await _changes(wired_app, loop["id"])
        await loops.post(f"/api/v1/loops/{loop['key']}/resume")

        with pytest.raises(ChangeConflictError, match="loop.resume"):
            await wired_app.svc.undo_change(TENANT, pause["id"], actor=UNDOER)


class TestMetricInUse:
    async def test_a_metric_a_loop_uses_is_kept(self, wired_app, loops):
        await _create(loops)
        metric = (await loops.get("/api/v1/metrics/purchase")).json()
        (create,) = await wired_app.svc.list_changes(TENANT, "metric", metric["id"])

        with pytest.raises(ChangeConflictError, match="'checkout-headline' uses"):
            await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        assert (await loops.get("/api/v1/metrics/purchase")).status_code == 200
