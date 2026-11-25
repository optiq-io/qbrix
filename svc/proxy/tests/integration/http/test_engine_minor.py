"""integration tests for engines and their minors, a qbrix next surface.

invariants verified:
  a loop is created on any engine spec, and on leibniz with the context it
  learns from. the engines read lists every engine with what it needs. on
  start, every running cycle that follows its engine's major moves to the
  latest minor this install ships, both ways: its cycle records the new
  version, its runtime record runs the new minor, what it learned stays, and
  its loop's history gets one change by qbrix that says what changed. a
  cycle pinned to a minor stays, as do drafts and retired loops. two
  replicas starting together move each cycle once.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio

import proxysvc.config
from qbrixcore.engine import ENGINES
from qbrixcore.engine import Buridan
from qbrixcore.engine import EngineRegistry
from qbrixcore.engine import EngineVersion
from qbrixcore.engine import Leibniz
from qbrixcore.engine import Resolved
from qbrixcore.engine import Spinoza

from proxysvc.mod.loop.upgrade import follow_minors
from proxysvc.mod.status import VERSION
from proxysvc.next import next_routes

TENANT = "dev-tenant"
CHANGES = "explores less once an option is clearly ahead"

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

PLAN = [{"name": "plan", "type": "categorical", "values": ["free", "pro"]}]


class SpinozaOneOne(Spinoza):
    version = EngineVersion(1, 1)
    changes = CHANGES

    @classmethod
    def _resolve(cls, metric_type, score_range, context_dim):
        resolved = super()._resolve(metric_type, score_range, context_dim)
        if resolved.fixed_params.get("alpha_prior") is not None:
            return Resolved(
                resolved.policy_cls, {"alpha_prior": 0.5, "beta_prior": 0.5}
            )
        return resolved


def _ship(monkeypatch, *engines) -> None:
    """the engines this install ships, as an upgrade or downgrade leaves them."""
    monkeypatch.setattr(ENGINES, "_majors", EngineRegistry(engines)._majors)


@pytest_asyncio.fixture
async def loops(wired_app, client, next_enabled):
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


async def _launched(client, **overrides) -> dict:
    loop = await _create(client, **overrides)
    resp = await client.post(f"/api/v1/loops/{loop['key']}/launch")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _record(wired_app, cycle_id: str) -> dict:
    raw = await wired_app.fake_redis.get(f"qbrix:tenant:{TENANT}:experiment:{cycle_id}")
    return json.loads(raw)


async def _cycle(client, key: str) -> dict:
    resp = await client.get(f"/api/v1/loops/{key}")
    assert resp.status_code == 200, resp.text
    return resp.json()["cycle"]


async def _minors(wired_app, loop_id: str) -> list[dict]:
    changes = await wired_app.svc.list_changes(TENANT, "loop", loop_id)
    return [change for change in changes if change["kind"] == "engine.minor"]


class TestChoosing:

    @pytest.mark.parametrize(
        "engine, pinned", [("buridan", "buridan:1"), ("spinoza:1.0", "spinoza:1.0")]
    )
    async def test_a_loop_runs_the_engine_it_was_created_on(
        self, loops, engine, pinned
    ):
        loop = await _launched(loops, engine=engine)

        assert loop["engine"] == engine
        assert loop["cycle"]["engine"] == pinned
        assert loop["cycle"]["engine_version"] == "1.0"

    async def test_leibniz_is_created_with_its_context(self, loops):
        loop = await _launched(loops, engine="leibniz", context=PLAN)

        assert loop["context"][0]["name"] == "plan"
        assert loop["cycle"]["context"][0]["name"] == "plan"

    async def test_leibniz_without_a_context_is_refused(self, loops):
        resp = await loops.post("/api/v1/loops", json={**HEADLINE, "engine": "leibniz"})

        assert resp.status_code == 400
        assert "declare the context first" in resp.text

    async def test_an_invalid_context_is_refused(self, loops):
        resp = await loops.post(
            "/api/v1/loops",
            json={**HEADLINE, "context": [{"name": "plan", "type": "nope"}]},
        )

        assert resp.status_code == 400
        assert "context.0" in resp.text

    async def test_engines_are_listed_default_first(self, loops):
        resp = await loops.get("/api/v1/engines")

        assert resp.status_code == 200
        body = resp.json()
        assert [engine["name"] for engine in body["engines"]] == [
            "spinoza",
            "buridan",
            "leibniz",
        ]
        assert body["forms"] == "spinoza, spinoza:1 or spinoza:1.3"


class TestMinors:

    async def test_a_cycle_on_a_major_moves_to_its_new_minor(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops)
        cycle_id = loop["cycle"]["id"]
        learned = {"alpha": [3.0, 9.0], "beta": [5.0, 2.0]}
        await wired_app.svc.redis.set_params(TENANT, cycle_id, learned)
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)

        moved = await follow_minors(wired_app.svc.redis)

        assert moved == 1
        cycle = await _cycle(loops, loop["key"])
        assert (cycle["id"], cycle["engine"], cycle["engine_version"]) == (
            cycle_id,
            "spinoza:1",
            "1.1",
        )
        record = await _record(wired_app, cycle_id)
        assert record["policy_params"] == {"alpha_prior": 0.5, "beta_prior": 0.5}
        assert await wired_app.svc.redis.get_params(TENANT, cycle_id) == learned
        [change] = await _minors(wired_app, loop["id"])
        assert change["actor"]["kind"] == "qbrix"
        assert change["reason"] == (
            f"Spinoza 1.0 → 1.1 with qbrix {VERSION}: {CHANGES}"
        )
        assert change["undoable"] is False

    async def test_a_cycle_pinned_to_a_minor_stays(self, wired_app, loops, monkeypatch):
        loop = await _launched(loops, engine="spinoza:1.0")
        before = await _record(wired_app, loop["cycle"]["id"])
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)

        assert await follow_minors(wired_app.svc.redis) == 0

        assert (await _cycle(loops, loop["key"]))["engine_version"] == "1.0"
        assert await _record(wired_app, loop["cycle"]["id"]) == before
        assert await _minors(wired_app, loop["id"]) == []

    async def test_drafts_and_retired_loops_stay(self, wired_app, loops, monkeypatch):
        draft = await _create(loops, name="A draft")
        retired = await _launched(loops, name="Retired")
        resp = await loops.post(f"/api/v1/loops/{retired['key']}/retire")
        assert resp.status_code == 200, resp.text
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)

        assert await follow_minors(wired_app.svc.redis) == 0

        assert await _minors(wired_app, draft["id"]) == []
        assert await _minors(wired_app, retired["id"]) == []

    async def test_a_paused_and_a_committed_loop_move_too(
        self, wired_app, loops, monkeypatch
    ):
        paused = await _launched(loops, name="Paused")
        committed = await _launched(loops, name="Committed")
        assert (await loops.post(f"/api/v1/loops/{paused['key']}/pause")).is_success
        resp = await loops.post(
            f"/api/v1/loops/{committed['key']}/commit", json={"option": "control"}
        )
        assert resp.status_code == 200, resp.text
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)

        assert await follow_minors(wired_app.svc.redis) == 2

    async def test_replicas_starting_together_move_each_cycle_once(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops)
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)

        moved = await asyncio.gather(
            follow_minors(wired_app.svc.redis), follow_minors(wired_app.svc.redis)
        )

        assert sum(moved) == 1
        assert len(await _minors(wired_app, loop["id"])) == 1

    async def test_a_second_start_moves_nothing(self, wired_app, loops, monkeypatch):
        await _launched(loops)
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)

        assert await follow_minors(wired_app.svc.redis) == 1
        assert await follow_minors(wired_app.svc.redis) == 0

    async def test_a_downgrade_moves_back_without_a_changes_line(
        self, wired_app, loops, monkeypatch
    ):
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)
        loop = await _launched(loops)
        assert loop["cycle"]["engine_version"] == "1.1"
        _ship(monkeypatch, Spinoza, Leibniz, Buridan)

        assert await follow_minors(wired_app.svc.redis) == 1

        assert (await _cycle(loops, loop["key"]))["engine_version"] == "1.0"
        record = await _record(wired_app, loop["cycle"]["id"])
        assert record["policy_params"] == {"alpha_prior": 1.0, "beta_prior": 1.0}
        [change] = await _minors(wired_app, loop["id"])
        assert change["reason"] == f"Spinoza 1.1 → 1.0 with qbrix {VERSION}"

    async def test_the_history_shows_the_engine_version_moving(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops)
        _ship(monkeypatch, Spinoza, SpinozaOneOne, Leibniz, Buridan)
        await follow_minors(wired_app.svc.redis)

        history = await loops.get(f"/api/v1/loops/{loop['key']}/history")
        changes = await loops.get("/api/v1/changes", params={"who": "qbrix"})

        assert history.status_code == 200, history.text
        [entry] = [e for e in history.json()["entries"] if e["kind"] == "engine.minor"]
        assert entry["verb"] == "updated the engine of"
        assert entry["who"]["kind"] == "qbrix"
        assert changes.status_code == 200, changes.text
        [row] = changes.json()["changes"]
        assert {"field": "engine version", "before": "1.0", "after": "1.1"} in row[
            "diff"
        ]
        assert row["not_undoable_reason"].startswith("qbrix moves a cycle")
