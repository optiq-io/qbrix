from __future__ import annotations

import time
from datetime import datetime
from datetime import timezone

import pytest

from proxysvc.mod.loop.delivery import Delivery

pytestmark = [pytest.mark.unit, pytest.mark.performance]

RUNS = 20_000
BUDGET_US = 50


def test_five_conditions_with_rollout_and_hours_cost_microseconds():
    delivery = Delivery.model_validate(
        {
            "audience": [
                {"property": "device", "operator": "is", "value": "mobile"},
                {"property": "country", "operator": "in", "value": ["NL", "BE", "DE"]},
                {"property": "plan", "operator": "is_not", "value": "free"},
                {"property": "orders", "operator": "gte", "value": 3},
                {"property": "referrer", "operator": "not_contains", "value": "ads"},
            ],
            "rollout": 50,
            "schedule": {
                "hours": {"start": "06:00", "end": "23:00"},
                "timezone": "Europe/Amsterdam",
            },
        }
    )
    properties = {
        "device": "mobile",
        "country": "NL",
        "plan": "pro",
        "orders": 7,
        "referrer": "newsletter",
    }
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    started = time.perf_counter_ns()
    for n in range(RUNS):
        delivery.decide("loop-1", f"u-{n}", properties, now)
    per_call_us = (time.perf_counter_ns() - started) / RUNS / 1000
    assert per_call_us < BUDGET_US
