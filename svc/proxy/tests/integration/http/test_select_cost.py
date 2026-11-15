"""what select on a live loop costs in process, its health counters included.

motor is a mock, so the figures are the proxy's own share of a decision:
the route read, the token, and the counters dispatched off the request path,
which share the event loop with the calls being timed. run with ``-s`` to
read p50 and p99 next to another branch's.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from unittest.mock import AsyncMock

import pytest

from proxysvc.core.actor import Actor

pytestmark = [pytest.mark.integration, pytest.mark.performance]

TENANT = "dev-tenant"
ACTOR = Actor.member("user-ada")
WARMUP = 500
CALLS = 5_000
BUDGET_P99_US = 20_000


async def test_select_on_a_live_loop_costs_well_under_a_millisecond(wired_app):
    svc = wired_app.svc
    await svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        actor=ACTOR,
    )
    draft = (
        await svc.create_loop(
            TENANT,
            name="Checkout headline",
            metric="purchase",
            options=[{"name": "Control"}, {"name": "Urgency"}],
            actor=ACTOR,
        )
    ).value
    loop = (await svc.launch_loop(TENANT, draft["key"], actor=ACTOR)).value
    wired_app.motor_mock.select = AsyncMock(
        return_value={"arm": {"index": 1}, "policy": "BetaTSPolicy"}
    )

    for n in range(WARMUP):
        await svc.select_loop(TENANT, loop["key"], f"warm-{n}")
    await wired_app.events.drain()

    timings = []
    for n in range(CALLS):
        started = time.perf_counter_ns()
        await svc.select_loop(TENANT, loop["key"], f"unit-{n}")
        timings.append(time.perf_counter_ns() - started)
        await asyncio.sleep(0)
    await wired_app.events.drain()

    cuts = statistics.quantiles(timings, n=100)
    p50_us, p99_us = cuts[49] / 1000, cuts[98] / 1000
    print(f"\nselect p50 {p50_us:.1f}us p99 {p99_us:.1f}us over {CALLS} calls")
    assert p99_us < BUDGET_P99_US
