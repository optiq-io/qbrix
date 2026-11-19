"""integration tests for changing and deleting a metric, a qbrix next surface.

invariants verified:
  a new window is a minor version that every loop using the metric serves at
  once, with the change in each loop's history. a reworded semantic is no
  version. a new semantic is a major version that starts one cycle on every
  live, paused or committed loop using the metric, in the same request, while
  a draft takes the version as it is; a committed loop stays committed. the
  name changes only before a loop has launched with the metric. undo restores
  a minor or a reword as a new change on the metric, never from a loop, never
  a major. a metric is deleted only while no loop uses it or ever ran it, and
  the refusal names the loop. the metric reads back with its versions, newest
  first, each with who made it, why and what it changed.
"""

from __future__ import annotations

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
SIGNUP = {"name": "signup", "semantic": "a new account", "type": "conversion"}


@pytest_asyncio.fixture
async def metrics(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    for metric in (PURCHASE, SIGNUP):
        resp = await client.post("/api/v1/metrics", json=metric)
        assert resp.status_code == 201, resp.text
    yield client
    app.router.routes[:] = routes


async def _loop(client, name: str, *, then: tuple[str, ...] = ()) -> dict:
    resp = await client.post(
        "/api/v1/loops",
        json={
            "name": name,
            "metric": "purchase",
            "options": [
                {"name": "Control", "config": {"text": "Buy now"}},
                {"name": "Urgency", "config": {"text": "Only today"}},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    loop = resp.json()
    for step in then:
        body = {"option": "urgency"} if step == "commit" else None
        resp = await client.post(f"/api/v1/loops/{loop['key']}/{step}", json=body)
        assert resp.status_code == 200, resp.text
    return await _get_loop(client, loop["key"])


async def _get_loop(client, key: str) -> dict:
    resp = await client.get(f"/api/v1/loops/{key}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _patch(client, body: dict, metric: str = "purchase", **headers) -> dict:
    resp = await client.patch(f"/api/v1/metrics/{metric}", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _changes(wired_app, target_type: str, target_id: str) -> list[dict]:
    return await wired_app.svc.list_changes(TENANT, target_type, target_id)


class TestWindow:
    async def test_a_new_window_is_a_minor_every_loop_serves_at_once(
        self, wired_app, metrics
    ):
        loop = await _loop(metrics, "Checkout headline", then=("launch",))

        updated = await _patch(
            metrics,
            {"window_seconds": 12 * 3600, "reason": "buyers decide within hours"},
        )

        assert updated["metric"]["version"] == "1.1"
        assert updated["metric"]["window_seconds"] == 12 * 3600
        assert updated["cycles"] == []
        assert updated["change"]["kind"] == "metric.update"
        assert updated["change"]["undoable"] is True
        route = await wired_app.svc.loops._routes.get(TENANT, loop["key"])
        assert route.metric.version == "1.1"
        assert route.metric.window_ms == 12 * 3600 * 1000
        assert route.cycle.id == loop["cycle"]["id"]

    async def test_each_loop_records_it_in_its_history(self, wired_app, metrics):
        live = await _loop(metrics, "Checkout headline", then=("launch",))
        draft = await _loop(metrics, "Pricing page")

        await _patch(
            metrics, {"window_seconds": 3600}, **{"X-Request-ID": "req-window"}
        )

        for loop in (live, draft):
            newest = (await _changes(wired_app, "loop", loop["id"]))[0]
            assert newest["kind"] == "metric.update"
            assert newest["request_id"] == "req-window"
            assert newest["before"]["metric"]["version"] == "1.0"
            assert newest["after"]["metric"]["version"] == "1.1"
            assert newest["after"]["metric"]["window_seconds"] == 3600
            assert newest["undoable"] is False

    async def test_the_same_window_changes_nothing(self, metrics):
        resp = await metrics.patch(
            "/api/v1/metrics/purchase", json={"window_seconds": 86400}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_METRIC"


class TestSemantic:
    async def test_a_reword_is_no_version(self, wired_app, metrics):
        updated = await _patch(
            metrics,
            {"semantic": "a checkout that completed", "semantic_change": "reword"},
        )

        assert updated["metric"]["version"] == "1.0"
        assert updated["metric"]["semantic"] == "a checkout that completed"
        change, _ = await _changes(wired_app, "metric", updated["metric"]["id"])
        assert change["kind"] == "metric.update"
        assert change["before"]["semantic"] == "a completed checkout"

    async def test_the_same_semantic_is_a_minor(self, metrics):
        updated = await _patch(
            metrics,
            {
                "semantic": "a completed checkout, sent from the order webhook",
                "semantic_change": "same",
            },
        )

        assert updated["metric"]["version"] == "1.1"
        assert updated["cycles"] == []

    async def test_a_new_semantic_starts_a_cycle_on_every_loop_still_deciding(
        self, wired_app, metrics
    ):
        live = await _loop(metrics, "Checkout headline", then=("launch",))
        paused = await _loop(metrics, "Pricing page", then=("launch", "pause"))
        committed = await _loop(metrics, "Hero image", then=("launch", "commit"))
        draft = await _loop(metrics, "Footer")

        updated = await _patch(
            metrics,
            {
                "semantic": "a paid order, sent since the payment webhook",
                "semantic_change": "new",
                "reason": "https://github.com/acme/shop/pull/491",
            },
            **{"X-Request-ID": "req-major"},
        )

        assert updated["metric"]["version"] == "2.0"
        assert updated["change"]["undoable"] is False
        assert sorted(c["loop"] for c in updated["cycles"]) == sorted(
            [live["key"], paused["key"], committed["key"]]
        )
        assert {c["cycle"] for c in updated["cycles"]} == {2}
        for loop, state in (
            (live, "live"),
            (paused, "paused"),
            (committed, "committed"),
        ):
            now = await _get_loop(metrics, loop["key"])
            assert now["state"] == state
            assert now["cycle"]["number"] == 2
            assert now["cycle"]["metric_version"] == "2.0"
            newest = (await _changes(wired_app, "loop", loop["id"]))[0]
            assert newest["kind"] == "metric.update"
            assert newest["request_id"] == "req-major"
            assert newest["reason"] == "https://github.com/acme/shop/pull/491"
            assert newest["before"]["cycle"]["number"] == 1
            assert newest["after"]["cycle"]["number"] == 2
        assert (await _get_loop(metrics, committed["key"]))["committed"] == "urgency"
        now = await _get_loop(metrics, draft["key"])
        assert now["cycle"] is None
        assert now["metric"]["version"] == "2.0"

    async def test_a_new_cycle_is_served(self, wired_app, metrics):
        loop = await _loop(metrics, "Checkout headline", then=("launch",))

        await _patch(metrics, {"semantic": "a paid order", "semantic_change": "new"})

        now = await _get_loop(metrics, loop["key"])
        route = await wired_app.svc.loops._routes.get(TENANT, loop["key"])
        assert route.cycle.id == now["cycle"]["id"]
        assert route.metric.version == "2.0"
        raw = await wired_app.fake_redis.get(
            f"qbrix:tenant:{TENANT}:experiment:{now['cycle']['id']}"
        )
        assert raw is not None

    async def test_a_semantic_says_how_it_changed(self, metrics):
        resp = await metrics.patch(
            "/api/v1/metrics/purchase", json={"semantic": "a paid order"}
        )

        assert resp.status_code == 400
        assert "reword, same or new" in resp.json()["detail"]

    async def test_an_unchanged_semantic_is_refused(self, metrics):
        resp = await metrics.patch(
            "/api/v1/metrics/purchase",
            json={"semantic": "a completed checkout", "semantic_change": "same"},
        )

        assert resp.status_code == 400


class TestName:
    async def test_renames_before_any_loop_launched_with_it(self, wired_app, metrics):
        draft = await _loop(metrics, "Checkout headline")

        updated = await _patch(metrics, {"name": "order"})

        assert updated["metric"]["name"] == "order"
        assert (await _get_loop(metrics, draft["key"]))["metric"]["name"] == "order"
        assert (
            await wired_app.svc._metric_service._routes.get(TENANT, "purchase") is None
        )

    async def test_a_name_decisions_were_made_under_stays(self, metrics):
        loop = await _loop(metrics, "Checkout headline", then=("launch",))

        resp = await metrics.patch("/api/v1/metrics/purchase", json={"name": "order"})

        assert resp.status_code == 409
        assert resp.json()["code"] == "METRIC_IN_USE"
        assert loop["key"] in resp.json()["detail"]

    async def test_a_taken_name_is_refused(self, metrics):
        resp = await metrics.patch("/api/v1/metrics/purchase", json={"name": "signup"})

        assert resp.status_code == 409
        assert resp.json()["code"] == "METRIC_NAME_TAKEN"

    async def test_an_unknown_metric_is_not_found(self, metrics):
        resp = await metrics.patch(
            "/api/v1/metrics/revenue", json={"window_seconds": 60}
        )

        assert resp.status_code == 404


class TestUndo:
    async def test_undoing_a_window_is_a_new_minor_with_the_old_window(
        self, wired_app, metrics
    ):
        loop = await _loop(metrics, "Checkout headline", then=("launch",))
        updated = await _patch(metrics, {"window_seconds": 3600})

        undo = await wired_app.svc.undo_change(
            TENANT, updated["change"]["id"], actor=UNDOER
        )

        assert undo["kind"] == "metric.update"
        assert undo["after"]["version"] == "1.2"
        assert undo["after"]["window_seconds"] == 86400
        route = await wired_app.svc.loops._routes.get(TENANT, loop["key"])
        assert route.metric.window_ms == 86400 * 1000

    async def test_undoing_a_reword_restores_the_text(self, wired_app, metrics):
        updated = await _patch(
            metrics, {"semantic": "a checkout", "semantic_change": "reword"}
        )

        undo = await wired_app.svc.undo_change(
            TENANT, updated["change"]["id"], actor=UNDOER
        )

        assert undo["after"]["version"] == "1.0"
        assert undo["after"]["semantic"] == "a completed checkout"

    async def test_a_new_semantic_cannot_be_undone(self, wired_app, metrics):
        updated = await _patch(
            metrics, {"semantic": "a paid order", "semantic_change": "new"}
        )

        with pytest.raises(ChangeNotUndoableError, match="new semantic"):
            await wired_app.svc.undo_change(
                TENANT, updated["change"]["id"], actor=UNDOER
            )

    async def test_a_loops_record_is_undone_on_the_metric(self, wired_app, metrics):
        loop = await _loop(metrics, "Checkout headline")
        await _patch(metrics, {"window_seconds": 3600})
        record = (await _changes(wired_app, "loop", loop["id"]))[0]

        with pytest.raises(ChangeNotUndoableError, match="on the metric 'purchase'"):
            await wired_app.svc.undo_change(TENANT, record["id"], actor=UNDOER)

    async def test_a_later_change_refuses_the_undo(self, wired_app, metrics):
        first = await _patch(metrics, {"window_seconds": 3600})
        await _patch(metrics, {"window_seconds": 60})

        with pytest.raises(ChangeConflictError):
            await wired_app.svc.undo_change(TENANT, first["change"]["id"], actor=UNDOER)


class TestDelete:
    async def test_deletes_a_metric_no_loop_used(self, wired_app, metrics):
        metric = (await metrics.get("/api/v1/metrics/signup")).json()

        resp = await metrics.request(
            "DELETE", "/api/v1/metrics/signup", json={"reason": "never wired"}
        )

        assert resp.status_code == 204
        assert (await metrics.get("/api/v1/metrics/signup")).status_code == 404
        delete, _ = await _changes(wired_app, "metric", metric["id"])
        assert delete["kind"] == "metric.delete"
        assert delete["reason"] == "never wired"

    async def test_a_metric_a_draft_uses_stays(self, metrics):
        draft = await _loop(metrics, "Checkout headline")

        resp = await metrics.delete("/api/v1/metrics/purchase")

        assert resp.status_code == 409
        assert resp.json()["code"] == "METRIC_IN_USE"
        assert draft["key"] in resp.json()["detail"]

    async def test_a_metric_a_loop_ran_in_an_earlier_cycle_stays(self, metrics):
        loop = await _loop(metrics, "Checkout headline", then=("launch",))
        resp = await metrics.post(
            f"/api/v1/loops/{loop['key']}/cycles", json={"metric": "signup"}
        )
        assert resp.status_code == 200, resp.text

        resp = await metrics.delete("/api/v1/metrics/purchase")

        assert resp.status_code == 409
        assert f"the loop '{loop['key']}' has used" in resp.json()["detail"]

    async def test_an_unknown_metric_is_not_found(self, metrics):
        resp = await metrics.delete("/api/v1/metrics/revenue")

        assert resp.status_code == 404


class TestVersions:
    async def test_newest_first_with_who_why_and_what_changed(self, metrics):
        await _patch(metrics, {"window_seconds": 3600, "reason": "faster buyers"})
        await _patch(
            metrics,
            {
                "semantic": "a paid order",
                "semantic_change": "new",
                "reason": "the payment webhook",
            },
        )

        resp = await metrics.get("/api/v1/metrics/purchase")

        versions = resp.json()["versions"]
        assert [v["version"] for v in versions] == ["2.0", "1.1", "1.0"]
        assert [v["reason"] for v in versions] == [
            "the payment webhook",
            "faster buyers",
            None,
        ]
        assert versions[0]["changed"] == [
            {
                "field": "semantic",
                "before": "a completed checkout",
                "after": "a paid order",
            }
        ]
        assert versions[1]["changed"] == [
            {"field": "window", "before": "1d", "after": "1h"}
        ]
        assert versions[2]["changed"] == []
        assert versions[0]["created_by"]["id"] == "dev-user"
