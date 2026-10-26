"""grpc integration tests for select(loop, context) and outcome(request_id, value).

the grpc answer is the http answer: the same option with its config, the
same reason, a request_id only for a live loop, the same recorded outcome,
and the same refusals.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2
from google.protobuf.json_format import MessageToDict

from qbrixproto import loop_pb2

from proxysvc.core.actor import Actor
from proxysvc.mod.loop.token import DecisionToken
from proxysvc.transport.grpc.exception.base import InvalidDecisionContextException
from proxysvc.transport.grpc.exception.base import InvalidOutcomeException
from proxysvc.transport.grpc.exception.base import LoopNotFoundException
from proxysvc.transport.grpc.exception.base import TokenInvalidException
from proxysvc.transport.grpc.loop import LoopGRPCServicer

TENANT = "tenant-a"
ACTOR = Actor.member("user-x")


@pytest.fixture
async def loop(wired_grpc) -> dict:
    svc = wired_grpc.svc
    await svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        actor=ACTOR,
    )
    return (
        await svc.create_loop(
            TENANT,
            name="Checkout headline",
            metric="purchase",
            options=[
                {"name": "Control", "config": {"text": "Buy now", "rank": 2}},
                {"name": "Urgency", "config": {"text": "Only today"}},
            ],
            actor=ACTOR,
        )
    ).value


def _request(loop: str, unit: str = "user-42", **properties) -> loop_pb2.SelectRequest:
    struct = struct_pb2.Struct()
    struct.update(properties)
    return loop_pb2.SelectRequest(
        loop=loop,
        context=loop_pb2.Context(unit=unit, properties=struct),
    )


def _as_answer(response: loop_pb2.SelectResponse) -> dict:
    return {
        "option": {
            "key": response.option.key,
            "name": response.option.name,
            "config": MessageToDict(response.option.config),
        },
        "request_id": response.request_id or None,
        "reason": response.reason,
    }


async def test_a_draft_answers_as_http_does(wired_grpc, loop):
    servicer = LoopGRPCServicer(wired_grpc.svc)

    response = await servicer.Select(_request(loop["key"]), MagicMock())
    expected = await wired_grpc.svc.select_loop(TENANT, loop["key"], "user-42")

    assert _as_answer(response) == {
        **expected,
        "option": {
            **expected["option"],
            "config": {"text": "Buy now", "rank": 2.0},
        },
    }
    assert response.reason == "draft"
    assert response.request_id == ""


async def test_a_live_loop_returns_a_decision(wired_grpc, loop):
    await wired_grpc.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)
    wired_grpc.motor_mock.select.return_value = {
        "arm": {"id": "x", "name": "x", "index": 1},
        "policy": "BetaTSPolicy",
    }
    servicer = LoopGRPCServicer(wired_grpc.svc)

    response = await servicer.Select(
        _request(loop["key"], device="mobile", seats=3), MagicMock()
    )
    await wired_grpc.events.drain()

    assert response.reason == "live"
    assert response.option.key == "urgency"
    decision = DecisionToken.decode(
        wired_grpc.svc._settings.token_secret_bytes, response.request_id, TENANT
    )
    assert decision.option_index == 1
    (event,) = wired_grpc.selection_spy.events
    assert event.properties == {"device": "mobile", "seats": 3}


async def test_an_empty_unit_is_an_invalid_argument(wired_grpc, loop):
    servicer = LoopGRPCServicer(wired_grpc.svc)

    with pytest.raises(Exception) as raised:
        await servicer.Select(_request(loop["key"], unit=""), MagicMock())

    assert "context.unit is required" in str(raised.value)
    assert _grpc_error(raised.value) is InvalidDecisionContextException


async def test_an_unknown_loop_is_not_found(wired_grpc, loop):
    servicer = LoopGRPCServicer(wired_grpc.svc)

    with pytest.raises(Exception) as raised:
        await servicer.Select(_request("nothing"), MagicMock())

    assert _grpc_error(raised.value) is LoopNotFoundException


async def _decision(wired_grpc, loop) -> str:
    await wired_grpc.svc.launch_loop(TENANT, loop["key"], actor=ACTOR)
    wired_grpc.motor_mock.select.return_value = {
        "arm": {"id": "x", "name": "x", "index": 1},
        "policy": "BetaTSPolicy",
    }
    answer = await wired_grpc.svc.select_loop(TENANT, loop["key"], "user-42")
    await wired_grpc.events.drain()
    return answer["request_id"]


async def test_an_outcome_is_recorded_as_http_records_it(wired_grpc, loop):
    request_id = await _decision(wired_grpc, loop)
    opened_ms = DecisionToken.decode(
        wired_grpc.svc._settings.token_secret_bytes, request_id, TENANT
    ).timestamp_ms
    at = timestamp_pb2.Timestamp()
    at.FromMilliseconds(opened_ms + 1_000)
    servicer = LoopGRPCServicer(wired_grpc.svc)

    response = await servicer.Outcome(
        loop_pb2.OutcomeRequest(request_id=request_id, value=1, id="order-7", at=at),
        MagicMock(),
    )
    await wired_grpc.events.drain()

    (event,) = wired_grpc.metric_spy.events
    assert (event.event_id, event.at_ms, event.value) == (
        "order-7",
        opened_ms + 1_000,
        1.0,
    )
    assert event.decisions[0]["option_index"] == 1
    assert response.id == "order-7"
    assert response.at.ToMilliseconds() == opened_ms + 1_000


async def test_an_outcome_without_id_or_time_gets_both(wired_grpc, loop):
    request_id = await _decision(wired_grpc, loop)
    servicer = LoopGRPCServicer(wired_grpc.svc)

    response = await servicer.Outcome(
        loop_pb2.OutcomeRequest(request_id=request_id, value=0), MagicMock()
    )
    await wired_grpc.events.drain()

    (event,) = wired_grpc.metric_spy.events
    assert response.id == event.event_id != ""
    assert response.at.ToMilliseconds() == event.at_ms == event.received_ms


async def test_an_invalid_value_is_an_invalid_argument(wired_grpc, loop):
    request_id = await _decision(wired_grpc, loop)
    servicer = LoopGRPCServicer(wired_grpc.svc)

    with pytest.raises(Exception) as raised:
        await servicer.Outcome(
            loop_pb2.OutcomeRequest(request_id=request_id, value=2), MagicMock()
        )
    await wired_grpc.events.drain()

    assert "a conversion is 0 or 1" in str(raised.value)
    assert _grpc_error(raised.value) is InvalidOutcomeException
    assert wired_grpc.metric_spy.events == []


async def test_an_outcome_without_a_value_is_refused(wired_grpc, loop):
    request_id = await _decision(wired_grpc, loop)
    servicer = LoopGRPCServicer(wired_grpc.svc)

    with pytest.raises(Exception) as raised:
        await servicer.Outcome(
            loop_pb2.OutcomeRequest(request_id=request_id), MagicMock()
        )
    await wired_grpc.events.drain()

    assert "value must be a number" in str(raised.value)
    assert wired_grpc.metric_spy.events == []


async def test_a_forged_request_id_is_an_invalid_token(wired_grpc, loop):
    request_id = await _decision(wired_grpc, loop)
    forged = request_id[:-1] + ("A" if request_id[-1] != "A" else "B")
    servicer = LoopGRPCServicer(wired_grpc.svc)

    with pytest.raises(Exception) as raised:
        await servicer.Outcome(
            loop_pb2.OutcomeRequest(request_id=forged, value=1), MagicMock()
        )
    await wired_grpc.events.drain()

    assert _grpc_error(raised.value) is TokenInvalidException
    assert wired_grpc.metric_spy.events == []


def _grpc_error(error: Exception):
    """the grpc exception the interceptor answers a domain error with."""
    from proxysvc.transport.grpc.exception.interceptor import _DOMAIN_TO_GRPC

    return _DOMAIN_TO_GRPC[type(error)]
