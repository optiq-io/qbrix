"""integration tests for outcome(request_id, value), a qbrix next surface.

invariants verified:
  a valid outcome publishes one metric event for exactly its decision, with
  the loop's metric, the version the decision was opened under, an id and a
  time, and answers both. a value the metric's type doesn't accept is refused
  with the rule and counted invalid for the decision's cycle. a time before
  the decision or too far ahead is refused. a request_id that doesn't verify
  in this workspace is refused the same way whatever the reason, counted for
  the caller only, and never published.
"""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timezone

import pytest
import pytest_asyncio

import proxysvc.config
from proxysvc.core.actor import Actor
from proxysvc.mod.agent.token import SelectionToken
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken
from proxysvc.next import next_routes

TENANT = "dev-tenant"
ACTOR = Actor.member("user-ada")

OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    """the client with the next routes mounted, and a metric of every type."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    for name, metric_type, score_range in [
        ("purchase", "conversion", None),
        ("items", "count", None),
        ("revenue", "value", None),
        ("rating", "score", (1.0, 5.0)),
    ]:
        await wired_app.svc.create_metric(
            TENANT,
            name=name,
            semantic=f"the {name} after a decision",
            metric_type=metric_type,
            score_range=score_range,
            actor=ACTOR,
        )
    yield client
    app.router.routes[:] = routes


async def _decision(wired_app, api, metric: str = "purchase") -> tuple[dict, str]:
    """a live loop improving the metric, and one decision's request_id."""
    loop = (
        await wired_app.svc.create_loop(
            TENANT,
            name=f"Checkout {metric}",
            metric=metric,
            options=OPTIONS,
            actor=ACTOR,
        )
    ).value
    loop = (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)).value
    wired_app.motor_mock.select.side_effect = None
    wired_app.motor_mock.select.return_value = {
        "arm": {"id": "ignored", "name": "ignored", "index": 1},
        "policy": "BetaTSPolicy",
    }
    resp = await api.post(
        "/api/v1/select", json={"loop": loop["key"], "context": {"unit": "user-42"}}
    )
    await wired_app.events.drain()
    return loop, resp.json()["request_id"]


async def _outcome(wired_app, api, request_id: str, value, **extra):
    resp = await api.post(
        "/api/v1/outcome", json={"request_id": request_id, "value": value, **extra}
    )
    await wired_app.events.drain()
    return resp


def _decoded(wired_app, request_id: str) -> Decision:
    return DecisionToken.decode(
        wired_app.svc._settings.token_secret_bytes, request_id, TENANT
    )


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


async def _invalid_count(wired_app, cycle_id: str) -> int:
    health = await wired_app.svc._redis.outcome_health(TENANT, cycle_id, 5)
    return health.by_reason.get("invalid", 0)


