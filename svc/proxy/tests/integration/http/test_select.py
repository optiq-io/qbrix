"""integration tests for select(loop, context), a qbrix next surface.

invariants verified:
  a draft or paused loop answers its fallback with its reason, no request_id,
  no motor call and nothing in the ledger. a live loop answers the option
  motor chose from the current cycle with a request_id that decodes to a
  fresh decision, and records the decision with its unit, properties and
  the metric terms it will be sealed by. a committed loop answers its
  committed option for every request, as a decision on the ledger, without
  asking motor; paused, it answers the fallback, and resumed, its committed
  option again; reopened, it asks motor again. a retired loop answers its
  fallback as reason retired, without a decision, and still counts the call;
  its cycle record stays for the decisions still sealing. a missing unit is
  refused; an
  unknown loop is not found and counted nowhere. every answer is counted by
  its reason, and a live loop's failures by outcome per cycle. loop writes
  keep the route select reads current. a draft's first call is a milestone
  once, naming the key it came from; a failed publish is tried again by the
  next call, and a live loop's calls are never one. a live or committed
  loop decides only for requests inside its delivery (schedule, audience,
  rollout); outside it, it answers the fallback as outside_delivery, without
  a decision, and counts the call. a route written before loops had a
  delivery decides for everyone.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

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
    loop = (
        await wired_app.svc.create_loop(
            TENANT,
            **{
                "name": "Checkout headline",
                "metric": "purchase",
                "options": OPTIONS,
                "actor": ACTOR,
                **overrides,
            },
        )
    ).value
    if launch:
        loop = (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)).value
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


class TestFirstCall:
    async def test_a_drafts_first_call_is_a_milestone_once(self, wired_app, api):
        loop = await _loop(wired_app)

        await _select(api, loop["key"])
        await _select(api, loop["key"], {"unit": "user-43"})
        await _settled(wired_app)

        found = wired_app.milestone_spy.events
        assert [event.kind for event in found] == ["loop.first_call"]
        assert found[0].event_id == f"first_call:{loop['id']}"
        assert found[0].loop_id == loop["id"]
        assert found[0].cycle_id == ""

    async def test_it_names_no_key_when_none_called(self, wired_app, api):
        loop = await _loop(wired_app)

        await _select(api, loop["key"])
        await _settled(wired_app)

        assert wired_app.milestone_spy.events[0].payload == {"source": None}

    async def test_it_names_the_key_that_called(self, wired_app, api):
        loop = await _loop(wired_app)

        await wired_app.svc.select_loop(TENANT, loop["key"], "u", source="web-prod")
        await _settled(wired_app)

        assert wired_app.milestone_spy.events[0].payload == {"source": "web-prod"}

    async def test_a_failed_publish_is_tried_again_by_the_next_call(
        self, wired_app, api
    ):
        loop = await _loop(wired_app)
        spy = wired_app.milestone_spy
        recorded = spy.publish

        async def refuse(event):
            raise ConnectionError("redis went away")

        spy.publish = refuse
        await _select(api, loop["key"])
        await _settled(wired_app)
        spy.publish = recorded
        await _select(api, loop["key"])
        await _settled(wired_app)

        assert [event.kind for event in spy.events] == ["loop.first_call"]

    async def test_a_redis_failure_never_touches_the_answer(
        self, wired_app, api, monkeypatch
    ):
        loop = await _loop(wired_app)

        async def fail(*_args):
            raise ConnectionError("redis went away")

        monkeypatch.setattr(wired_app.svc._redis, "first_call_once", fail)
        resp = await _select(api, loop["key"])
        await _settled(wired_app)

        assert resp.status_code == 200
        assert wired_app.milestone_spy.events == []

    async def test_a_live_loop_never_records_one(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 0)

        await _select(api, loop["key"])
        await _settled(wired_app)

        assert wired_app.milestone_spy.events == []


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
        assert counts == {
            "live": 0,
            "committed": 0,
            "outside_delivery": 0,
            "draft": 2,
            "paused": 0,
            "retired": 0,
        }


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


async def _committed(wired_app, option: str = "urgency") -> dict:
    loop = await _loop(wired_app, launch=True)
    return (
        await wired_app.svc.commit_loop(TENANT, loop["key"], option=option, actor=ACTOR)
    ).value


class TestCommitted:
    async def test_answers_the_committed_option_without_motor(self, wired_app, api):
        loop = await _committed(wired_app)
        _motor_chooses(wired_app, 0)

        resp = await _select(api, loop["key"])

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reason"] == "committed"
        assert body["option"]["key"] == "urgency"
        assert body["request_id"]
        wired_app.motor_mock.select.assert_not_called()

    async def test_every_request_gets_the_same_option(self, wired_app, api):
        loop = await _committed(wired_app, "control")

        answers = [
            (await _select(api, loop["key"], {"unit": f"user-{n}"})).json()
            for n in range(20)
        ]

        assert {answer["option"]["key"] for answer in answers} == {"control"}
        assert len({answer["request_id"] for answer in answers}) == 20

    async def test_the_request_id_decodes_to_the_committed_option(self, wired_app, api):
        loop = await _committed(wired_app)

        resp = await _select(api, loop["key"])
        decision = DecisionToken.decode(
            wired_app.svc._settings.token_secret_bytes,
            resp.json()["request_id"],
            TENANT,
        )

        assert decision.cycle_id == loop["cycle"]["id"]
        assert decision.option_index == 1
        assert decision.metric_version == "1.0"

    async def test_records_the_decision_on_the_ledger(self, wired_app, api):
        loop = await _committed(wired_app)
        wired_app.selection_spy.events.clear()

        resp = await _select(api, loop["key"])
        await _settled(wired_app)

        (event,) = wired_app.selection_spy.events
        assert event.reason == "committed"
        assert event.policy == "committed"
        assert event.request_id == resp.json()["request_id"]
        assert event.cycle_id == loop["cycle"]["id"]
        assert (event.arm_name, event.arm_index) == ("urgency", 1)
        assert event.metric_id == loop["metric"]["id"]
        assert event.window_ms == 2 * 24 * 60 * 60 * 1000

    async def test_is_counted_as_committed_and_by_outcome(self, wired_app, api):
        loop = await _committed(wired_app)

        await _select(api, loop["key"])
        await _settled(wired_app)

        redis = wired_app.svc._redis
        counts = await redis.loop_selects(TENANT, loop["id"], 5)
        assert (counts["committed"], counts["live"]) == (1, 0)
        assert (await redis.select_health(TENANT, loop["cycle"]["id"], 5)).ok == 1

    async def test_paused_it_answers_the_fallback_and_resumed_its_option(
        self, wired_app, api
    ):
        loop = await _committed(wired_app)
        await wired_app.svc.pause_loop(TENANT, loop["key"], actor=ACTOR)

        paused = (await _select(api, loop["key"])).json()
        await wired_app.svc.resume_loop(TENANT, loop["key"], actor=ACTOR)
        resumed = (await _select(api, loop["key"])).json()

        assert (paused["reason"], paused["request_id"]) == ("paused", None)
        assert paused["option"]["key"] == "control"
        assert (resumed["reason"], resumed["option"]["key"]) == (
            "committed",
            "urgency",
        )
        assert resumed["request_id"]
        wired_app.motor_mock.select.assert_not_called()

    async def test_reopening_asks_motor_again(self, wired_app, api):
        loop = await _committed(wired_app)
        await wired_app.svc.reopen_loop(TENANT, loop["key"], actor=ACTOR)
        _motor_chooses(wired_app, 0)

        resp = await _select(api, loop["key"])

        assert resp.json()["reason"] == "live"
        assert resp.json()["option"]["key"] == "control"
        wired_app.motor_mock.select.assert_called_once()


async def _retired(wired_app, committed: bool = False) -> dict:
    loop = await (_committed(wired_app) if committed else _loop(wired_app, launch=True))
    return (await wired_app.svc.retire_loop(TENANT, loop["key"], actor=ACTOR)).value


class TestRetired:
    @pytest.mark.parametrize("committed", [False, True])
    async def test_answers_the_fallback_without_a_decision(
        self, wired_app, api, committed
    ):
        loop = await _retired(wired_app, committed)
        wired_app.motor_mock.select.reset_mock()
        wired_app.selection_spy.events.clear()

        resp = await _select(api, loop["key"])
        await _settled(wired_app)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reason"] == "retired"
        assert body["request_id"] is None
        assert body["option"]["key"] == "control"
        wired_app.motor_mock.select.assert_not_called()
        assert wired_app.selection_spy.events == []

    async def test_is_counted_as_retired(self, wired_app, api):
        loop = await _retired(wired_app)

        await _select(api, loop["key"])
        await _settled(wired_app)

        counts = await wired_app.svc._redis.loop_selects(TENANT, loop["id"], 5)
        assert (counts["retired"], counts["live"]) == (1, 0)

    async def test_its_id_still_answers(self, wired_app, api):
        loop = await _retired(wired_app)

        resp = await _select(api, loop["id"])

        assert resp.json()["reason"] == "retired"

    async def test_keeps_the_cycle_record_its_open_decisions_seal_by(
        self, wired_app, api
    ):
        loop = await _loop(wired_app, launch=True)
        redis = wired_app.svc._redis
        record = await redis.get_experiment(TENANT, loop["cycle"]["id"])

        await wired_app.svc.retire_loop(TENANT, loop["key"], actor=ACTOR)

        assert record is not None
        assert await redis.get_experiment(TENANT, loop["cycle"]["id"]) == record


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


MOBILE_NL = [
    {"property": "device", "operator": "is", "value": "mobile"},
    {"property": "country", "operator": "in", "value": ["NL", "BE"]},
]
MOBILE_IN_NL = {"unit": "user-42", "properties": {"device": "mobile", "country": "NL"}}
DESKTOP_IN_NL = {
    "unit": "user-42",
    "properties": {"device": "desktop", "country": "NL"},
}


async def _deliver(wired_app, loop: dict, **delivery) -> dict:
    return (
        await wired_app.svc.update_delivery(
            TENANT, loop["key"], actor=ACTOR, **delivery
        )
    ).value


def _at(monkeypatch, moment: datetime) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr("proxysvc.mod.loop.select.datetime", Clock)


class TestDelivery:
    async def test_a_live_loop_decides_inside_its_audience_only(self, wired_app, api):
        loop = await _loop(wired_app, launch=True, fallback="urgency")
        await _deliver(wired_app, loop, audience=MOBILE_NL)
        _motor_chooses(wired_app, 0)

        inside = (await _select(api, loop["key"], MOBILE_IN_NL)).json()
        outside = (await _select(api, loop["key"], DESKTOP_IN_NL)).json()
        missing = (await _select(api, loop["key"], {"unit": "user-42"})).json()

        assert (inside["reason"], inside["option"]["key"]) == ("live", "control")
        assert inside["request_id"]
        for answer in (outside, missing):
            assert answer["reason"] == "outside_delivery"
            assert answer["option"]["key"] == "urgency"
            assert answer["request_id"] is None
        assert wired_app.motor_mock.select.call_count == 1

    async def test_a_committed_loop_serves_its_option_only_inside(self, wired_app, api):
        loop = await _committed(wired_app, "urgency")
        await _deliver(wired_app, loop, audience=MOBILE_NL, fallback="control")

        inside = (await _select(api, loop["key"], MOBILE_IN_NL)).json()
        outside = (await _select(api, loop["key"], DESKTOP_IN_NL)).json()

        assert (inside["reason"], inside["option"]["key"]) == ("committed", "urgency")
        assert (outside["reason"], outside["option"]["key"]) == (
            "outside_delivery",
            "control",
        )
        assert outside["request_id"] is None

    async def test_outside_is_not_a_decision_and_is_counted(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        await _deliver(wired_app, loop, rollout=0)
        wired_app.motor_mock.select.reset_mock()

        await _select(api, loop["key"])
        await _select(api, loop["key"], {"unit": "user-7"})
        await _settled(wired_app)

        wired_app.motor_mock.select.assert_not_called()
        assert wired_app.selection_spy.events == []
        counts = await wired_app.svc._redis.loop_selects(TENANT, loop["id"], 5)
        assert counts["outside_delivery"] == 2
        assert counts["live"] == 0

    async def test_rollout_holds_a_units_answer(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        await _deliver(wired_app, loop, rollout=50)
        _motor_chooses(wired_app, 0)

        first = [
            (await _select(api, loop["key"], {"unit": f"u-{n}"})).json()["reason"]
            for n in range(40)
        ]
        again = [
            (await _select(api, loop["key"], {"unit": f"u-{n}"})).json()["reason"]
            for n in range(40)
        ]

        assert first == again
        assert {"live", "outside_delivery"} == set(first)

    async def test_outside_its_hours_and_before_its_start(
        self, wired_app, api, monkeypatch
    ):
        loop = await _loop(wired_app, launch=True)
        await _deliver(
            wired_app,
            loop,
            schedule={
                "hours": {"start": "09:00", "end": "18:00"},
                "starts_on": "2026-12-01",
                "timezone": "Europe/Amsterdam",
            },
        )
        _motor_chooses(wired_app, 0)

        _at(monkeypatch, datetime(2026, 11, 30, 10, 0, tzinfo=timezone.utc))
        before_start = (await _select(api, loop["key"])).json()["reason"]
        _at(monkeypatch, datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc))
        in_hours = (await _select(api, loop["key"])).json()["reason"]
        _at(monkeypatch, datetime(2026, 12, 1, 17, 0, tzinfo=timezone.utc))
        after_hours = (await _select(api, loop["key"])).json()["reason"]

        assert (before_start, in_hours, after_hours) == (
            "outside_delivery",
            "live",
            "outside_delivery",
        )

    async def test_a_draft_answers_its_state_first(self, wired_app, api):
        draft = await _loop(wired_app)
        await _deliver(wired_app, draft, rollout=0)

        assert (await _select(api, draft["key"])).json()["reason"] == "draft"

    async def test_a_route_written_before_delivery_decides_for_everyone(
        self, wired_app, api
    ):
        loop = await _loop(wired_app, launch=True)
        routes = wired_app.svc._loop_select_service._routes
        route = await routes.get(TENANT, loop["id"])
        raw = route.model_dump_json(exclude={"delivery"})
        for kind, ref in (("id", route.id), ("key", route.key)):
            await wired_app.fake_redis.set(
                f"qbrix:tenant:{TENANT}:loop:{kind}:{ref}", raw
            )
        routes._forget(TENANT, route.id, route.key)
        _motor_chooses(wired_app, 0)

        assert (await _select(api, loop["key"])).json()["reason"] == "live"

    async def test_a_delivery_change_moves_the_route(self, wired_app, api):
        loop = await _loop(wired_app, launch=True)
        _motor_chooses(wired_app, 0)
        assert (await _select(api, loop["key"])).json()["reason"] == "live"

        await _deliver(wired_app, loop, rollout=0)

        assert (await _select(api, loop["key"])).json()["reason"] == "outside_delivery"
