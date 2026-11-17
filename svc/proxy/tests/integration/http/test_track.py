"""integration tests for track(metric, value, {decisions, unit, id, at}), a
qbrix next surface.

invariants verified:
  an event carrying a decisions token publishes one metric event that credits
  exactly the decisions in it whose loop improves the metric, from every such
  loop. an entry for a loop on another metric, or opened after the event, is
  not credited; when none is left the event is recorded with neither decisions
  nor a unit, so nothing can match it. an entry that doesn't verify in this
  workspace is dropped and counted; a token with none that verifies is
  refused. an event without decisions is published with its unit for the
  sealer to match. a value the metric's type refuses is refused with the rule
  and counted for the metric. a batch answers each event in order, and one
  bad event never refuses the rest.
"""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timezone

import pytest
import pytest_asyncio

import proxysvc.config
from proxysvc.core.actor import Actor
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken
from proxysvc.mod.loop.token import DecisionsToken
from proxysvc.next import next_routes

TENANT = "dev-tenant"
ACTOR = Actor.member("user-ada")

OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    """the client with the next routes mounted, and three metrics."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    for name, metric_type in [
        ("purchase", "conversion"),
        ("add_to_cart", "conversion"),
        ("revenue", "value"),
    ]:
        await wired_app.svc.create_metric(
            TENANT,
            name=name,
            semantic=f"the {name} after a decision",
            metric_type=metric_type,
            actor=ACTOR,
        )
    wired_app.motor_mock.select.side_effect = None
    wired_app.motor_mock.select.return_value = {
        "arm": {"id": "ignored", "name": "ignored", "index": 1},
        "policy": "BetaTSPolicy",
    }
    yield client
    app.router.routes[:] = routes


async def _decision(wired_app, api, name: str, metric: str = "purchase") -> str:
    """a live loop improving the metric, and one decision's request_id."""
    loop = (
        await wired_app.svc.create_loop(
            TENANT, name=name, metric=metric, options=OPTIONS, actor=ACTOR
        )
    ).value
    loop = (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)).value
    resp = await api.post(
        "/api/v1/select", json={"loop": loop["key"], "context": {"unit": "user-42"}}
    )
    await wired_app.events.drain()
    return resp.json()["request_id"]


async def _track(wired_app, api, body: dict):
    resp = await api.post("/api/v1/track", json=body)
    await wired_app.events.drain()
    return resp


def _decoded(wired_app, request_id: str) -> Decision:
    return DecisionToken.decode(
        wired_app.svc._settings.token_secret_bytes, request_id, TENANT
    )


def _ref(decision: Decision) -> dict:
    return {
        "decision_id": decision.decision_id,
        "loop_id": decision.loop_id,
        "cycle_id": decision.cycle_id,
        "option_index": decision.option_index,
        "opened_ms": decision.timestamp_ms,
    }


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


async def _metric_id(wired_app, name: str) -> str:
    return (await wired_app.svc.get_metric(TENANT, name))["id"]


async def _metric_invalid(wired_app, name: str) -> int:
    counts = await wired_app.svc._redis.metric_outcomes(
        TENANT, await _metric_id(wired_app, name), 5
    )
    return counts.get("invalid", 0)


