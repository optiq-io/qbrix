"""integration tests for switching a running cycle between following its
engine's major and staying on the minor it runs, a qbrix next surface.

invariants verified:
  staying on the running minor keeps the cycle, its record and what it
  learned, records one undoable engine.version, and upgrades leave it there.
  following again moves the cycle to the latest minor in the same request,
  as an engine.version by the actor and an engine.minor by qbrix, keeping
  what it learned. an undo restores the earlier spec; a second undo, an undo
  after the cycle moved or ended, and another minor, major or engine are
  refused with what to do instead. paused and committed loops switch too;
  drafts and retired loops don't. staged edits route a switch alone to
  engine.version and let it ride in a cycle.start when one starts anyway.
"""

from __future__ import annotations

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

from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopRetiredError
from proxysvc.core.error import LoopStateError
from proxysvc.mod.loop.upgrade import follow_minors
from proxysvc.next import next_routes

TENANT = "dev-tenant"
MEMBER = Actor.member("dev-user", request_id="req-switch")
UNDOER = Actor.member("user-undo", request_id="req-undo")
LEARNED = {"alpha": [3.0, 9.0], "beta": [5.0, 2.0]}

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
SOCIAL = {"key": "social", "name": "Social proof", "config": {"text": "1,000 bought"}}


class SpinozaOneOne(Spinoza):
    version = EngineVersion(1, 1)
    changes = "explores less once an option is clearly ahead"

    @classmethod
    def _resolve(cls, metric_type, score_range, context_dim):
        resolved = super()._resolve(metric_type, score_range, context_dim)
        if resolved.fixed_params.get("alpha_prior") is not None:
            return Resolved(
                resolved.policy_cls, {"alpha_prior": 0.5, "beta_prior": 0.5}
            )
        return resolved


def _ship_newer_minor(monkeypatch) -> None:
    engines = (Spinoza, SpinozaOneOne, Leibniz, Buridan)
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


async def _switch(wired_app, key: str, engine: str) -> dict:
    applied = await wired_app.svc.loops.update_engine_version(
        TENANT, key, engine=engine, actor=MEMBER, reason="audit"
    )
    assert applied is not None
    return applied


async def _loop(wired_app, key: str) -> dict:
    return await wired_app.svc.get_loop(TENANT, key)


async def _changes(wired_app, loop_id: str, *kinds: str) -> list[dict]:
    changes = await wired_app.svc.list_changes(TENANT, "loop", loop_id)
    return [change for change in changes if change["kind"] in kinds]


class TestStaying:

    async def test_it_keeps_the_cycle_and_what_it_learned(self, wired_app, loops):
        loop = await _launched(loops, engine="spinoza:1")
        cycle_id = loop["cycle"]["id"]
        await wired_app.svc.redis.set_params(TENANT, cycle_id, LEARNED)
        record = await _record(wired_app, cycle_id)

        await _switch(wired_app, loop["key"], "spinoza:1.0")

        read = await _loop(wired_app, loop["key"])
        assert read["engine"] == "spinoza:1.0"
        assert (read["cycle"]["id"], read["cycle"]["number"]) == (cycle_id, 1)
        assert read["cycle"]["engine"] == "spinoza:1.0"
        assert read["cycle"]["engine_version"] == "1.0"
        assert await _record(wired_app, cycle_id) == record
        assert await wired_app.svc.redis.get_params(TENANT, cycle_id) == LEARNED
        [change] = await _changes(wired_app, loop["id"], "engine.version")
        assert change["actor"]["kind"] == "member"
        assert change["undoable"] is True
        assert change["reason"] == "audit"

    async def test_an_upgrade_leaves_it_on_its_minor(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops)
        await _switch(wired_app, loop["key"], "spinoza:1.0")
        _ship_newer_minor(monkeypatch)

        assert await follow_minors(wired_app.svc.redis) == 0

        assert (await _loop(wired_app, loop["key"]))["cycle"]["engine_version"] == "1.0"

    async def test_the_history_reads_as_the_version_held(self, wired_app, loops):
        loop = await _launched(loops)
        await _switch(wired_app, loop["key"], "spinoza:1.0")

        history = await loops.get(f"/api/v1/loops/{loop['key']}/history")
        changes = await loops.get("/api/v1/changes")

        assert history.status_code == 200, history.text
        [entry] = [
            e for e in history.json()["entries"] if e["kind"] == "engine.version"
        ]
        assert entry["verb"] == "changed the engine version of"
        [row] = [r for r in changes.json()["changes"] if r["kind"] == "engine.version"]
        assert row["diff"] == [
            {
                "field": "engine version",
                "before": "follows 1.x",
                "after": "stays on 1.0",
            }
        ]

    @pytest.mark.parametrize("state", ["pause", "commit"])
    async def test_a_paused_or_committed_loop_switches_too(
        self, wired_app, loops, state
    ):
        loop = await _launched(loops)
        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/{state}", json={"option": "control"}
        )
        assert resp.status_code == 200, resp.text

        applied = await _switch(wired_app, loop["key"], "spinoza:1.0")

        assert applied.value["cycle"]["engine"] == "spinoza:1.0"


