"""the selection_events row, its columns and the schema that holds them."""

from __future__ import annotations

import json
import re

import pytest

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.migrations import SELECTION_EVENTS_ALTERS
from qbrixstore.clickhouse.migrations import SELECTION_EVENTS_TABLE

from lib.store.tests.test_event import a_selection

pytestmark = pytest.mark.unit


def _table_columns() -> list[str]:
    body = SELECTION_EVENTS_TABLE.split("(", 1)[1].split("\n)\n", 1)[0]
    return [line.split()[0] for line in body.strip().splitlines()]


def test_the_row_matches_the_columns():
    row = ClickHouseClient._selection_to_row(a_selection())

    assert len(row) == len(ClickHouseClient.SELECTION_COLUMNS)


def test_every_written_column_is_in_the_table():
    assert set(ClickHouseClient.SELECTION_COLUMNS) <= set(_table_columns())


def test_every_column_added_since_the_first_schema_has_an_alter():
    added = {
        re.search(r"ADD COLUMN IF NOT EXISTS (\w+)", alter).group(1)
        for alter in SELECTION_EVENTS_ALTERS
    }
    first_schema = {
        "tenant_id",
        "experiment_id",
        "request_id",
        "arm_id",
        "arm_name",
        "arm_index",
        "is_default",
        "context_id",
        "context_vector",
        "context_metadata",
        "timestamp_ms",
        "policy",
        "event_date",
    }

    assert set(_table_columns()) - first_schema == added


def test_a_decision_writes_its_loop_and_metric_terms():
    event = a_selection(
        loop_id="loop-1",
        cycle_id="cyc-1",
        decision_id="dec-1",
        reason="live",
        unit="user-42",
        properties={"plan": "pro"},
        metric_id="m-1",
        metric_version="1.0",
        metric_type="conversion",
        window_ms=86_400_000,
    )

    row = dict(
        zip(
            ClickHouseClient.SELECTION_COLUMNS,
            ClickHouseClient._selection_to_row(event),
        )
    )

    assert row["decision_id"] == "dec-1"
    assert row["unit"] == "user-42"
    assert json.loads(row["properties"]) == {"plan": "pro"}
    assert row["metric_version"] == "1.0"
    assert row["window_ms"] == 86_400_000