class TestDecisions:
    async def test_credits_every_loop_improving_the_metric(self, wired_app, api):
        first = await _decision(wired_app, api, "Checkout button")
        second = await _decision(wired_app, api, "Checkout headline")
        token = DecisionsToken.join([first, second])

        resp = await _track(
            wired_app,
            api,
            {"metric": "purchase", "value": 1, "decisions": token, "id": "order-7"},
        )

        assert resp.status_code == 202, resp.text
        assert resp.json()["credited"] == 2
        assert resp.json()["id"] == "order-7"
        (event,) = wired_app.metric_spy.events
        assert event.metric_id == await _metric_id(wired_app, "purchase")
        assert event.source == "track"
        assert event.value == 1.0
        assert event.unit == ""
        assert event.decisions == [
            _ref(_decoded(wired_app, first)),
            _ref(_decoded(wired_app, second)),
        ]

    async def test_a_loop_on_another_metric_is_not_credited(self, wired_app, api):
        purchase = await _decision(wired_app, api, "Checkout button")
        headline = await _decision(wired_app, api, "Headline", "add_to_cart")

        resp = await _track(
            wired_app,
            api,
            {
                "metric": "purchase",
                "value": 1,
                "decisions": DecisionsToken.join([headline, purchase]),
            },
        )

        assert resp.json()["credited"] == 1
        (event,) = wired_app.metric_spy.events
        assert event.decisions == [_ref(_decoded(wired_app, purchase))]

    async def test_none_for_the_metric_is_recorded_unmatchable(self, wired_app, api):
        headline = await _decision(wired_app, api, "Headline", "add_to_cart")

        resp = await _track(
            wired_app,
            api,
            {
                "metric": "purchase",
                "value": 1,
                "decisions": headline,
                "unit": "user-42",
            },
        )

        assert resp.status_code == 202, resp.text
        assert resp.json()["credited"] == 0
        (event,) = wired_app.metric_spy.events
        assert (event.decisions, event.unit) == ([], "")

    async def test_a_decision_opened_after_the_event_is_not_credited(
        self, wired_app, api
    ):
        request_id = await _decision(wired_app, api, "Checkout button")
        before = _decoded(wired_app, request_id).timestamp_ms - 1_000

        resp = await _track(
            wired_app,
            api,
            {
                "metric": "purchase",
                "value": 1,
                "decisions": request_id,
                "at": _iso(before),
            },
        )

        assert resp.json()["credited"] == 0
        assert wired_app.metric_spy.events[0].decisions == []

    async def test_a_forged_entry_is_dropped_and_counted(self, wired_app, api):
        request_id = await _decision(wired_app, api, "Checkout button")
        decision = _decoded(wired_app, request_id)
        foreign = DecisionToken.encode(
            wired_app.svc._settings.token_secret_bytes,
            Decision(**{**decision.__dict__, "tenant_id": "tenant-elsewhere"}),
        )
        forged = request_id[:-1] + ("A" if request_id[-1] != "A" else "B")

        resp = await _track(
            wired_app,
            api,
            {
                "metric": "purchase",
                "value": 1,
                "decisions": DecisionsToken.join([foreign, request_id, forged]),
            },
        )

        assert resp.json()["credited"] == 1
        (event,) = wired_app.metric_spy.events
        assert event.decisions == [_ref(decision)]
        redis = wired_app.svc._redis
        assert await redis.invalid_outcomes(TENANT, window_minutes=5) == 2

    async def test_a_token_with_nothing_that_verifies_is_refused(self, wired_app, api):
        request_id = await _decision(wired_app, api, "Checkout button")
        forged = request_id[:-1] + ("A" if request_id[-1] != "A" else "B")

        resp = await _track(
            wired_app, api, {"metric": "purchase", "value": 1, "decisions": forged}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_DECISIONS"
        assert wired_app.metric_spy.events == []

    @pytest.mark.parametrize("token", ["", "...", 42])
    async def test_an_empty_or_malformed_token_is_refused(self, wired_app, api, token):
        resp = await _track(
            wired_app, api, {"metric": "purchase", "value": 1, "decisions": token}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_DECISIONS"

    async def test_a_repeated_id_reaches_the_sealer_twice(self, wired_app, api):
        request_id = await _decision(wired_app, api, "Checkout button")
        body = {"metric": "purchase", "value": 1, "decisions": request_id, "id": "o-1"}

        await _track(wired_app, api, body)
        await _track(wired_app, api, body)

        assert [e.event_id for e in wired_app.metric_spy.events] == ["o-1", "o-1"]

    async def test_stamps_each_credited_cycle(self, wired_app, api):
        request_id = await _decision(wired_app, api, "Checkout button")
        cycle_id = _decoded(wired_app, request_id).cycle_id
        redis = wired_app.svc._redis
        key = (TENANT, cycle_id)
        before = (await redis.intakes([key]))[key].outcomes

        await _track(
            wired_app, api, {"metric": "purchase", "value": 1, "decisions": request_id}
        )

        assert (await redis.intakes([key]))[key].outcomes == before + 1


class TestUnit:
    async def test_is_published_for_the_sealer_to_match(self, wired_app, api):
        before = int(time.time() * 1000)

        resp = await _track(
            wired_app, api, {"metric": "revenue", "value": 49.5, "unit": "user-42"}
        )

        assert resp.status_code == 202, resp.text
        assert resp.json()["credited"] is None
        (event,) = wired_app.metric_spy.events
        assert event.metric_id == await _metric_id(wired_app, "revenue")
        assert (event.decisions, event.unit, event.value) == ([], "user-42", 49.5)
        assert before <= event.at_ms == event.received_ms

    @pytest.mark.parametrize("unit", [None, "", "  ", "x" * 257])
    async def test_neither_decisions_nor_a_good_unit_is_refused(
        self, wired_app, api, unit
    ):
        resp = await _track(
            wired_app, api, {"metric": "purchase", "value": 1, "unit": unit}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_OUTCOME"
        assert wired_app.metric_spy.events == []


class TestRefused:
    async def test_an_unknown_metric_is_not_found(self, wired_app, api):
        resp = await _track(
            wired_app, api, {"metric": "signup", "value": 1, "unit": "user-42"}
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "METRIC_NOT_FOUND"

    async def test_an_invalid_value_names_the_rule_and_is_counted(self, wired_app, api):
        request_id = await _decision(wired_app, api, "Checkout button")
        cycle_id = _decoded(wired_app, request_id).cycle_id

        resp = await _track(
            wired_app, api, {"metric": "purchase", "value": 2, "decisions": request_id}
        )

        assert resp.status_code == 400
        assert "a conversion is 0 or 1" in resp.json()["detail"]
        assert wired_app.metric_spy.events == []
        assert await _metric_invalid(wired_app, "purchase") == 1
        health = await wired_app.svc._redis.outcome_health(TENANT, cycle_id, 5)
        assert health.by_reason.get("invalid", 0) == 1

    async def test_a_time_far_ahead_is_refused(self, wired_app, api):
        ahead = int(time.time() * 1000) + 6 * 60 * 1000

        resp = await _track(
            wired_app,
            api,
            {"metric": "purchase", "value": 1, "unit": "u", "at": _iso(ahead)},
        )

        assert resp.status_code == 400
        assert "5 minutes ahead" in resp.json()["detail"]

    async def test_an_unknown_field_is_refused(self, wired_app, api):
        resp = await _track(
            wired_app,
            api,
            {"metric": "purchase", "value": 1, "unit": "u", "request_id": "x"},
        )

        assert resp.status_code == 422


class TestBatch:
    async def test_answers_each_event_in_order(self, wired_app, api):
        request_id = await _decision(wired_app, api, "Checkout button")
        events = [
            {"metric": "revenue", "value": float(i), "unit": f"user-{i}"}
            for i in range(500)
        ]
        events[3] = {"metric": "purchase", "value": 1, "decisions": request_id}
        events[7] = {"metric": "purchase", "value": 5, "unit": "user-7"}
        events[9] = {"metric": "signup", "value": 1, "unit": "user-9"}

        resp = await _track(wired_app, api, {"events": events})

        assert resp.status_code == 202, resp.text
        results = resp.json()["results"]
        assert len(results) == 500
        assert results[3]["credited"] == 1
        assert results[7]["error"]["code"] == "INVALID_OUTCOME"
        assert results[9]["error"]["code"] == "METRIC_NOT_FOUND"
        assert results[0]["credited"] is None and results[0]["error"] is None
        assert len(wired_app.metric_spy.events) == 498

    @pytest.mark.parametrize("size", [0, 501])
    async def test_an_empty_or_oversized_batch_is_refused(self, wired_app, api, size):
        events = [{"metric": "revenue", "value": 1, "unit": "u"}] * size

        resp = await _track(wired_app, api, {"events": events})

        assert resp.status_code == 422
        assert wired_app.metric_spy.events == []


class TestMetricCache:
    async def test_a_deleted_metric_is_forgotten(self, wired_app, api):
        created = await wired_app.svc.create_metric(
            TENANT,
            name="signup",
            semantic="a sign-up after a decision",
            metric_type="conversion",
            actor=ACTOR,
        )
        body = {"metric": "signup", "value": 1, "unit": "u"}
        assert (await _track(wired_app, api, body)).status_code == 202

        await wired_app.svc.undo_change(TENANT, created.change["id"], actor=ACTOR)

        assert (await _track(wired_app, api, body)).status_code == 404