class TestAccepted:
    async def test_publishes_one_event_for_its_decision(self, wired_app, api):
        loop, request_id = await _decision(wired_app, api)
        decision = _decoded(wired_app, request_id)
        before = int(time.time() * 1000)

        resp = await _outcome(wired_app, api, request_id, 1)

        assert resp.status_code == 202, resp.text
        (event,) = wired_app.metric_spy.events
        metric = await wired_app.svc.get_metric(TENANT, "purchase")
        assert event.tenant_id == TENANT
        assert event.metric_id == metric["id"]
        assert event.metric_version == "1.0"
        assert event.value == 1.0
        assert event.unit == "user-42"
        assert event.source == "outcome"
        assert event.decisions == [
            {
                "decision_id": decision.decision_id,
                "loop_id": loop["id"],
                "cycle_id": decision.cycle_id,
                "option_index": 1,
                "opened_ms": decision.timestamp_ms,
            }
        ]
        assert before <= event.at_ms == event.received_ms
        assert resp.json() == {"id": event.event_id, "at": _iso(event.at_ms)[:-6] + "Z"}

    async def test_keeps_the_callers_id_and_time(self, wired_app, api):
        _, request_id = await _decision(wired_app, api)
        at_ms = _decoded(wired_app, request_id).timestamp_ms + 1_000

        resp = await _outcome(
            wired_app, api, request_id, 0, id="order-991", at=_iso(at_ms)
        )

        assert resp.status_code == 202, resp.text
        (event,) = wired_app.metric_spy.events
        assert (event.event_id, event.at_ms) == ("order-991", at_ms)
        assert resp.json()["id"] == "order-991"

    async def test_a_repeat_is_recorded_for_the_sealer(self, wired_app, api):
        _, request_id = await _decision(wired_app, api)

        await _outcome(wired_app, api, request_id, 1, id="order-991")
        await _outcome(wired_app, api, request_id, 1, id="order-991")

        assert [e.event_id for e in wired_app.metric_spy.events] == [
            "order-991",
            "order-991",
        ]

    async def test_a_paused_loop_still_takes_outcomes(self, wired_app, api):
        loop, request_id = await _decision(wired_app, api)
        routes = wired_app.svc._loop_select_service._routes
        route = await routes.get(TENANT, loop["id"])
        await routes.put(TENANT, route.model_copy(update={"state": "paused"}))

        resp = await _outcome(wired_app, api, request_id, 1)

        assert resp.status_code == 202, resp.text
        assert len(wired_app.metric_spy.events) == 1

    @pytest.mark.parametrize(
        "metric, value",
        [
            ("purchase", 0),
            ("purchase", 1.0),
            ("items", 3),
            ("items", 4.0),
            ("revenue", -12.5),
            ("rating", 1),
            ("rating", 4.5),
        ],
    )
    async def test_every_valid_value_is_accepted(self, wired_app, api, metric, value):
        _, request_id = await _decision(wired_app, api, metric)

        resp = await _outcome(wired_app, api, request_id, value)

        assert resp.status_code == 202, resp.text
        assert wired_app.metric_spy.events[0].value == float(value)


class TestInvalidValue:
    @pytest.mark.parametrize(
        "metric, value, rule",
        [
            ("purchase", 2, "a conversion is 0 or 1"),
            ("purchase", 0.5, "a conversion is 0 or 1"),
            ("items", -1, "a count is a whole number of 0 or more"),
            ("items", 1.5, "a count is a whole number of 0 or more"),
            ("rating", 6, "a score for this metric is between 1 and 5"),
            ("revenue", "12", "value must be a number"),
            ("revenue", True, "value must be a number"),
            ("revenue", None, "value must be a number"),
        ],
    )
    async def test_is_refused_with_its_rule_and_counted(
        self, wired_app, api, metric, value, rule
    ):
        _, request_id = await _decision(wired_app, api, metric)
        cycle_id = _decoded(wired_app, request_id).cycle_id

        resp = await _outcome(wired_app, api, request_id, value)

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_OUTCOME"
        assert rule in resp.json()["detail"]
        assert wired_app.metric_spy.events == []
        assert await _invalid_count(wired_app, cycle_id) == 1

    async def test_a_non_finite_value_is_refused(self, wired_app, api):
        _, request_id = await _decision(wired_app, api, "revenue")
        cycle_id = _decoded(wired_app, request_id).cycle_id

        resp = await api.post(
            "/api/v1/outcome",
            content=f'{{"request_id": "{request_id}", "value": Infinity}}',
            headers={"content-type": "application/json"},
        )
        await wired_app.events.drain()

        assert resp.status_code == 400
        assert "finite" in resp.json()["detail"]
        assert await _invalid_count(wired_app, cycle_id) == 1