class TestFollowing:

    async def test_it_moves_to_the_newest_minor_in_the_same_request(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops, engine="spinoza:1.0")
        cycle_id = loop["cycle"]["id"]
        await wired_app.svc.redis.set_params(TENANT, cycle_id, LEARNED)
        _ship_newer_minor(monkeypatch)

        applied = await _switch(wired_app, loop["key"], "spinoza:1")

        assert applied.value["cycle"]["id"] == cycle_id
        assert applied.value["cycle"]["engine"] == "spinoza:1"
        assert applied.value["cycle"]["engine_version"] == "1.1"
        assert applied.value["engine"] == "spinoza:1"
        record = await _record(wired_app, cycle_id)
        assert record["policy_params"] == {"alpha_prior": 0.5, "beta_prior": 0.5}
        assert await wired_app.svc.redis.get_params(TENANT, cycle_id) == LEARNED
        minor, version = await _changes(
            wired_app, loop["id"], "engine.version", "engine.minor"
        )
        assert (version["kind"], version["actor"]["kind"]) == (
            "engine.version",
            "member",
        )
        assert (minor["kind"], minor["actor"]["kind"]) == ("engine.minor", "qbrix")

    async def test_with_nothing_newer_it_only_follows(self, wired_app, loops):
        loop = await _launched(loops, engine="spinoza:1.0")
        record = await _record(wired_app, loop["cycle"]["id"])

        applied = await _switch(wired_app, loop["key"], "spinoza:1")

        assert applied.value["cycle"]["engine_version"] == "1.0"
        assert await _record(wired_app, loop["cycle"]["id"]) == record
        assert await _changes(wired_app, loop["id"], "engine.minor") == []


class TestUndo:

    async def test_it_restores_the_earlier_spec_once(self, wired_app, loops):
        loop = await _launched(loops)
        await _switch(wired_app, loop["key"], "spinoza:1.0")
        [change] = await _changes(wired_app, loop["id"], "engine.version")

        undo = await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)

        assert undo["kind"] == "engine.version"
        read = await _loop(wired_app, loop["key"])
        assert read["cycle"]["engine"] == "spinoza:1"
        assert read["cycle"]["id"] == loop["cycle"]["id"]
        with pytest.raises(ChangeConflictError, match="already undone"):
            await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)

    async def test_after_a_new_cycle_it_is_refused(self, wired_app, loops):
        loop = await _launched(loops)
        await _switch(wired_app, loop["key"], "spinoza:1.0")
        [change] = await _changes(wired_app, loop["id"], "engine.version")
        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles",
            json={"options": [*HEADLINE["options"], SOCIAL]},
        )
        assert resp.status_code == 200, resp.text

        with pytest.raises(ChangeConflictError, match="has ended"):
            await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)

    async def test_after_following_moved_the_cycle_it_is_refused(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops, engine="spinoza:1.0")
        _ship_newer_minor(monkeypatch)
        await _switch(wired_app, loop["key"], "spinoza:1")
        [change] = await _changes(wired_app, loop["id"], "engine.version")

        with pytest.raises(ChangeConflictError, match="stay on 1.1 instead"):
            await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)


