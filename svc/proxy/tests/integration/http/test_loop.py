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
  a live or committed loop pauses (qbrix with its evidence, or a person with
  none, keeping a committed loop's option) and a person resumes it to the
  state it was paused from; each is one change, only the call that
  moves the state records one, both undo into the other, and live_since moves
  at launch and resume. a person commits a live loop to one of its cycle's
  options and reopens it to live in the same cycle; each is one change, each
  undoes into the other, and a rename recorded before a loop had a committed
  option still undoes. a person retires a live, committed or paused loop: its
  cycle ends, its route serves the fallback, its key stays taken and its reads
  stay open; a draft or retired loop is refused with what to do instead,
  and retiring can't be undone. a person starts a new cycle of a live or
  paused loop with new options, a new engine or both, or resets it with the
  same ones: the current cycle ends, the next one pins its engine, version
  and metric version, the loop's options become the cycle's (an option that
  stays keeps its id), the fallback stays if its option does and is named
  otherwise, the route serves the new cycle, the earlier cycle's record and
  results stay, a paused loop stays paused, and neither can be undone. a
  draft, committed, paused-from-committed or retired loop is refused with
  what to do instead. a loop decides for everyone until its delivery
  changes; a delivery change sets the parts it names and keeps the rest,
  can set the fallback, is one change with before and after, writes the
  route, and undoes. any state but retired can change it, and a change that
  can't apply is refused with why.
"""

from __future__ import annotations

import json
import math

import pytest
import pytest_asyncio

import proxysvc.config
from qbrixstore.clickhouse.ledger import PropertyArrival
from qbrixstore.postgres import session as session_module
from qbrixstore.postgres.models import Change

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
QBRIX = Actor.qbrix()
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

    async def test_a_generated_key_skips_the_reserved_one(self, loops):
        loop = await _create(loops, name="New")

        assert loop["key"] == "new-2"

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
            ({"key": "new"}, "a loop can't have the key 'new'"),
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
            ({"engine": "leibniz"}, "declare the context first"),
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
            ({"key": "new"}, "a loop can't have the key 'new'"),
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


class TestDelete:
    @pytest.mark.parametrize("by", ["key", "id"])
    async def test_a_draft_is_deleted_as_one_change(self, wired_app, loops, by):
        draft = await _create(loops)

        resp = await loops.delete(
            f"/api/v1/loops/{draft[by]}", headers={"X-Request-ID": "req-delete"}
        )

        assert resp.status_code == 204, resp.text
        assert await wired_app.svc.get_loop(TENANT, draft["id"]) is None
        delete, _ = await _changes(wired_app, draft["id"])
        assert delete["kind"] == "loop.delete"
        assert delete["actor"]["kind"] == "member"
        assert delete["request_id"] == "req-delete"
        assert _unstamped(delete["before"]) == _unstamped(draft)
        assert delete["undoable"] is False

    async def test_its_link_is_not_found_and_its_key_is_free(self, loops):
        draft = await _create(loops)
        await loops.delete(f"/api/v1/loops/{draft['key']}")

        assert (await loops.get(f"/api/v1/loops/{draft['key']}")).status_code == 404
        assert (await _create(loops))["key"] == draft["key"]

    async def test_a_launched_loop_is_refused_and_untouched(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.delete(f"/api/v1/loops/{loop['key']}")

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_DRAFT"
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"
        assert len(await _changes(wired_app, loop["id"])) == 2

    async def test_an_unknown_loop_is_not_found(self, loops):
        assert (await loops.delete("/api/v1/loops/nothing")).status_code == 404

    async def test_another_workspaces_draft_is_not_found(self, wired_app, loops):
        draft = await _create(loops)

        with as_tenant(wired_app.app, tenant_id="tenant-other"):
            resp = await loops.delete(f"/api/v1/loops/{draft['key']}")

        assert resp.status_code == 404
        assert await wired_app.svc.get_loop(TENANT, draft["id"]) is not None

    async def test_a_viewer_is_refused(self, wired_app, loops):
        draft = await _create(loops)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await loops.delete(f"/api/v1/loops/{draft['key']}")

        assert resp.status_code == 403
        assert await wired_app.svc.get_loop(TENANT, draft["id"]) is not None


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
    return (
        await wired_app.svc._loop_service.pause_loop(TENANT, ref, actor=actor, **kwargs)
    ).value


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


async def _commit(client, ref: str, option: str = "urgency", **body) -> dict:
    resp = await client.post(
        f"/api/v1/loops/{ref}/commit", json={"option": option, **body}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _committed(loops) -> dict:
    loop = await _launch(loops, (await _create(loops))["key"])
    return await _commit(loops, loop["key"])


async def _route(wired_app, ref: str):
    return await wired_app.svc._loop_select_service._routes.get(TENANT, ref)


class TestCommit:
    async def test_a_live_loop_commits_to_one_option(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        committed = await _commit(loops, loop["key"])

        assert (committed["state"], committed["committed"]) == ("committed", "urgency")
        assert committed["cycle"] == loop["cycle"]
        assert committed["live_since"] == loop["live_since"]

    async def test_a_live_loop_is_committed_to_nothing(self, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        assert loop["committed"] is None

    async def test_is_a_change_by_the_person_with_their_reason(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/commit",
            json={"option": "urgency", "reason": "urgency won"},
            headers={"X-Request-ID": "req-commit"},
        )
        commit, *_ = await _changes(wired_app, loop["id"])

        assert commit["kind"] == "loop.commit"
        assert commit["actor"]["kind"] == "member"
        assert commit["reason"] == "urgency won"
        assert commit["request_id"] == "req-commit"
        assert commit["before"]["state"] == "live"
        assert commit["before"]["committed"] is None
        assert commit["after"] == resp.json()
        assert commit["undoable"] is True

    async def test_writes_the_committed_route(self, wired_app, loops):
        loop = await _committed(loops)

        route = await _route(wired_app, loop["key"])

        assert route.state == "committed"
        assert route.options[route.committed].key == "urgency"

    @pytest.mark.parametrize("state", ["draft", "paused", "committed"])
    async def test_only_a_live_loop_commits(self, wired_app, loops, state):
        loop = await _create(loops)
        if state != "draft":
            loop = await _launch(loops, loop["key"])
        if state == "paused":
            loop = await _pause(wired_app, loop["key"])
        if state == "committed":
            loop = await _commit(loops, loop["key"])
        before = len(await _changes(wired_app, loop["id"]))

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/commit", json={"option": "control"}
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_LIVE"
        assert f"is {state}" in resp.text
        assert len(await _changes(wired_app, loop["id"])) == before

    async def test_an_unknown_option_is_refused_with_the_options(
        self, wired_app, loops
    ):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/commit", json={"option": "nope"}
        )

        assert resp.status_code in (400, 422)
        assert "(control, urgency)" in resp.text
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"
        assert len(await _changes(wired_app, loop["id"])) == 2

    async def test_a_commit_that_loses_the_race_records_nothing(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launch(loops, (await _create(loops))["key"])
        resolve = LoopRepository.resolve

        async def a_pause_lands(repo, ref):
            found = await resolve(repo, ref)
            await repo.transition(
                found.id, from_state="live", state="paused", paused_from="live"
            )
            return found

        with monkeypatch.context() as patch:
            patch.setattr(LoopRepository, "resolve", a_pause_lands)
            resp = await loops.post(
                f"/api/v1/loops/{loop['key']}/commit", json={"option": "urgency"}
            )

        assert resp.status_code == 409
        assert "is paused" in resp.text
        kinds = [c["kind"] for c in await _changes(wired_app, loop["id"])]
        assert "loop.commit" not in kinds

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.post("/api/v1/loops/nothing/commit", json={"option": "a"})

        assert resp.status_code == 404

    async def test_a_viewer_is_refused(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await loops.post(
                f"/api/v1/loops/{loop['key']}/commit", json={"option": "urgency"}
            )

        assert resp.status_code == 403
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"

    async def test_an_api_key_is_refused(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-x", api_key_id="key-1")
        try:
            resp = await loops.post(
                f"/api/v1/loops/{loop['key']}/commit", json={"option": "urgency"}
            )
        finally:
            del overrides[get_actor]

        assert resp.status_code == 403
        assert "api key" in resp.text
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"


class TestReopen:
    async def test_returns_to_live_in_the_same_cycle(self, wired_app, loops):
        loop = await _committed(loops)

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/reopen")

        assert resp.status_code == 200, resp.text
        reopened = resp.json()
        assert (reopened["state"], reopened["committed"]) == ("live", None)
        assert reopened["cycle"] == loop["cycle"]
        assert reopened["live_since"] == loop["live_since"]

    async def test_is_a_change_by_the_person_with_their_reason(self, wired_app, loops):
        loop = await _committed(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/reopen", json={"reason": "new season"}
        )
        reopen, *_ = await _changes(wired_app, loop["id"])

        assert reopen["kind"] == "loop.reopen"
        assert reopen["reason"] == "new season"
        assert reopen["before"]["committed"] == "urgency"
        assert reopen["after"] == resp.json()

    async def test_writes_the_live_route(self, wired_app, loops):
        loop = await _committed(loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/reopen")

        route = await _route(wired_app, loop["key"])

        assert (route.state, route.committed) == ("live", None)

    @pytest.mark.parametrize("launch", [False, True])
    async def test_a_loop_that_isnt_committed_is_refused(
        self, wired_app, loops, launch
    ):
        loop = await _create(loops)
        if launch:
            loop = await _launch(loops, loop["key"])

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/reopen")

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_COMMITTED"
        assert f"is {loop['state']}" in resp.text

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.post("/api/v1/loops/nothing/reopen")

        assert resp.status_code == 404


class TestUndoCommitReopen:
    async def test_undo_of_commit_reopens(self, wired_app, loops):
        loop = await _committed(loops)
        commit, *_ = await _changes(wired_app, loop["id"])

        undo = await wired_app.svc.undo_change(TENANT, commit["id"], actor=UNDOER)
        after = await wired_app.svc.get_loop(TENANT, loop["id"])

        assert undo["kind"] == "loop.reopen"
        assert undo["undoes_id"] == commit["id"]
        assert (after["state"], after["committed"]) == ("live", None)

    async def test_undo_of_reopen_commits_to_the_same_option(self, wired_app, loops):
        loop = await _committed(loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/reopen")
        reopen, *_ = await _changes(wired_app, loop["id"])

        undo = await wired_app.svc.undo_change(TENANT, reopen["id"], actor=UNDOER)
        after = await wired_app.svc.get_loop(TENANT, loop["id"])

        assert undo["kind"] == "loop.commit"
        assert undo["actor"]["user_id"] == UNDOER.user_id
        assert (after["state"], after["committed"]) == ("committed", "urgency")
        route = await _route(wired_app, loop["key"])
        assert route.options[route.committed].key == "urgency"

    async def test_undo_of_a_commit_after_a_reopen_is_refused(self, wired_app, loops):
        loop = await _committed(loops)
        commit, *_ = await _changes(wired_app, loop["id"])
        await loops.post(f"/api/v1/loops/{loop['key']}/reopen")

        with pytest.raises(ChangeConflictError, match="loop.reopen"):
            await wired_app.svc.undo_change(TENANT, commit["id"], actor=UNDOER)

    async def test_a_rename_recorded_before_committed_existed_still_undoes(
        self, wired_app, loops
    ):
        loop = await _launch(loops, (await _create(loops))["key"])
        await loops.patch(f"/api/v1/loops/{loop['key']}", json={"name": "Headline"})
        rename, *_ = await _changes(wired_app, loop["id"])
        async with session_module.get_session() as session:
            change = await session.get(Change, rename["id"])
            change.before = {k: v for k, v in change.before.items() if k != "committed"}
            change.after = {k: v for k, v in change.after.items() if k != "committed"}

        undo = await wired_app.svc.undo_change(TENANT, rename["id"], actor=UNDOER)

        assert undo["kind"] == "loop.rename"
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["name"] == HEADLINE[
            "name"
        ]


async def _retire(client, ref: str, **body) -> dict:
    resp = await client.post(f"/api/v1/loops/{ref}/retire", json=body or None)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _retired(loops) -> dict:
    loop = await _launch(loops, (await _create(loops))["key"])
    return await _retire(loops, loop["key"])


class TestRetire:
    async def test_a_live_loop_retires_and_its_cycle_ends(self, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        retired = await _retire(loops, loop["key"])

        assert retired["state"] == "retired"
        assert retired["key"] == loop["key"]
        assert retired["cycle"]["number"] == loop["cycle"]["number"]
        assert loop["cycle"]["ended_at"] is None
        assert retired["cycle"]["ended_at"] is not None

    @pytest.mark.parametrize("committed", [False, True])
    async def test_a_paused_loop_retires_without_resuming(
        self, wired_app, loops, committed
    ):
        loop = await (_committed(loops) if committed else _launched(loops))
        await _pause_by_hand(loops, loop["key"])

        retired = await _retire(loops, loop["key"])

        assert (retired["state"], retired["paused_from"]) == ("retired", None)
        assert retired["committed"] is None
        kinds = [c["kind"] for c in await _changes(wired_app, loop["id"])]
        assert kinds[:2] == ["loop.retire", "loop.pause"]

    async def test_a_committed_loop_retires_and_drops_its_option(self, loops):
        loop = await _committed(loops)

        retired = await _retire(loops, loop["key"])

        assert (retired["state"], retired["committed"]) == ("retired", None)

    async def test_is_a_change_by_the_person_that_cant_be_undone(
        self, wired_app, loops
    ):
        loop = await _launch(loops, (await _create(loops))["key"])

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/retire",
            json={"reason": "built into the page"},
            headers={"X-Request-ID": "req-retire"},
        )
        retire, *_ = await _changes(wired_app, loop["id"])

        assert retire["kind"] == "loop.retire"
        assert retire["actor"]["kind"] == "member"
        assert retire["reason"] == "built into the page"
        assert retire["request_id"] == "req-retire"
        assert retire["before"]["state"] == "live"
        assert retire["after"] == resp.json()
        assert retire["undoable"] is False

    async def test_needs_no_body(self, wired_app, loops):
        loop = await _retired(loops)

        retire, *_ = await _changes(wired_app, loop["id"])

        assert retire["reason"] is None

    async def test_writes_the_retired_route(self, wired_app, loops):
        loop = await _committed(loops)
        await _retire(loops, loop["key"])

        route = await _route(wired_app, loop["key"])

        assert (route.state, route.committed) == ("retired", None)

    @pytest.mark.parametrize(
        "state, fix",
        [
            ("draft", "delete the draft instead"),
            ("retired", "it is retired already"),
        ],
    )
    async def test_a_draft_or_retired_loop_is_refused(
        self, wired_app, loops, state, fix
    ):
        loop = await _create(loops)
        if state != "draft":
            loop = await _launch(loops, loop["key"])
        if state == "retired":
            loop = await _retire(loops, loop["key"])
        before = len(await _changes(wired_app, loop["id"]))

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/retire")

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_RETIRABLE"
        assert f"is {state}; {fix}" in resp.text
        assert len(await _changes(wired_app, loop["id"])) == before

    async def test_a_retire_that_loses_the_race_records_nothing(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launch(loops, (await _create(loops))["key"])
        resolve = LoopRepository.resolve

        async def a_pause_lands(repo, ref):
            found = await resolve(repo, ref)
            await repo.transition(
                found.id, from_state="live", state="paused", paused_from="live"
            )
            return found

        with monkeypatch.context() as patch:
            patch.setattr(LoopRepository, "resolve", a_pause_lands)
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/retire")

        assert resp.status_code == 409
        assert "is paused" in resp.text
        after = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert after["cycle"]["ended_at"] is None
        kinds = [c["kind"] for c in await _changes(wired_app, loop["id"])]
        assert "loop.retire" not in kinds

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.post("/api/v1/loops/nothing/retire")

        assert resp.status_code == 404

    async def test_a_viewer_is_refused(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/retire")

        assert resp.status_code == 403
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"

    async def test_an_api_key_is_refused(self, wired_app, loops):
        loop = await _launch(loops, (await _create(loops))["key"])
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-x", api_key_id="key-1")
        try:
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/retire")
        finally:
            del overrides[get_actor]

        assert resp.status_code == 403
        assert "api key" in resp.text
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"


class TestRetiredReads:
    async def test_its_loop_cycles_and_history_stay_readable(self, loops):
        loop = await _retired(loops)

        got = await loops.get(f"/api/v1/loops/{loop['key']}")
        cycles = await loops.get(f"/api/v1/loops/{loop['key']}/cycles")
        history = await loops.get(f"/api/v1/loops/{loop['key']}/history")

        assert [r.status_code for r in (got, cycles, history)] == [200] * 3
        assert got.json()["state"] == "retired"
        assert cycles.json()["cycles"][0]["ended_at"] is not None
        assert history.json()["changes"][0]["kind"] == "loop.retire"

    async def test_the_list_filters_by_retired(self, loops):
        loop = await _retired(loops)
        await _create(loops, name="Pricing CTA")

        resp = await loops.get("/api/v1/loops", params={"state": "retired"})

        assert resp.status_code == 200, resp.text
        assert [row["key"] for row in resp.json()["loops"]] == [loop["key"]]

    async def test_its_key_stays_taken(self, loops):
        loop = await _retired(loops)

        resp = await loops.post("/api/v1/loops", json={**HEADLINE, "key": loop["key"]})

        assert resp.status_code == 409


class TestUndoRetire:
    async def test_retire_cannot_be_undone(self, wired_app, loops):
        loop = await _retired(loops)
        retire, *_ = await _changes(wired_app, loop["id"])

        with pytest.raises(ChangeNotUndoableError, match="create a new loop"):
            await wired_app.svc.undo_change(TENANT, retire["id"], actor=UNDOER)

        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "retired"

    async def test_undo_over_http_says_why(self, wired_app, loops):
        loop = await _retired(loops)
        retire, *_ = await _changes(wired_app, loop["id"])

        resp = await loops.post(f"/api/v1/changes/{retire['id']}/undo")

        assert resp.status_code == 409
        assert "the choice has left the product" in resp.text

    async def test_undo_of_a_commit_before_retire_is_refused(self, wired_app, loops):
        loop = await _committed(loops)
        commit, *_ = await _changes(wired_app, loop["id"])
        await _retire(loops, loop["key"])

        with pytest.raises(ChangeConflictError, match="loop.retire"):
            await wired_app.svc.undo_change(TENANT, commit["id"], actor=UNDOER)


async def _launched(loops) -> dict:
    return await _launch(loops, (await _create(loops))["key"])


async def _pause_by_hand(client, ref: str, **body) -> dict:
    resp = await client.post(f"/api/v1/loops/{ref}/pause", json=body or None)
    assert resp.status_code == 200, resp.text
    return resp.json()["loop"]


class TestPauseByHand:
    async def test_a_live_loop_pauses_from_live(self, wired_app, loops):
        loop = await _launched(loops)

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/pause")

        assert resp.status_code == 200, resp.text
        paused = resp.json()["loop"]
        assert (paused["state"], paused["paused_from"]) == ("paused", "live")
        expected = math.ceil(proxysvc.config.settings.experiment_cache_ttl)
        assert resp.json()["serving_within_seconds"] == expected
        assert (await _route(wired_app, loop["key"])).state == "paused"

    async def test_a_committed_loop_pauses_and_keeps_its_option(self, wired_app, loops):
        loop = await _committed(loops)

        paused = await _pause_by_hand(loops, loop["key"])

        assert (paused["state"], paused["paused_from"]) == ("paused", "committed")
        assert paused["committed"] == "urgency"
        route = await _route(wired_app, loop["key"])
        assert route.state == "paused"
        assert route.options[route.committed].key == "urgency"

    async def test_is_a_change_by_the_person_without_evidence(self, wired_app, loops):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/pause",
            json={"reason": "checkout bug"},
            headers={"X-Request-ID": "req-pause"},
        )
        pause, *_ = await _changes(wired_app, loop["id"])

        assert pause["kind"] == "loop.pause"
        assert pause["actor"]["kind"] == "member"
        assert pause["reason"] == "checkout bug"
        assert pause["request_id"] == "req-pause"
        assert pause["evidence"] is None
        assert pause["after"] == resp.json()["loop"]
        assert pause["undoable"] is True

    @pytest.mark.parametrize(
        "state, fix",
        [
            ("draft", "a draft serves its fallback until it is launched"),
            ("paused", "it is paused already"),
            ("retired", "a retired loop serves its fallback already"),
        ],
    )
    async def test_only_a_live_or_committed_loop_pauses(
        self, wired_app, loops, state, fix
    ):
        loop = await _create(loops)
        if state != "draft":
            loop = await _launch(loops, loop["key"])
        if state == "paused":
            loop = await _pause_by_hand(loops, loop["key"])
        if state == "retired":
            loop = await _retire(loops, loop["key"])
        before = len(await _changes(wired_app, loop["id"]))

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/pause")

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_NOT_PAUSABLE"
        assert f"is {state}; {fix}" in resp.text
        assert len(await _changes(wired_app, loop["id"])) == before

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.post("/api/v1/loops/nothing/pause")

        assert resp.status_code == 404

    async def test_a_viewer_is_refused(self, wired_app, loops):
        loop = await _launched(loops)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/pause")

        assert resp.status_code == 403
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"

    async def test_an_api_key_is_refused(self, wired_app, loops):
        loop = await _launched(loops)
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-x", api_key_id="key-1")
        try:
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/pause")
        finally:
            del overrides[get_actor]

        assert resp.status_code == 403
        assert (await wired_app.svc.get_loop(TENANT, loop["id"]))["state"] == "live"


class TestResumeCommitted:
    async def test_returns_to_committed_with_its_option(self, wired_app, loops):
        loop = await _committed(loops)
        await _pause_by_hand(loops, loop["key"])

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/resume")

        resumed = resp.json()["loop"]
        assert (resumed["state"], resumed["paused_from"]) == ("committed", None)
        assert resumed["committed"] == "urgency"
        route = await _route(wired_app, loop["key"])
        assert route.state == "committed"
        assert route.options[route.committed].key == "urgency"

    async def test_undo_of_its_pause_resumes_to_committed(self, wired_app, loops):
        loop = await _committed(loops)
        await _pause_by_hand(loops, loop["key"])
        pause, *_ = await _changes(wired_app, loop["id"])

        undo = await wired_app.svc.undo_change(TENANT, pause["id"], actor=UNDOER)
        after = await wired_app.svc.get_loop(TENANT, loop["id"])

        assert undo["kind"] == "loop.resume"
        assert (after["state"], after["committed"]) == ("committed", "urgency")

    async def test_undo_of_its_resume_pauses_from_committed(self, wired_app, loops):
        loop = await _committed(loops)
        await _pause_by_hand(loops, loop["key"])
        await loops.post(f"/api/v1/loops/{loop['key']}/resume")
        resume, *_ = await _changes(wired_app, loop["id"])

        undo = await wired_app.svc.undo_change(TENANT, resume["id"], actor=UNDOER)
        after = await wired_app.svc.get_loop(TENANT, loop["id"])

        assert undo["kind"] == "loop.pause"
        assert (after["state"], after["paused_from"]) == ("paused", "committed")
        assert after["committed"] == "urgency"


THREE = [
    {"key": "control", "name": "Control", "config": {"text": "Buy now"}},
    {"key": "urgency", "name": "Urgency", "config": {"text": "Only today"}},
    {"key": "social", "name": "Social proof", "config": {"text": "Loved by 10k"}},
]


async def _start_cycle(client, ref: str, **body) -> dict:
    resp = await client.post(f"/api/v1/loops/{ref}/cycles", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["loop"]


async def _reset_cycle(client, ref: str, **body) -> dict:
    resp = await client.post(f"/api/v1/loops/{ref}/cycles/reset", json=body or None)
    assert resp.status_code == 200, resp.text
    return resp.json()["loop"]


async def _record(wired_app, cycle_id: str) -> dict | None:
    raw = await wired_app.fake_redis.get(f"qbrix:tenant:{TENANT}:experiment:{cycle_id}")
    return json.loads(raw) if raw else None


async def _cycles(client, ref: str) -> list[dict]:
    resp = await client.get(f"/api/v1/loops/{ref}/cycles")
    assert resp.status_code == 200, resp.text
    return resp.json()["cycles"]


class TestStartCycle:
    async def test_new_options_start_the_next_cycle(self, wired_app, loops):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles", json={"options": THREE}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["serving_within_seconds"] == math.ceil(
            proxysvc.config.settings.experiment_cache_ttl
        )
        started = resp.json()["loop"]
        assert started["state"] == "live"
        assert started["cycle"]["number"] == 2
        assert started["cycle"]["id"] != loop["cycle"]["id"]
        assert [o["key"] for o in started["options"]] == [
            "control",
            "urgency",
            "social",
        ]
        first, second = reversed(await _cycles(loops, loop["key"]))
        assert first["ended_at"] is not None
        assert second["ended_at"] is None
        assert [o["key"] for o in first["options"]] == ["control", "urgency"]
        assert [o["key"] for o in second["options"]] == [
            "control",
            "urgency",
            "social",
        ]

    async def test_an_option_that_stays_keeps_its_id(self, loops):
        loop = await _launched(loops)

        started = await _start_cycle(loops, loop["key"], options=THREE)

        ids = {o["key"]: o["id"] for o in loop["options"]}
        assert {o["key"]: o["id"] for o in started["options"][:2]} == ids

    async def test_serves_the_new_cycle_and_keeps_the_earlier_record(
        self, wired_app, loops
    ):
        loop = await _launched(loops)

        started = await _start_cycle(loops, loop["key"], options=THREE)

        route = await _route(wired_app, loop["key"])
        assert route.cycle.id == started["cycle"]["id"]
        assert [o.key for o in route.options] == ["control", "urgency", "social"]
        record = await _record(wired_app, started["cycle"]["id"])
        assert [a["name"] for a in record["pool"]["arms"]] == [
            "control",
            "urgency",
            "social",
        ]
        earlier = await _record(wired_app, loop["cycle"]["id"])
        assert [a["name"] for a in earlier["pool"]["arms"]] == ["control", "urgency"]

    async def test_a_new_engine_pins_its_spec_and_version(self, wired_app, loops):
        loop = await _launched(loops)

        started = await _start_cycle(loops, loop["key"], engine="buridan:1")

        assert started["engine"] == "buridan:1"
        assert started["cycle"]["engine"] == "buridan:1"
        assert started["cycle"]["engine_version"] == "1.0"
        assert started["cycle"]["metric_version"] == loop["cycle"]["metric_version"]
        assert [o["key"] for o in started["options"]] == ["control", "urgency"]
        record = await _record(wired_app, started["cycle"]["id"])
        assert record["policy"] == "RandomPolicy"

    async def test_the_fallback_stays_when_its_option_does(self, loops):
        loop = await _launched(loops)

        started = await _start_cycle(loops, loop["key"], options=[THREE[2], THREE[0]])

        assert loop["fallback"] == "control"
        assert started["fallback"] == "control"

    async def test_a_dropped_fallback_must_be_named(self, wired_app, loops):
        loop = await _launched(loops)
        before = len(await _changes(wired_app, loop["id"]))

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles", json={"options": THREE[1:]}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_LOOP"
        assert "name one of them as the fallback (urgency, social)" in resp.text
        assert len(await _changes(wired_app, loop["id"])) == before

    async def test_a_named_fallback_is_kept(self, loops):
        loop = await _launched(loops)

        started = await _start_cycle(
            loops, loop["key"], options=THREE[1:], fallback="social"
        )

        assert started["fallback"] == "social"

    async def test_a_fallback_that_is_no_option_is_refused(self, loops):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles",
            json={"options": THREE, "fallback": "nothing"},
        )

        assert resp.status_code == 400
        assert "'nothing' is not one of the loop's options" in resp.text

    @pytest.mark.parametrize(
        "body, message",
        [
            ({}, "needs new options, a new engine or both"),
            ({"options": HEADLINE["options"][:1]}, "at least 2 options"),
            ({"engine": "nope"}, "nope"),
        ],
    )
    async def test_an_invalid_cycle_is_refused(self, loops, body, message):
        loop = await _launched(loops)

        resp = await loops.post(f"/api/v1/loops/{loop['key']}/cycles", json=body)

        assert resp.status_code == 400
        assert message in resp.text

    async def test_the_same_options_and_engine_say_to_reset(self, loops):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles",
            json={"options": THREE[:2], "engine": loop["engine"]},
        )

        assert resp.status_code == 400
        assert "reset the cycle" in resp.text

    async def test_is_a_change_by_the_person_that_cant_be_undone(
        self, wired_app, loops
    ):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles",
            json={"options": THREE, "reason": "try social proof"},
            headers={"X-Request-ID": "req-cycle"},
        )
        start, *_ = await _changes(wired_app, loop["id"])

        assert start["kind"] == "cycle.start"
        assert start["actor"]["kind"] == "member"
        assert start["reason"] == "try social proof"
        assert start["request_id"] == "req-cycle"
        assert start["before"]["cycle"]["number"] == 1
        assert start["after"] == resp.json()["loop"]
        assert start["undoable"] is False

    async def test_a_paused_loop_stays_paused(self, wired_app, loops):
        loop = await _launched(loops)
        await _pause_by_hand(loops, loop["key"])

        started = await _start_cycle(loops, loop["key"], options=THREE)

        assert (started["state"], started["paused_from"]) == ("paused", "live")
        assert started["cycle"]["number"] == 2
        route = await _route(wired_app, loop["key"])
        assert (route.state, route.cycle.number) == ("paused", 2)
        resumed = await loops.post(f"/api/v1/loops/{loop['key']}/resume")
        assert resumed.json()["loop"]["state"] == "live"
        assert resumed.json()["loop"]["cycle"]["number"] == 2

    @pytest.mark.parametrize(
        "state, fix",
        [
            ("draft", "is draft; launch it first"),
            ("committed", "is committed; reopen it first"),
            (
                "paused-committed",
                "is paused; it was committed before the pause, so resume and "
                "reopen it first",
            ),
            ("retired", "is retired; create a new loop to serve the choice again"),
        ],
    )
    async def test_other_states_are_refused(self, wired_app, loops, state, fix):
        loop = await _create(loops)
        if state != "draft":
            loop = await _launch(loops, loop["key"])
        if state in ("committed", "paused-committed"):
            loop = await _commit(loops, loop["key"])
        if state == "paused-committed":
            loop = await _pause_by_hand(loops, loop["key"])
        if state == "retired":
            loop = await _retire(loops, loop["key"])
        before = len(await _changes(wired_app, loop["id"]))

        start = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles", json={"options": THREE}
        )
        reset = await loops.post(f"/api/v1/loops/{loop['key']}/cycles/reset")

        for resp in (start, reset):
            assert resp.status_code == 409
            assert resp.json()["code"] == "LOOP_NOT_CYCLABLE"
            assert fix in resp.text
        assert len(await _changes(wired_app, loop["id"])) == before

    async def test_a_start_that_loses_the_race_records_nothing(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops)
        resolve = LoopRepository.resolve

        async def a_commit_lands(repo, ref):
            found = await resolve(repo, ref)
            await repo.transition(
                found.id, from_state="live", state="committed", committed_key="urgency"
            )
            return found

        with monkeypatch.context() as patch:
            patch.setattr(LoopRepository, "resolve", a_commit_lands)
            resp = await loops.post(
                f"/api/v1/loops/{loop['key']}/cycles", json={"options": THREE}
            )

        assert resp.status_code == 409
        assert "is committed" in resp.text
        assert len(await _cycles(loops, loop["key"])) == 1
        kinds = [c["kind"] for c in await _changes(wired_app, loop["id"])]
        assert "cycle.start" not in kinds

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.post("/api/v1/loops/nothing/cycles", json={"options": THREE})

        assert resp.status_code == 404

    async def test_a_viewer_is_refused(self, wired_app, loops):
        loop = await _launched(loops)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await loops.post(
                f"/api/v1/loops/{loop['key']}/cycles", json={"options": THREE}
            )

        assert resp.status_code == 403
        assert len(await _cycles(loops, loop["key"])) == 1

    async def test_an_api_key_is_refused(self, wired_app, loops):
        loop = await _launched(loops)
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-x", api_key_id="key-1")
        try:
            resp = await loops.post(f"/api/v1/loops/{loop['key']}/cycles/reset")
        finally:
            del overrides[get_actor]

        assert resp.status_code == 403
        assert "api key" in resp.text


class TestResetCycle:
    async def test_keeps_options_engine_and_fallback_with_fresh_learning(
        self, wired_app, loops
    ):
        loop = await _launched(loops)

        reset = await _reset_cycle(loops, loop["key"], reason="the page changed")

        assert reset["cycle"]["number"] == 2
        assert reset["cycle"]["id"] != loop["cycle"]["id"]
        assert reset["options"] == loop["options"]
        assert (reset["engine"], reset["fallback"]) == (
            loop["engine"],
            loop["fallback"],
        )
        assert reset["cycle"]["engine"] == loop["cycle"]["engine"]
        record = await _record(wired_app, reset["cycle"]["id"])
        earlier = await _record(wired_app, loop["cycle"]["id"])
        assert record["pool"]["arms"] == earlier["pool"]["arms"]
        assert reset["cycle"]["id"] != earlier["id"]

    async def test_is_a_change_that_cant_be_undone(self, wired_app, loops):
        loop = await _launched(loops)
        await _reset_cycle(loops, loop["key"])
        reset, *_ = await _changes(wired_app, loop["id"])

        assert reset["kind"] == "cycle.reset"
        assert reset["reason"] is None
        with pytest.raises(ChangeNotUndoableError, match="begins fresh learning"):
            await wired_app.svc.undo_change(TENANT, reset["id"], actor=UNDOER)

    async def test_a_paused_loop_stays_paused(self, loops):
        loop = await _launched(loops)
        await _pause_by_hand(loops, loop["key"])

        reset = await _reset_cycle(loops, loop["key"])

        assert (reset["state"], reset["cycle"]["number"]) == ("paused", 2)


class TestEarlierCycles:
    async def test_stay_readable(self, loops):
        loop = await _launched(loops)
        await _start_cycle(loops, loop["key"], options=THREE)
        await _reset_cycle(loops, loop["key"])

        cycles = await _cycles(loops, loop["key"])
        earlier = await loops.get(
            f"/api/v1/loops/{loop['key']}/results", params={"cycle": 1}
        )

        assert [c["number"] for c in cycles] == [3, 2, 1]
        assert [c["ended_at"] is None for c in cycles] == [True, False, False]
        assert earlier.status_code == 200, earlier.text
        assert earlier.json()["cycle"]["id"] == loop["cycle"]["id"]

    async def test_start_cannot_be_undone_over_http(self, wired_app, loops):
        loop = await _launched(loops)
        await _start_cycle(loops, loop["key"], options=THREE)
        start, *_ = await _changes(wired_app, loop["id"])

        resp = await loops.post(f"/api/v1/changes/{start['id']}/undo")

        assert resp.status_code == 409
        assert "the earlier cycle stays readable" in resp.text

    async def test_history_shows_the_cycle_and_the_new_option(self, loops):
        loop = await _launched(loops)
        await _start_cycle(loops, loop["key"], options=THREE)

        resp = await loops.get("/api/v1/changes", params={"kind": "cycle.start"})
        latest = resp.json()["changes"][0]

        assert latest["pieces"][1]["text"] == " started a new cycle of "
        assert {"field": "cycle", "before": "1", "after": "2"} in latest["diff"]
        assert {"field": "option", "before": None, "after": "Social proof"} in latest[
            "diff"
        ]


MOBILE = [{"property": "device", "operator": "is", "value": "mobile"}]
OFFICE_HOURS = {
    "hours": {"start": "09:00", "end": "18:00"},
    "timezone": "Europe/Amsterdam",
}
EVERYONE = {
    "audience": [],
    "rollout": 100,
    "schedule": {"hours": None, "starts_on": None, "timezone": None},
}


async def _deliver(client, ref: str, **body):
    return await client.put(f"/api/v1/loops/{ref}/delivery", json=body)


class TestDelivery:
    async def test_a_new_loop_decides_for_everyone(self, loops):
        loop = await _create(loops)

        assert loop["delivery"] == EVERYONE

    async def test_a_change_sets_what_it_names_and_keeps_the_rest(
        self, wired_app, loops
    ):
        loop = await _launched(loops)

        first = await _deliver(loops, loop["key"], audience=MOBILE, reason="mobile")
        second = await _deliver(loops, loop["key"], rollout=25, fallback="urgency")

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["serving_within_seconds"] == math.ceil(
            proxysvc.config.settings.experiment_cache_ttl
        )
        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert read["delivery"] == {**EVERYONE, "audience": MOBILE, "rollout": 25}
        assert read["fallback"] == "urgency"

    async def test_it_is_one_change_with_before_and_after(self, wired_app, loops):
        loop = await _launched(loops)

        await _deliver(loops, loop["key"], schedule=OFFICE_HOURS, reason="office")
        change, *_ = await _changes(wired_app, loop["id"])

        assert change["kind"] == "delivery.update"
        assert change["reason"] == "office"
        assert change["before"]["delivery"] == EVERYONE
        assert change["after"]["delivery"]["schedule"] == {
            **OFFICE_HOURS,
            "starts_on": None,
        }

    async def test_it_writes_the_route(self, wired_app, loops):
        loop = await _launched(loops)

        await _deliver(loops, loop["key"], audience=MOBILE, rollout=40)
        route = await _route(wired_app, loop["key"])

        assert route.delivery.rollout == 40
        assert route.delivery.audience[0].property == "device"

    async def test_undo_restores_the_delivery_and_fallback(self, wired_app, loops):
        loop = await _launched(loops)
        await _deliver(loops, loop["key"], audience=MOBILE, fallback="urgency")
        change, *_ = await _changes(wired_app, loop["id"])

        undo = await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)
        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        route = await _route(wired_app, loop["key"])

        assert undo["kind"] == "delivery.update"
        assert undo["undoes_id"] == change["id"]
        assert read["delivery"] == EVERYONE
        assert read["fallback"] == "control"
        assert route.delivery.everyone

    async def test_undo_after_a_later_delivery_change_is_refused(
        self, wired_app, loops
    ):
        loop = await _launched(loops)
        await _deliver(loops, loop["key"], rollout=50)
        earlier, *_ = await _changes(wired_app, loop["id"])
        await _deliver(loops, loop["key"], rollout=80)

        with pytest.raises(ChangeConflictError, match="delivery.update"):
            await wired_app.svc.undo_change(TENANT, earlier["id"], actor=UNDOER)

    async def test_a_draft_paused_or_committed_loop_can_change_it(
        self, wired_app, loops
    ):
        draft = await _create(loops, name="Draft")
        committed = await _committed(loops)
        paused = await _pause_by_hand(
            loops,
            (await _launch(loops, (await _create(loops, name="Paused"))["key"]))["key"],
        )

        for loop in (draft, committed, paused):
            resp = await _deliver(loops, loop["key"], rollout=10)
            assert resp.status_code == 200, resp.text

    async def test_a_retired_loop_is_refused(self, loops):
        retired = await _retired(loops)

        resp = await _deliver(loops, retired["key"], rollout=10)

        assert resp.status_code == 409
        assert resp.json()["code"] == "LOOP_RETIRED"
        assert "create a new loop" in resp.json()["detail"]

    @pytest.mark.parametrize(
        "body, message",
        [
            ({}, "needs an audience, a rollout, a schedule, a fallback"),
            ({"rollout": 100}, "nothing changes"),
            ({"fallback": "social"}, "not one of the loop's options"),
            ({"rollout": 101}, "rollout"),
            (
                {"schedule": {"hours": {"start": "09:00", "end": "18:00"}}},
                "needs its timezone",
            ),
            (
                {"audience": [{"property": "c", "operator": "eq", "value": "NL"}]},
                "audience.0.operator",
            ),
        ],
    )
    async def test_a_change_that_cant_apply_is_refused(self, loops, body, message):
        loop = await _launched(loops)

        resp = await _deliver(loops, loop["key"], **body)

        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "INVALID_LOOP"
        assert message in resp.json()["detail"]

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await _deliver(loops, "nope", rollout=10)

        assert resp.status_code == 404

    async def test_a_viewer_is_refused(self, wired_app, loops):
        loop = await _launched(loops)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await _deliver(loops, loop["key"], rollout=10)

        assert resp.status_code == 403


PLAN = {"name": "plan", "type": "categorical", "values": ["free", "pro"]}
SEATS = {"name": "seats", "type": "numeric", "min": 1.0, "max": 500.0}
RETURNING = {"name": "returning", "type": "boolean"}


async def _declare(client, ref: str, context, **body):
    return await client.put(
        f"/api/v1/loops/{ref}/context", json={"context": context, **body}
    )


async def _on_leibniz(loops, context=None) -> dict:
    """a live loop whose current cycle learns from context."""
    loop = await _create(loops)
    resp = await _declare(loops, loop["key"], context or [PLAN])
    assert resp.status_code == 200, resp.text
    await _launch(loops, loop["key"])
    return await _start_cycle(loops, loop["key"], engine="leibniz")


class TestContext:
    async def test_a_new_loop_learns_from_no_context(self, loops):
        loop = await _create(loops)

        assert loop["context"] is None

    async def test_a_draft_declares_it_without_a_cycle(self, wired_app, loops):
        loop = await _create(loops)

        resp = await _declare(loops, loop["key"], [PLAN, SEATS], reason="segments")

        assert resp.status_code == 200, resp.text
        declared = resp.json()["loop"]
        assert declared["context"] == [PLAN, SEATS]
        assert declared["cycle"] is None
        change, *_ = await _changes(wired_app, loop["id"])
        assert change["kind"] == "context.update"
        assert change["reason"] == "segments"
        assert change["before"]["context"] is None
        assert change["after"]["context"] == [PLAN, SEATS]

    async def test_on_spinoza_it_keeps_the_cycle_and_undoes(self, wired_app, loops):
        loop = await _launched(loops)

        declared = (await _declare(loops, loop["key"], [PLAN])).json()["loop"]
        change, *_ = await _changes(wired_app, loop["id"])
        route = await _route(wired_app, loop["key"])

        assert declared["cycle"]["id"] == loop["cycle"]["id"]
        assert declared["cycle"]["context"] is None
        assert route.cycle.context is None
        assert change["undoable"] is True

        await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)
        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert read["context"] is None

    async def test_leibniz_is_refused_until_the_context_is_declared(self, loops):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles", json={"engine": "leibniz"}
        )

        assert resp.status_code == 400, resp.text
        assert "declare the context first" in resp.json()["detail"]

    async def test_a_cycle_on_leibniz_learns_with_the_context(self, wired_app, loops):
        started = await _on_leibniz(loops, [PLAN, SEATS])

        record = await _record(wired_app, started["cycle"]["id"])
        route = await _route(wired_app, started["key"])

        assert started["engine"].startswith("leibniz")
        assert started["cycle"]["context"] == [PLAN, SEATS]
        assert record["policy_params"]["dim"] == 1 + 3 + 1
        assert [p.name for p in route.cycle.context.root] == ["plan", "seats"]

    async def test_on_leibniz_it_starts_a_cycle_that_cant_be_undone(
        self, wired_app, loops
    ):
        loop = await _on_leibniz(loops)

        declared = (await _declare(loops, loop["key"], [PLAN, RETURNING])).json()[
            "loop"
        ]
        change, *_ = await _changes(wired_app, loop["id"])
        record = await _record(wired_app, declared["cycle"]["id"])

        assert declared["cycle"]["number"] == loop["cycle"]["number"] + 1
        assert declared["cycle"]["context"] == [PLAN, RETURNING]
        assert record["policy_params"]["dim"] == 1 + 3 + 1
        assert change["kind"] == "context.update"
        assert change["undoable"] is False
        with pytest.raises(ChangeNotUndoableError, match="started a new cycle"):
            await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)

    async def test_a_paused_leibniz_loop_stays_paused_in_its_new_cycle(self, loops):
        loop = await _on_leibniz(loops)
        await _pause_by_hand(loops, loop["key"])

        declared = (await _declare(loops, loop["key"], [SEATS])).json()["loop"]

        assert declared["state"] == "paused"
        assert declared["cycle"]["number"] == loop["cycle"]["number"] + 1

    async def test_a_committed_leibniz_loop_is_reopened_first(self, loops):
        loop = await _on_leibniz(loops)
        await _commit(loops, loop["key"])

        resp = await _declare(loops, loop["key"], [SEATS])

        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "LOOP_NOT_CYCLABLE"
        assert "reopen it first" in resp.json()["detail"]

    async def test_a_committed_spinoza_loop_declares_it(self, loops):
        loop = await _committed(loops)

        resp = await _declare(loops, loop["key"], [PLAN])

        assert resp.status_code == 200, resp.text

    async def test_a_retired_loop_is_refused(self, loops):
        retired = await _retired(loops)

        resp = await _declare(loops, retired["key"], [PLAN])

        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "LOOP_RETIRED"

    @pytest.mark.parametrize(
        "context, message",
        [
            ([], "context: context schema needs at least one property"),
            (
                [{"name": "plan", "type": "categorical", "values": []}],
                "context.0.values",
            ),
            ([PLAN, PLAN], "duplicate property names: plan"),
            ([{"name": "plan", "type": "colour"}], "context.0"),
        ],
    )
    async def test_an_invalid_context_is_refused(self, loops, context, message):
        loop = await _launched(loops)

        resp = await _declare(loops, loop["key"], context)

        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "INVALID_LOOP"
        assert message in resp.json()["detail"]

    async def test_the_same_context_is_nothing_to_change(self, loops):
        loop = await _create(loops)
        await _declare(loops, loop["key"], [PLAN])

        resp = await _declare(loops, loop["key"], [PLAN])

        assert resp.status_code == 400, resp.text
        assert "nothing changes" in resp.json()["detail"]

    async def test_leibniz_can_never_clear_it(self, loops):
        loop = await _on_leibniz(loops)

        resp = await _declare(loops, loop["key"], None)

        assert resp.status_code == 400, resp.text
        assert "start a cycle on another engine first" in resp.json()["detail"]

    async def test_a_viewer_is_refused(self, wired_app, loops):
        loop = await _launched(loops)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            resp = await _declare(loops, loop["key"], [PLAN])

        assert resp.status_code == 403


def _arrival(name, type_, arrived, last, last_ms=1):
    return PropertyArrival(name, type_, arrived, last_ms, json.dumps(last))


class TestContextRead:
    async def test_it_says_what_arrived_could_be_read_and_wasnt_declared(
        self, wired_app, loops
    ):
        loop = await _on_leibniz(loops, [PLAN, SEATS, RETURNING])
        wired_app.svc._clickhouse.arrivals[loop["id"]] = (
            100,
            [
                _arrival("plan", "String", 90, "pro", last_ms=5),
                _arrival("plan", "Double", 10, 3.5, last_ms=9),
                _arrival("seats", "Int64", 40, 12),
                _arrival("country", "String", 100, "NL"),
                _arrival("returning", "Null", 7, None),
            ],
        )

        resp = await loops.get(f"/api/v1/loops/{loop['key']}/context")

        assert resp.status_code == 200, resp.text
        read = resp.json()
        assert read["context"] == [PLAN, SEATS, RETURNING]
        assert read["learns_from_context"] is True
        assert read["decisions"] == 100
        assert read["properties"] == [
            {
                "name": "plan",
                "type": "categorical",
                "arrived": 100,
                "readable": 90,
                "last_value": 3.5,
            },
            {
                "name": "seats",
                "type": "numeric",
                "arrived": 40,
                "readable": 40,
                "last_value": 12,
            },
            {
                "name": "returning",
                "type": "boolean",
                "arrived": 0,
                "readable": 0,
                "last_value": None,
            },
        ]
        assert read["undeclared"] == [{"name": "country", "arrived": 100}]

    async def test_a_loop_with_no_context_lists_what_it_could_declare(
        self, wired_app, loops
    ):
        loop = await _launched(loops)
        wired_app.svc._clickhouse.arrivals[loop["id"]] = (
            3,
            [_arrival("device", "String", 3, "mobile")],
        )

        read = (await loops.get(f"/api/v1/loops/{loop['key']}/context")).json()

        assert read["learns_from_context"] is False
        assert read["properties"] == []
        assert read["undeclared"] == [{"name": "device", "arrived": 3}]

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await loops.get("/api/v1/loops/nope/context")

        assert resp.status_code == 404
