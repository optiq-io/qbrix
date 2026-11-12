from __future__ import annotations

import time

import pytest

from qbrixcore.context_schema import ContextSchema

pytestmark = [pytest.mark.unit, pytest.mark.performance]

RUNS = 20_000
BUDGET_US = 50


def test_ten_properties_encode_in_microseconds():
    schema = ContextSchema.model_validate(
        [
            {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
            {"name": "plan", "type": "categorical", "values": ["free", "pro", "team"]},
            {"name": "country", "type": "categorical", "values": ["NL", "BE", "DE"]},
            {"name": "browser", "type": "categorical", "values": ["chrome", "safari"]},
            {"name": "seats", "type": "numeric", "min": 1, "max": 500},
            {"name": "orders", "type": "numeric", "min": 0, "max": 100},
            {"name": "age_days", "type": "numeric", "min": 0, "max": 3650},
            {"name": "returning", "type": "boolean"},
            {"name": "trial", "type": "boolean"},
            {"name": "admin", "type": "boolean"},
        ]
    )
    properties = {
        "device": "mobile",
        "plan": "pro",
        "country": "NL",
        "browser": 3.5,
        "seats": 12,
        "orders": 7,
        "age_days": 400,
        "returning": True,
        "trial": "no",
        "admin": False,
        "referrer": "newsletter",
    }
    started = time.perf_counter_ns()
    for _ in range(RUNS):
        schema.encode_lenient(properties)
    per_call_us = (time.perf_counter_ns() - started) / RUNS / 1000
    assert per_call_us < BUDGET_US