class TestRefused:

    @pytest.mark.parametrize(
        "engine, says",
        [
            ("spinoza:1.1", r"stay on the minor the cycle runs \(1.0\)"),
            ("spinoza:2", "moving to it starts a cycle"),
            ("buridan:1", "moving to it starts a cycle"),
            ("spinoza", "name the major: spinoza:1 follows its minors"),
            ("spinoza:1", "nothing changes: the cycle already follows spinoza:1"),
        ],
    )
    async def test_anything_but_a_switch(self, wired_app, loops, engine, says):
        loop = await _launched(loops)

        with pytest.raises(LoopInvalidError, match=says):
            await _switch(wired_app, loop["key"], engine)

    async def test_a_draft_switches_with_its_brief(self, wired_app, loops):
        loop = await _create(loops)

        with pytest.raises(LoopStateError, match="draft"):
            await _switch(wired_app, loop["key"], "spinoza:1.0")

    async def test_a_retired_loop(self, wired_app, loops):
        loop = await _launched(loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/retire")

        with pytest.raises(LoopRetiredError):
            await _switch(wired_app, loop["key"], "spinoza:1.0")


class TestEdits:

    async def test_a_switch_alone_is_one_undoable_change_and_no_cycle(
        self, wired_app, loops
    ):
        loop = await _launched(loops)
        body = {"cycle": {"engine": "spinoza:1.0"}, "delivery": {"rollout": 50}}

        checked = await loops.post(
            f"/api/v1/loops/{loop['key']}/edits/check", json=body
        )

        assert checked.status_code == 200, checked.text
        assert checked.json() == {
            "changes": [
                {
                    "id": None,
                    "kind": "engine.version",
                    "parts": ["cycle"],
                    "undoable": True,
                },
                {
                    "id": None,
                    "kind": "delivery.update",
                    "parts": ["delivery"],
                    "undoable": True,
                },
            ],
            "cycle": None,
        }
        applied = await loops.post(f"/api/v1/loops/{loop['key']}/edits", json=body)
        assert applied.status_code == 200, applied.text
        assert applied.json()["loop"]["cycle"]["id"] == loop["cycle"]["id"]
        assert applied.json()["loop"]["cycle"]["engine"] == "spinoza:1.0"

    async def test_with_a_new_option_it_rides_in_the_cycle(self, loops):
        loop = await _launched(loops)
        body = {
            "cycle": {
                "engine": "spinoza:1.0",
                "options": [
                    {"key": "control", **HEADLINE["options"][0]},
                    {"key": "urgency", **HEADLINE["options"][1]},
                    SOCIAL,
                ],
            }
        }

        checked = await loops.post(
            f"/api/v1/loops/{loop['key']}/edits/check", json=body
        )
        applied = await loops.post(f"/api/v1/loops/{loop['key']}/edits", json=body)

        assert checked.status_code == 200, checked.text
        assert [c["kind"] for c in checked.json()["changes"]] == ["cycle.start"]
        assert checked.json()["cycle"] == 2
        assert applied.json()["loop"]["cycle"]["engine"] == "spinoza:1.0"
        assert applied.json()["loop"]["cycle"]["number"] == 2

    async def test_following_again_writes_the_moved_record(
        self, wired_app, loops, monkeypatch
    ):
        loop = await _launched(loops, engine="spinoza:1.0")
        _ship_newer_minor(monkeypatch)

        applied = await loops.post(
            f"/api/v1/loops/{loop['key']}/edits",
            json={"cycle": {"engine": "spinoza:1"}},
        )

        assert applied.status_code == 200, applied.text
        assert applied.json()["cycle"] is None
        record = await _record(wired_app, loop["cycle"]["id"])
        assert record["policy_params"] == {"alpha_prior": 0.5, "beta_prior": 0.5}
