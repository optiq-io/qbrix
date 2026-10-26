"""a change runs once per connection, tool and arguments within the window: a
repeat gets the first result, a concurrent repeat waits for it, and a call
that fails leaves nothing behind."""

from __future__ import annotations

import asyncio

import pytest
from fakeredis.aioredis import FakeRedis

from proxysvc.transport.mcp.error import Refusal
from proxysvc.transport.mcp.repeat import RepeatGuard
from proxysvc.transport.mcp.repeat import repeat_key

pytestmark = pytest.mark.unit


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


class _Call:
    def __init__(self, result=None, fail: Exception | None = None, delay=0.0):
        self.calls = 0
        self._result = result or {"loop": "checkout-headline"}
        self._fail = fail
        self._delay = delay

    async def __call__(self):
        self.calls += 1
        await asyncio.sleep(self._delay)
        if self._fail is not None:
            raise self._fail
        return {**self._result, "n": self.calls}


def test_the_key_ignores_argument_order():
    assert repeat_key("c", "loop_create", {"a": 1, "b": 2}) == repeat_key(
        "c", "loop_create", {"b": 2, "a": 1}
    )


@pytest.mark.parametrize(
    "other",
    [
        ("other-connection", "loop_create", {"a": 1}),
        ("c", "metric_create", {"a": 1}),
        ("c", "loop_create", {"a": 2}),
    ],
)
def test_the_key_tells_connection_tool_and_arguments_apart(other):
    assert repeat_key("c", "loop_create", {"a": 1}) != repeat_key(*other)


async def test_a_repeat_returns_the_first_result(redis):
    guard = RepeatGuard(redis)
    call = _Call()

    first = await guard.once("k", call)
    second = await guard.once("k", call)

    assert first == second == {"loop": "checkout-headline", "n": 1}
    assert call.calls == 1


async def test_a_repeat_lasts_only_the_window(redis):
    guard = RepeatGuard(redis, window_sec=300)
    await guard.once("k", _Call())

    assert 0 < await redis.ttl("k") <= 300


async def test_a_concurrent_repeat_waits_for_the_first(redis):
    guard = RepeatGuard(redis)
    call = _Call(delay=0.3)

    first, second = await asyncio.gather(guard.once("k", call), guard.once("k", call))

    assert first == second
    assert call.calls == 1


async def test_a_repeat_that_waits_too_long_is_told_to_try_again(redis):
    guard = RepeatGuard(redis, wait_sec=0.2)
    slow = asyncio.create_task(guard.once("k", _Call(delay=1.0)))
    await asyncio.sleep(0.05)

    with pytest.raises(Refusal, match="still running"):
        await guard.once("k", _Call())
    slow.cancel()


async def test_a_failed_call_leaves_nothing_behind(redis):
    guard = RepeatGuard(redis)

    with pytest.raises(Refusal):
        await guard.once("k", _Call(fail=Refusal("no")))

    assert await redis.get("k") is None
    assert (await guard.once("k", _Call()))["n"] == 1
