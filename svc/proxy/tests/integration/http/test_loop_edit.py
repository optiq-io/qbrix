"""integration tests for editing a loop's brief and applying staged edits.

invariants verified:
  a brief change sets a loop's purpose and owner, who must be a member of the
  workspace, as one brief.update with before and after, and undoes. on a draft
  it also takes the options, engine, metric and fallback; past draft those are
  refused, since they start a new cycle. edits staged across a loop's tabs
  apply in one transaction, one change per kind sharing the request id: past
  draft everything that needs a cycle (options, engine, metric, the fallback,
  and the context when the new cycle's engine learns from it) starts exactly
  one cycle.start; a context alone on leibniz stays context.update and starts
  the cycle; on a draft nothing starts a cycle. a new metric's cycle pins that
  metric's newest version. a check returns the plan the apply then carries
  out and changes nothing; a refused part refuses the whole apply, naming the
  part, and nothing is half applied.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

import proxysvc.config
from qbrixstore.postgres import session as session_module
from qbrixstore.postgres.models import User

from proxysvc.core.actor import Actor
from proxysvc.core.error import LoopStateError
from proxysvc.next import next_routes

TENANT = "dev-tenant"
UNDOER = Actor.member("user-undo", request_id="req-undo")

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
}
SIGNUP = {"name": "signup", "semantic": "a new account", "type": "conversion"}

HEADLINE = {
    "name": "Checkout headline",
    "purpose": "find the headline that converts",
    "metric": "purchase",
    "options": [
        {"name": "Control", "config": {"text": "Buy now"}},
        {"name": "Urgency", "config": {"text": "Only today"}},
    ],
}
OPTIONS = [
    {"key": "control", "name": "Control", "config": {"text": "Buy now"}},
    {"key": "urgency", "name": "Urgency", "config": {"text": "Only today"}},
    {"key": "social", "name": "Social proof", "config": {"text": "1,000 bought"}},
]
PLAN = {"name": "plan", "type": "categorical", "values": ["free", "pro"]}
RETURNING = {"name": "returning", "type": "boolean"}
MOBILE = [{"property": "device", "operator": "is", "value": "mobile"}]


@pytest_asyncio.fixture
async def loops(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    for metric in (PURCHASE, SIGNUP):
        resp = await client.post("/api/v1/metrics", json=metric)
        assert resp.status_code == 201, resp.text
    async with session_module.get_session() as session:
        for user_id, name in (("dev-user", "Dev"), ("user-ana", "Ana")):
            session.add(
                User(
                    id=user_id,
                    tenant_id=TENANT,
                    email=f"{name.lower()}@example.com",
                    password_hash="x",
                    name=name,
                )
            )
    yield client
    app.router.routes[:] = routes


async def _create(client, **overrides) -> dict:
    resp = await client.post("/api/v1/loops", json={**HEADLINE, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _launched(client) -> dict:
    loop = await _create(client)
    resp = await client.post(f"/api/v1/loops/{loop['key']}/launch")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _on_leibniz(client) -> dict:
    loop = await _create(client)
    resp = await client.put(
        f"/api/v1/loops/{loop['key']}/context", json={"context": [PLAN]}
    )
    assert resp.status_code == 200, resp.text
    await client.post(f"/api/v1/loops/{loop['key']}/launch")
    resp = await client.post(
        f"/api/v1/loops/{loop['key']}/cycles", json={"engine": "leibniz"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["loop"]


async def _apply(client, ref: str, body: dict, **headers):
    return await client.post(f"/api/v1/loops/{ref}/edits", json=body, headers=headers)


async def _applied(client, ref: str, body: dict) -> dict:
    resp = await _apply(client, ref, body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _check(client, ref: str, body: dict):
    return await client.post(f"/api/v1/loops/{ref}/edits/check", json=body)


async def _changes(wired_app, loop_id: str) -> list[dict]:
    return await wired_app.svc.list_changes(TENANT, "loop", loop_id)


async def _cycles(client, ref: str) -> list[dict]:
    resp = await client.get(f"/api/v1/loops/{ref}/cycles")
    assert resp.status_code == 200, resp.text
    return resp.json()["cycles"]


def _kinds(edited: dict) -> list[str]:
    return [change["kind"] for change in edited["changes"]]


class TestBrief:
    async def test_purpose_and_owner_are_one_change_that_undoes(self, wired_app, loops):
        loop = await _launched(loops)

        edited = await _applied(
            loops,
            loop["key"],
            {
                "brief": {"purpose": "lift checkout", "owner": "ana@example.com"},
                "reason": "ana runs checkout now",
            },
        )

        assert _kinds(edited) == ["brief.update"]
        assert edited["changes"][0]["undoable"] is True
        assert edited["cycle"] is None
        assert edited["loop"]["purpose"] == "lift checkout"
        assert edited["loop"]["owner"] == {"id": "user-ana", "name": "Ana"}
        change, *_ = await _changes(wired_app, loop["id"])
        assert change["kind"] == "brief.update"
        assert change["reason"] == "ana runs checkout now"
        assert change["before"]["purpose"] == "find the headline that converts"
        assert change["after"]["owner"]["id"] == "user-ana"

        await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)

        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert read["purpose"] == "find the headline that converts"
        assert read["owner"]["id"] == loop["owner"]["id"]

    async def test_the_history_says_what_moved(self, wired_app, loops):
        loop = await _launched(loops)
        await _applied(loops, loop["key"], {"brief": {"owner": "user-ana"}})

        page = await wired_app.svc.list_workspace_changes(
            TENANT, loop=loop["id"], fold=False, limit=1
        )

        [entry] = page["changes"]
        assert entry["verb"] == "changed the brief of"
        assert {d["field"]: d["after"] for d in entry["diff"]} == {"owner": "Ana"}

    async def test_an_owner_outside_the_workspace_is_refused(self, loops):
        loop = await _launched(loops)

        resp = await _apply(loops, loop["key"], {"brief": {"owner": "nobody@x.io"}})

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"].startswith(
            "brief: the owner must be a member of this workspace"
        )

    async def test_nothing_changing_is_refused(self, loops):
        loop = await _launched(loops)

        resp = await _apply(loops, loop["key"], {"brief": {"purpose": loop["purpose"]}})

        assert resp.status_code == 400, resp.text
        assert "brief: nothing changes" in resp.json()["detail"]

    async def test_past_draft_its_options_start_a_cycle_instead(self, wired_app, loops):
        loop = await _launched(loops)

        with pytest.raises(LoopStateError, match="start a new cycle instead"):
            await wired_app.svc.loops.update_brief(
                TENANT, loop["key"], metric="signup", actor=UNDOER
            )

    async def test_a_retired_loop_keeps_its_brief_editable(self, loops):
        loop = await _launched(loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/retire")

        edited = await _applied(loops, loop["key"], {"brief": {"purpose": "gone"}})

        assert edited["loop"]["purpose"] == "gone"


class TestDraft:
    async def test_options_engine_and_metric_edit_the_brief_without_a_cycle(
        self, wired_app, loops
    ):
        loop = await _create(loops)

        edited = await _applied(
            loops,
            loop["key"],
            {
                "brief": {"purpose": "signups"},
                "cycle": {"options": OPTIONS, "engine": "buridan", "metric": "signup"},
                "delivery": {"fallback": "social"},
            },
        )

        assert _kinds(edited) == ["brief.update"]
        assert edited["changes"][0]["parts"] == ["brief", "cycle", "delivery"]
        assert edited["cycle"] is None
        draft = edited["loop"]
        assert draft["state"] == "draft"
        assert draft["cycle"] is None
        assert draft["metric"]["name"] == "signup"
        assert draft["engine"] == "buridan"
        assert draft["fallback"] == "social"
        assert [o["key"] for o in draft["options"]] == ["control", "urgency", "social"]

    async def test_undoing_a_draft_edit_restores_its_options_and_metric(
        self, wired_app, loops
    ):
        loop = await _create(loops)
        await _applied(
            loops, loop["key"], {"cycle": {"options": OPTIONS, "metric": "signup"}}
        )
        change, *_ = await _changes(wired_app, loop["id"])

        await wired_app.svc.undo_change(TENANT, change["id"], actor=UNDOER)

        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert read["metric"]["name"] == "purchase"
        assert [o["key"] for o in read["options"]] == ["control", "urgency"]

    async def test_a_context_and_leibniz_together_apply_in_order(self, loops):
        loop = await _create(loops)

        edited = await _applied(
            loops,
            loop["key"],
            {"cycle": {"engine": "leibniz"}, "context": {"context": [PLAN]}},
        )

        assert _kinds(edited) == ["context.update", "brief.update"]
        assert edited["loop"]["engine"].startswith("leibniz")
        assert edited["loop"]["context"] == [PLAN]


class TestApplyTogether:
    async def test_options_delivery_and_context_on_spinoza_are_three_changes(
        self, wired_app, loops
    ):
        loop = await _launched(loops)

        resp = await _apply(
            loops,
            loop["key"],
            {
                "cycle": {"options": OPTIONS},
                "delivery": {"audience": MOBILE, "rollout": 50},
                "context": {"context": [PLAN]},
                "reason": "staged on three tabs",
            },
            **{"X-Request-ID": "req-apply-1"},
        )

        assert resp.status_code == 200, resp.text
        edited = resp.json()
        assert _kinds(edited) == ["cycle.start", "context.update", "delivery.update"]
        assert [c["parts"] for c in edited["changes"]] == [
            ["cycle"],
            ["context"],
            ["delivery"],
        ]
        assert edited["cycle"] == 2
        assert len(await _cycles(loops, loop["key"])) == 2
        changes = (await _changes(wired_app, loop["id"]))[:3]
        assert {c["request_id"] for c in changes} == {"req-apply-1"}
        assert {c["reason"] for c in changes} == {"staged on three tabs"}
        assert edited["loop"]["cycle"]["context"] is None
        assert edited["loop"]["delivery"]["rollout"] == 50

    async def test_an_option_and_leibniz_together_start_exactly_one_cycle(
        self, wired_app, loops
    ):
        loop = await _launched(loops)

        edited = await _applied(
            loops,
            loop["key"],
            {
                "cycle": {"options": OPTIONS, "engine": "leibniz"},
                "context": {"context": [PLAN]},
            },
        )

        assert _kinds(edited) == ["cycle.start"]
        assert edited["changes"][0]["parts"] == ["cycle", "context"]
        assert edited["cycle"] == 2
        assert len(await _cycles(loops, loop["key"])) == 2
        assert edited["loop"]["cycle"]["context"] == [PLAN]
        route = await wired_app.svc.loops._routes.get(TENANT, loop["key"])
        assert route.cycle.context is not None

    async def test_a_context_alone_on_leibniz_stays_its_own_kind(self, loops):
        loop = await _on_leibniz(loops)

        edited = await _applied(
            loops,
            loop["key"],
            {
                "context": {"context": [PLAN, RETURNING]},
                "delivery": {"rollout": 20},
            },
        )

        assert _kinds(edited) == ["context.update", "delivery.update"]
        assert edited["changes"][0]["undoable"] is False
        assert edited["cycle"] == 3

    async def test_a_new_metric_starts_a_cycle_pinning_its_version(self, loops):
        loop = await _launched(loops)

        edited = await _applied(loops, loop["key"], {"cycle": {"metric": "signup"}})

        assert _kinds(edited) == ["cycle.start"]
        assert edited["loop"]["metric"]["name"] == "signup"
        current, earlier = await _cycles(loops, loop["key"])
        assert current["number"] == 2
        assert current["metric_version"] == "1.0"
        assert earlier["ended_at"] is not None

    async def test_the_fallback_rides_with_the_cycle_that_drops_its_option(self, loops):
        loop = await _launched(loops)

        edited = await _applied(
            loops,
            loop["key"],
            {
                "cycle": {"options": OPTIONS[1:]},
                "delivery": {"fallback": "social"},
            },
        )

        assert _kinds(edited) == ["cycle.start"]
        assert edited["changes"][0]["parts"] == ["cycle", "delivery"]
        assert edited["loop"]["fallback"] == "social"

    async def test_a_paused_loop_stays_paused(self, loops):
        loop = await _launched(loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/pause")

        edited = await _applied(loops, loop["key"], {"cycle": {"options": OPTIONS}})

        assert edited["loop"]["state"] == "paused"
        assert edited["cycle"] == 2


class TestCheck:
    BODY = {
        "brief": {"purpose": "lift checkout"},
        "cycle": {"options": OPTIONS},
        "delivery": {"rollout": 40},
    }

    async def test_it_is_the_plan_the_apply_carries_out(self, wired_app, loops):
        loop = await _launched(loops)
        before = await _changes(wired_app, loop["id"])

        checked = await _check(loops, loop["key"], self.BODY)

        assert checked.status_code == 200, checked.text
        plan = checked.json()
        assert plan == {
            "changes": [
                {
                    "id": None,
                    "kind": "brief.update",
                    "parts": ["brief"],
                    "undoable": True,
                },
                {
                    "id": None,
                    "kind": "cycle.start",
                    "parts": ["cycle"],
                    "undoable": False,
                },
                {
                    "id": None,
                    "kind": "delivery.update",
                    "parts": ["delivery"],
                    "undoable": True,
                },
            ],
            "cycle": 2,
        }
        assert await _changes(wired_app, loop["id"]) == before
        assert len(await _cycles(loops, loop["key"])) == 1
        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert read["purpose"] == loop["purpose"]

        applied = await _applied(loops, loop["key"], self.BODY)

        assert [
            {k: v for k, v in change.items() if k != "id"}
            for change in applied["changes"]
        ] == [
            {k: v for k, v in change.items() if k != "id"} for change in plan["changes"]
        ]
        assert applied["cycle"] == plan["cycle"]
        assert all(change["id"] for change in applied["changes"])

    async def test_it_refuses_what_the_apply_would(self, loops):
        loop = await _launched(loops)

        resp = await _check(loops, loop["key"], {"delivery": {"rollout": 400}})

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"].startswith("delivery: rollout")


class TestRefusals:
    async def test_a_refused_part_refuses_the_whole_apply(self, wired_app, loops):
        loop = await _launched(loops)
        before = await _changes(wired_app, loop["id"])
        route = await wired_app.svc.loops._routes.get(TENANT, loop["key"])

        resp = await _apply(
            loops,
            loop["key"],
            {
                "brief": {"purpose": "lift checkout"},
                "cycle": {"options": OPTIONS},
                "delivery": {"audience": [{"property": "device", "operator": "eq"}]},
            },
        )

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"].startswith("delivery: ")
        assert await _changes(wired_app, loop["id"]) == before
        assert len(await _cycles(loops, loop["key"])) == 1
        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert read["purpose"] == loop["purpose"]
        assert [o["key"] for o in read["options"]] == ["control", "urgency"]
        assert await wired_app.svc.loops._routes.get(TENANT, loop["key"]) == route

    async def test_a_committed_loop_says_to_reopen_it(self, wired_app, loops):
        loop = await _launched(loops)
        await loops.post(
            f"/api/v1/loops/{loop['key']}/commit", json={"option": "urgency"}
        )

        resp = await _apply(
            loops,
            loop["key"],
            {"brief": {"purpose": "lift"}, "cycle": {"options": OPTIONS}},
        )

        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "LOOP_NOT_CYCLABLE"
        assert resp.json()["detail"].startswith("cycle: ")
        assert "reopen it first" in resp.json()["detail"]
        read = await wired_app.svc.get_loop(TENANT, loop["id"])
        assert read["purpose"] == loop["purpose"]

    async def test_a_retired_loop_refuses_its_delivery(self, loops):
        loop = await _launched(loops)
        await loops.post(f"/api/v1/loops/{loop['key']}/retire")

        resp = await _apply(loops, loop["key"], {"delivery": {"rollout": 10}})

        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "LOOP_RETIRED"

    async def test_clearing_leibnizs_context_with_its_cycle_is_refused(self, loops):
        loop = await _on_leibniz(loops)

        resp = await _apply(
            loops,
            loop["key"],
            {"cycle": {"options": OPTIONS}, "context": {"context": None}},
        )

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"].startswith("context: ")

    async def test_an_empty_apply_is_refused(self, loops):
        loop = await _launched(loops)

        resp = await _apply(loops, loop["key"], {"reason": "nothing"})

        assert resp.status_code == 400, resp.text
        assert "at least one edit" in resp.json()["detail"]

    async def test_an_empty_part_is_refused(self, loops):
        loop = await _launched(loops)

        resp = await _apply(loops, loop["key"], {"delivery": {}})

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"].startswith("delivery: a delivery change needs")

    async def test_an_unknown_loop_is_not_found(self, loops):
        resp = await _apply(loops, "nope", {"brief": {"purpose": "x"}})

        assert resp.status_code == 404, resp.text


class TestStartCycleWithMetric:
    async def test_the_cycles_route_takes_a_metric(self, loops):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles", json={"metric": "signup"}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["loop"]["metric"]["name"] == "signup"
        assert resp.json()["loop"]["cycle"]["number"] == 2

    async def test_an_unknown_metric_is_refused(self, loops):
        loop = await _launched(loops)

        resp = await loops.post(
            f"/api/v1/loops/{loop['key']}/cycles", json={"metric": "nope"}
        )

        assert resp.status_code == 400, resp.text
        assert "no metric named or with id 'nope'" in resp.json()["detail"]
