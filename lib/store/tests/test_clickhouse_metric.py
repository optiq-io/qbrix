"""the metric_events row, its columns and the schema that holds them."""

from __future__ import annotations

import pytest

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.migrations import METRIC_EVENTS_TABLE

from lib.store.tests.test_event import a_metric

pytestmark = pytest.mark.unit


def _table_columns() -> list[str]:
    body = METRIC_EVENTS_TABLE.split("(", 1)[1].split("\n)\n", 1)[0]
    return [line.split()[0] for line in body.strip().splitlines()]


def _row(event) -> dict:
    return dict(
        zip(ClickHouseClient.METRIC_COLUMNS, ClickHouseClient._metric_to_row(event))
    )


def test_the_row_matches_the_columns():
    row = ClickHouseClient._metric_to_row(a_metric())

    assert len(row) == len(ClickHouseClient.METRIC_COLUMNS)


def test_every_written_column_is_in_the_table():
    assert set(ClickHouseClient.METRIC_COLUMNS) <= set(_table_columns())


def test_the_decision_tuple_follows_the_table():
    declared = METRIC_EVENTS_TABLE.split("Array(Tuple(", 1)[1].split("))", 1)[0]

    names = tuple(part.split()[0] for part in declared.split(","))

    assert names == ClickHouseClient.DECISION_FIELDS


def test_each_decision_is_written_as_a_tuple_in_order():
    row = _row(a_metric())

    assert row["decisions"] == [("dec-1", "loop-1", "cyc-1", 2, 1_000)]
    assert row["at_ms"] == 2_000
    assert row["source"] == "outcome"


def test_the_ledger_is_read_by_workspace_then_event_time():
    assert "ORDER BY (tenant_id, at_ms, event_id)" in METRIC_EVENTS_TABLE