class TestTimeAndId:
    async def test_a_time_before_the_decision_is_refused(self, wired_app, api):
        _, request_id = await _decision(wired_app, api)
        before = _decoded(wired_app, request_id).timestamp_ms - 1_000

        resp = await _outcome(wired_app, api, request_id, 1, at=_iso(before))

        assert resp.status_code == 400
        assert "earlier than the decision" in resp.json()["detail"]
        assert wired_app.metric_spy.events == []

    async def test_a_time_far_ahead_is_refused(self, wired_app, api):
        _, request_id = await _decision(wired_app, api)
        ahead = int(time.time() * 1000) + 6 * 60 * 1000

        resp = await _outcome(wired_app, api, request_id, 1, at=_iso(ahead))

        assert resp.status_code == 400
        assert "5 minutes ahead" in resp.json()["detail"]
        assert wired_app.metric_spy.events == []

    async def test_a_time_without_an_offset_is_utc(self, wired_app, api):
        _, request_id = await _decision(wired_app, api)
        at_ms = _decoded(wired_app, request_id).timestamp_ms + 1_000
        naive = datetime.fromtimestamp(at_ms / 1000, tz=timezone.utc).replace(
            tzinfo=None
        )

        resp = await _outcome(wired_app, api, request_id, 1, at=naive.isoformat())

        assert resp.status_code == 202, resp.text
        assert wired_app.metric_spy.events[0].at_ms == at_ms

    @pytest.mark.parametrize("bad_id", ["", "   ", 42, "x" * 257])
    async def test_a_bad_id_is_refused(self, wired_app, api, bad_id):
        _, request_id = await _decision(wired_app, api)

        resp = await _outcome(wired_app, api, request_id, 1, id=bad_id)

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_OUTCOME"
        assert wired_app.metric_spy.events == []


class TestRequestId:
    async def test_another_workspaces_decision_reads_as_forged(self, wired_app, api):
        _, request_id = await _decision(wired_app, api)
        decision = _decoded(wired_app, request_id)
        secret = wired_app.svc._settings.token_secret_bytes
        foreign = DecisionToken.encode(
            secret,
            Decision(**{**decision.__dict__, "tenant_id": "tenant-elsewhere"}),
        )
        forged = request_id[:-1] + ("A" if request_id[-1] != "A" else "B")

        from_elsewhere = await _outcome(wired_app, api, foreign, 1)
        tampered = await _outcome(wired_app, api, forged, 1)

        assert from_elsewhere.status_code == 400
        assert from_elsewhere.json() == tampered.json()
        assert from_elsewhere.json()["code"] == "INVALID_REQUEST_ID"
        assert wired_app.metric_spy.events == []
        redis = wired_app.svc._redis
        assert await redis.invalid_outcomes(TENANT, window_minutes=5) == 2
        assert await _invalid_count(wired_app, decision.cycle_id) == 0
        assert await wired_app.fake_redis.keys("qbrix:tenant:tenant-elsewhere:*") == []

    async def test_a_selection_token_is_no_decision(self, wired_app, api):
        token = SelectionToken.encode(
            secret=wired_app.svc._settings.token_secret_bytes,
            tenant_id=TENANT,
            experiment_id="exp-1",
            arm_index=0,
            context_id="ctx",
            context_vector=[],
            context_metadata={},
        )

        resp = await _outcome(wired_app, api, token, 1)

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_REQUEST_ID"
        assert wired_app.metric_spy.events == []

    async def test_a_deleted_loops_decision_is_not_found(self, wired_app, api):
        loop, request_id = await _decision(wired_app, api)
        await wired_app.svc._loop_select_service._routes.drop(
            TENANT, loop["id"], loop["key"]
        )

        resp = await _outcome(wired_app, api, request_id, 1)

        assert resp.status_code == 404
        assert resp.json()["code"] == "LOOP_NOT_FOUND"
        assert wired_app.metric_spy.events == []


class TestFeedbackUntouched:
    async def test_an_outcome_reaches_neither_feedback_nor_selection(
        self, wired_app, api
    ):
        _, request_id = await _decision(wired_app, api)
        wired_app.selection_spy.events.clear()

        await _outcome(wired_app, api, request_id, 1)

        assert wired_app.feedback_spy.events == []
        assert wired_app.selection_spy.events == []
