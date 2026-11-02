"""integration tests for a workspace's milestones, a qbrix next surface.

invariants verified:
  milestones read newest first, in sentences made from current names, with the
  leader's change as a diff. a first leader says no one it came from. each
  filter narrows them and an unknown loop or metric is not found. they are never
  another workspace's, and a deleted draft's are gone. with next off the route
  doesn't exist.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

import pytest_asyncio

import proxysvc.config
from qbrixstore.event import MilestoneEvent

from proxysvc.core.actor import Actor
from proxysvc.next import next_routes

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
ACTOR = Actor.member("user-ada")
AT = 1_700_000_000_000
HOUR = 60 * 60 * 1000

OPTIONS = [
    {"name": "Ships today", "config": {}},
    {"name": "Pay in one tap", "config": {}},
]


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=3600,
        actor=ACTOR,
    )
    yield client
    app.router.routes[:] = routes


async def _live(wired_app, name: str = "Checkout headline") -> dict:
    loop = (
        await wired_app.svc.create_loop(
            TENANT, name=name, metric="purchase", options=OPTIONS, actor=ACTOR
        )
    ).value
    return (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)).value


def _event(loop: dict, kind: str, event_id: str, at_ms: int = AT, **payload):
    return MilestoneEvent(
        event_id=event_id,
        kind=kind,
        tenant_id=TENANT,
        loop_id=loop["id"],
        cycle_id=loop["cycle"]["id"],
        payload=payload,
        at_ms=at_ms,
    )


def _sentence(event: dict) -> str:
    return "".join(p.get("text") or p.get("name") or "" for p in event["pieces"])


async def _milestones(api, **params) -> list[dict]:
    resp = await api.get("/api/v1/milestones", params=params)
    assert resp.status_code == 200
    return resp.json()["milestones"]


class TestSentences:
    async def test_a_new_leader_names_where_the_lead_came_from(self, wired_app, api):
        loop = await _live(wired_app)
        wired_app.ledger.reach(
            _event(loop, "loop.leader_changed", "l1", **{"from": 0, "to": 1})
        )

        event = (await _milestones(api))[0]

        assert _sentence(event) == "Pay in one tap took the lead from Ships today."
        assert event["pieces"][0] == {
            "kind": "option",
            "name": "Pay in one tap",
            "text": None,
        }
        assert event["diff"] == [
            {"field": "leader", "before": "Ships today", "after": "Pay in one tap"}
        ]
        assert event["source"] == "qbrix"
        assert event["cycle_id"] == loop["cycle"]["id"]
        assert event["loop"]["key"] == loop["key"]

    async def test_a_first_leader_names_no_one_before_it(self, wired_app, api):
        loop = await _live(wired_app)
        wired_app.ledger.reach(
            _event(loop, "loop.leader_changed", "l1", **{"from": None, "to": 0})
        )

        event = (await _milestones(api))[0]

        assert _sentence(event) == "Ships today took the lead."
        assert event["diff"] == [
            {"field": "leader", "before": None, "after": "Ships today"}
        ]

    async def test_the_first_seal_names_the_loop(self, wired_app, api):
        loop = await _live(wired_app)
        wired_app.ledger.reach(_event(loop, "loop.first_seal", "s1"))

        event = (await _milestones(api))[0]

        assert _sentence(event) == "Checkout headline's first window sealed."
        assert event["diff"] == []

    async def test_a_first_call_names_who_called(self, wired_app, api):
        loop = await _live(wired_app)
        wired_app.ledger.reach(_event(loop, "loop.first_call", "c1", source="web-prod"))

        event = (await _milestones(api))[0]

        assert _sentence(event) == "web-prod made the first call to Checkout headline."
        assert event["source"] == "web-prod"

    async def test_a_first_call_with_no_key_says_the_api(self, wired_app, api):
        loop = await _live(wired_app)
        wired_app.ledger.reach(_event(loop, "loop.first_call", "c1", source=None))

        event = (await _milestones(api))[0]

        assert _sentence(event).startswith("the API made the first call")
        assert event["source"] == "the API"


class TestList:
    async def test_it_reads_newest_first(self, wired_app, api):
        loop = await _live(wired_app)
        wired_app.ledger.reach(_event(loop, "loop.first_seal", "old", AT - HOUR))
        wired_app.ledger.reach(
            _event(loop, "loop.leader_changed", "new", AT, **{"to": 0})
        )

        assert [e["id"] for e in await _milestones(api)] == ["new", "old"]

    async def test_events_within_ten_minutes_of_the_same_kind_fold(
        self, wired_app, api
    ):
        loop = await _live(wired_app)
        for i, at in enumerate((AT, AT - 60_000, AT - HOUR)):
            wired_app.ledger.reach(
                _event(loop, "loop.leader_changed", f"l{i}", at, **{"to": 0})
            )

        found = await _milestones(api)

        assert [(e["id"], e["count"]) for e in found] == [("l0", 2), ("l2", 1)]
        assert found[0]["first_at"] is not None

    async def test_it_filters_by_loop_metric_kind_and_since(self, wired_app, api):
        loop = await _live(wired_app)
        other = await _live(wired_app, "Pricing page")
        wired_app.ledger.reach(_event(loop, "loop.first_seal", "a", AT))
        wired_app.ledger.reach(_event(other, "loop.first_seal", "b", AT - HOUR))
        wired_app.ledger.reach(
            _event(loop, "loop.leader_changed", "c", AT - 2 * HOUR, **{"to": 0})
        )

        ids = lambda found: {e["id"] for e in found}
        assert ids(await _milestones(api, loop=loop["key"])) == {"a", "c"}
        assert ids(await _milestones(api, metric="purchase")) == {"a", "b", "c"}
        assert ids(await _milestones(api, kind="loop.first_seal")) == {"a", "b"}
        since = datetime.fromtimestamp((AT - HOUR) / 1000, timezone.utc).isoformat()
        assert ids(await _milestones(api, since=since)) == {"a", "b"}

    async def test_an_unknown_loop_or_metric_is_not_found(self, api):
        loop = await api.get("/api/v1/milestones", params={"loop": "nope"})
        metric = await api.get("/api/v1/milestones", params={"metric": "nope"})

        assert (loop.status_code, metric.status_code) == (404, 404)

    async def test_it_is_never_another_workspaces(self, wired_app, api):
        loop = await _live(wired_app)
        wired_app.ledger.reach(_event(loop, "loop.first_seal", "a"))

        with as_tenant(wired_app.app, "other-tenant"):
            assert await _milestones(api) == []
            refused = await api.get("/api/v1/milestones", params={"loop": loop["key"]})

        assert refused.status_code == 404

    async def test_a_deleted_drafts_events_are_gone(self, wired_app, api):
        loop = (
            await wired_app.svc.create_loop(
                TENANT, name="Gone", metric="purchase", options=OPTIONS, actor=ACTOR
            )
        ).value
        wired_app.ledger.reach(
            MilestoneEvent(
                event_id="c1",
                kind="loop.first_call",
                tenant_id=TENANT,
                loop_id=loop["id"],
                cycle_id="",
                payload={"source": None},
                at_ms=AT,
            )
        )
        await wired_app.svc.loops.delete_loop(TENANT, loop["id"], actor=ACTOR)

        assert await _milestones(api) == []


class TestSwitchedOff:
    async def test_the_route_doesnt_exist(self, client):
        assert (await client.get("/api/v1/milestones")).status_code == 404
