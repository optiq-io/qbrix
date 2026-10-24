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
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

import proxysvc.config
from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.next import next_routes

TENANT = "dev-tenant"
UNDOER = Actor.member("user-undo", request_id="req-undo")

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

        assert loop["metric"] == {"id": metric["id"], "name": "purchase"}

    async def test_the_owner_is_the_person_behind_the_actor(self, wired_app, loops):
        loop = await _create(loops)
        (change,) = await _changes(wired_app, loop["id"])

        assert loop["owner"] == change["actor"]["user_id"]

    async def test_the_owner_through_a_connection_is_its_member(self, wired_app, loops):
        via = Actor(
            kind="connection",
            user_id="user-ada",
            connection_id="conn-1",
            client_name="claude",
        )

        loop = await wired_app.svc.create_loop(
            TENANT,
            name="Pricing page",
            metric="purchase",
            options=[{"name": "A"}, {"name": "B"}],
            actor=via,
        )
        (change,) = await _changes(wired_app, loop["id"])

        assert loop["owner"] == "user-ada"
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


class TestMetricInUse:
    async def test_a_metric_a_loop_uses_is_kept(self, wired_app, loops):
        await _create(loops)
        metric = (await loops.get("/api/v1/metrics/purchase")).json()
        (create,) = await wired_app.svc.list_changes(TENANT, "metric", metric["id"])

        with pytest.raises(ChangeConflictError, match="'checkout-headline' uses"):
            await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        assert (await loops.get("/api/v1/metrics/purchase")).status_code == 200
