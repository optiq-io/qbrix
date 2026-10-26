"""integration tests for select(loop, context), a qbrix next surface.

invariants verified:
  a draft or paused loop answers its fallback with its reason, no request_id,
  no motor call and nothing in the ledger. a live loop answers the option
  motor chose from the current cycle with a request_id that decodes to a
  fresh decision, and records the decision with its unit, properties and
  the metric terms it will be sealed by. a missing unit is refused; an
  unknown loop is not found and counted nowhere. every answer is counted by
  its reason, and a live loop's failures by outcome per cycle. loop writes
  keep the route select reads current.
"""

from __future__ import annotations

import grpc
import pytest
import pytest_asyncio

import proxysvc.config
from proxysvc.core.actor import Actor
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
    """the client with the next routes mounted, and a metric to improve."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=2 * 24 * 60 * 60,
        actor=ACTOR,
    )
    yield client
    app.router.routes[:] = routes


async def _loop(wired_app, *, launch: bool = False, **overrides) -> dict:
    loop = await wired_app.svc.create_loop(
        TENANT,
        **{
            "name": "Checkout headline",
            "metric": "purchase",
            "options": OPTIONS,
            "actor": ACTOR,
            **overrides,
        },
    )
    if launch:
        loop = await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)
    return loop


def _motor_chooses(wired_app, index: int) -> None:
    wired_app.motor_mock.select.reset_mock()
    wired_app.motor_mock.select.side_effect = None
    wired_app.motor_mock.select.return_value = {
        "arm": {"id": "ignored", "name": "ignored", "index": index},
        "policy": "BetaTSPolicy",
    }


async def _select(api, loop: str, context: dict | None = None):
    return await api.post(
        "/api/v1/select",
        json={
            "loop": loop,
            "context": {"unit": "user-42"} if context is None else context,
        },
    )


async def _settled(wired_app) -> None:
    await wired_app.events.drain()


class TestDraft:
    async def test_answers_the_fallback_without_a_decision(self, wired_app, api):
        loop = await _loop(wired_app, fallback="urgency")
        wired_app.motor_mock.select.reset_mock()

        resp = await _select(api, loop["key"])
        await _settled(wired_app)

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "option": {
                "key": "urgency",
                "name": "Urgency",
                "config": {"text": "Only today"},
            },
            "request_id": None,
            "reason": "draft",
        }
        wired_app.motor_mock.select.assert_not_called()
        assert wired_app.selection_spy.events == []

    async def test_is_counted_by_its_reason(self, wired_app, api):
        loop = await _loop(wired_app)

        await _select(api, loop["key"])
        await _select(api, loop["id"])
        await _settled(wired_app)

        counts = await wired_app.svc._redis.loop_selects(TENANT, loop["id"], 5)
        assert counts == {"live": 0, "draft": 2, "paused": 0}


class TestPaused:
    async def test_answers_the_fallback_without_a_decision(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        routes = wired_app.svc._loop_select_service._routes
        route = await routes.get(TENANT, loop["id"])
        await routes.put(TENANT, route.model_copy(update={"state": "paused"}))
        wired_app.motor_mock.select.reset_mock()

        resp = await _select(api, loop["key"])
        await _settled(wired_app)

        assert resp.json()["reason"] == "paused"
        assert resp.json()["request_id"] is None
        assert resp.json()["option"]["key"] == "control"
        wired_app.motor_mock.select.assert_not_called()
        assert wired_app.selection_spy.events == []


class TestLive:
    async def test_answers_motors_choice_with_a_request_id(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 1)

        resp = await _select(api, loop["key"])

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reason"] == "live"
        assert body["option"] == {
            "key": "urgency",
            "name": "Urgency",
            "config": {"text": "Only today"},
        }
        assert body["request_id"]
        tenant, cycle_id, unit, *_ = wired_app.motor_mock.select.call_args.args
        assert (tenant, cycle_id, unit) == (TENANT, loop["cycle"]["id"], "user-42")

    async def test_the_request_id_decodes_to_its_decision(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 0)

        resp = await _select(api, loop["key"])
        decision = DecisionToken.decode(
            wired_app.svc._settings.token_secret_bytes,
            resp.json()["request_id"],
            TENANT,
        )

        assert decision.loop_id == loop["id"]
        assert decision.cycle_id == loop["cycle"]["id"]
        assert decision.option_index == 0
        assert decision.unit == "user-42"
        assert decision.metric_version == "1.0"
        assert decision.decision_id

    async def test_identical_calls_are_distinct_decisions(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 0)
        secret = wired_app.svc._settings.token_secret_bytes

        first = await _select(api, loop["key"])
        second = await _select(api, loop["key"])

        ids = {
            DecisionToken.decode(secret, r.json()["request_id"], TENANT).decision_id
            for r in (first, second)
        }
        assert len(ids) == 2

    async def test_records_the_decision_with_its_metric_terms(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 1)
        wired_app.selection_spy.events.clear()

        resp = await _select(
            api,
            loop["key"],
            {"unit": "user-42", "properties": {"device": "mobile", "seats": 3}},
        )
        await _settled(wired_app)

        (event,) = wired_app.selection_spy.events
        decision = DecisionToken.decode(
            wired_app.svc._settings.token_secret_bytes,
            resp.json()["request_id"],
            TENANT,
        )
        assert event.experiment_id == loop["cycle"]["id"]
        assert event.cycle_id == loop["cycle"]["id"]
        assert event.loop_id == loop["id"]
        assert event.decision_id == decision.decision_id
        assert event.request_id == resp.json()["request_id"]
        assert event.reason == "live"
        assert event.unit == "user-42"
        assert event.context_id == "user-42"
        assert event.properties == {"device": "mobile", "seats": 3}
        assert (event.arm_id, event.arm_name, event.arm_index) == (
            loop["options"][1]["id"],
            "urgency",
            1,
        )
        assert event.metric_id == loop["metric"]["id"]
        assert event.metric_version == "1.0"
        assert event.metric_type == "conversion"
        assert event.window_ms == 2 * 24 * 60 * 60 * 1000

    async def test_is_counted_by_reason_and_by_outcome(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 0)

        await _select(api, loop["key"])
        await _settled(wired_app)

        redis = wired_app.svc._redis
        assert (await redis.loop_selects(TENANT, loop["id"], 5))["live"] == 1
        assert (await redis.select_health(TENANT, loop["cycle"]["id"], 5)).ok == 1

    async def test_a_motor_failure_counts_an_error_for_the_cycle(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        wired_app.motor_mock.select.side_effect = grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE, None, None, details="motor down"
        )

        resp = await _select(api, loop["key"])
        await _settled(wired_app)

        assert resp.status_code == 500
        health = await wired_app.svc._redis.select_health(
            TENANT, loop["cycle"]["id"], 5
        )
        assert health.error == 1
        assert health.by_reason == {"motor_unavailable": 1}
        assert (await wired_app.svc._redis.loop_selects(TENANT, loop["id"], 5))[
            "live"
        ] == 0

    async def test_a_cycle_motor_cant_find_is_qbrixs_error(self, wired_app, api):
        from proxysvc.core.error import ExperimentNotFoundError

        loop = await _loop(wired_app, launch=True)
        wired_app.motor_mock.select.side_effect = ExperimentNotFoundError()

        resp = await _select(api, loop["key"])
        await _settled(wired_app)

        assert resp.status_code == 500
        health = await wired_app.svc._redis.select_health(
            TENANT, loop["cycle"]["id"], 5
        )
        assert (health.error, health.not_found) == (1, 0)
        assert health.by_reason == {"config": 1}


class TestRefusals:
    @pytest.mark.parametrize(
        "context, names",
        [
            ({}, "context.unit is required"),
            ({"unit": ""}, "context.unit is required"),
            ({"unit": "   "}, "context.unit is required"),
            ({"unit": 42}, "context.unit is required"),
            ({"unit": "u" * 257}, "at most 256 characters"),
            ({"unit": "user-42", "properties": [1, 2]}, "must be an object"),
        ],
    )
    async def test_a_bad_context_names_the_problem(
        self, wired_app, api, context, names
    ):
        loop = await _loop(wired_app)

        resp = await _select(api, loop["key"], context)

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_CONTEXT"
        assert names in resp.json()["detail"]

    async def test_an_unknown_loop_is_not_found_and_not_counted(self, wired_app, api):
        resp = await _select(api, "nothing")
        await _settled(wired_app)

        assert resp.status_code == 404
        assert resp.json()["code"] == "LOOP_NOT_FOUND"
        assert await wired_app.fake_redis.keys("qbrix:tenant:*:health:*") == []

    async def test_a_decision_is_no_feedback_token(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 0)
        request_id = (await _select(api, loop["key"])).json()["request_id"]
        wired_app.feedback_spy.events.clear()

        resp = await api.post(
            "/api/v1/agent/feedback", json={"request_id": request_id, "reward": 1.0}
        )
        await _settled(wired_app)

        assert 400 <= resp.status_code < 500
        assert wired_app.feedback_spy.events == []


class TestRoute:
    async def test_a_new_key_moves_the_route(self, wired_app, api):
        loop = await _loop(wired_app)
        await wired_app.svc.rename_loop(
            TENANT, loop["key"], key="headline", actor=ACTOR
        )

        moved = await _select(api, "headline")
        old = await _select(api, loop["key"])

        assert moved.json()["reason"] == "draft"
        assert old.status_code == 404

    async def test_launch_makes_the_route_live(self, wired_app, api):
        loop = await _loop(wired_app)
        assert (await _select(api, loop["key"])).json()["reason"] == "draft"
        await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)
        _motor_chooses(wired_app, 0)

        assert (await _select(api, loop["key"])).json()["reason"] == "live"

    async def test_pause_and_resume_move_the_route(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        await wired_app.svc._loop_service.pause_loop(TENANT, loop["key"], actor=ACTOR)

        paused = await _select(api, loop["key"])
        await wired_app.svc.resume_loop(TENANT, loop["key"], actor=ACTOR)
        _motor_chooses(wired_app, 0)
        resumed = await _select(api, loop["key"])

        assert paused.json()["reason"] == "paused"
        assert paused.json()["request_id"] is None
        assert resumed.json()["reason"] == "live"
        assert resumed.json()["request_id"]

    async def test_undo_of_create_removes_the_route(self, wired_app, api):
        loop = await _loop(wired_app)
        (create,) = await wired_app.svc.list_changes(TENANT, "loop", loop["id"])

        await wired_app.svc.undo_change(TENANT, create["id"], actor=ACTOR)

        assert (await _select(api, loop["key"])).status_code == 404
        assert (await _select(api, loop["id"])).status_code == 404
