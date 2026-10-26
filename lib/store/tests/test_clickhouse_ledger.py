"""the ledger's tables as the sealer reads and writes them: ledger time on
decisions and outcomes, and sealed_decisions."""

from __future__ import annotations

import re

import pytest

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.ledger import SealedDecision
from qbrixstore.clickhouse.migrations import LEDGER_INDEXES
from qbrixstore.clickhouse.migrations import METRIC_EVENTS_ALTERS
from qbrixstore.clickhouse.migrations import METRIC_EVENTS_TABLE
from qbrixstore.clickhouse.migrations import SEALED_DECISIONS_TABLE
from qbrixstore.clickhouse.migrations import SELECTION_EVENTS_TABLE

from lib.store.tests.test_event import a_metric
from lib.store.tests.test_event import a_selection

pytestmark = pytest.mark.unit


def _table_columns(ddl: str) -> list[str]:
    body = ddl.split("(", 1)[1].split("\n)\n", 1)[0]
    return [line.split()[0] for line in body.strip().splitlines()]


def a_sealed(**overrides) -> SealedDecision:
    fields = dict(
        tenant_id="t1",
        loop_id="loop-1",
        cycle_id="cyc-1",
        decision_id="dec-1",
        option_index=2,
        unit="user-1",
        metric_id="m-1",
        metric_version="1.0",
        metric_type="score",
        opened_ms=1_000,
        sealed_ms=61_000,
        sealed_by="window",
        value=None,
        outcomes=0,
    )
    fields.update(overrides)
    return SealedDecision(**fields)


class TestSealedDecisions:
    def test_every_written_column_is_in_the_table(self):
        columns = _table_columns(SEALED_DECISIONS_TABLE)

        assert ClickHouseClient.SEALED_COLUMNS == columns[: len(columns) - 1]

    def test_a_repeated_pass_replaces_its_rows_by_decision(self):
        assert "ENGINE = ReplacingMergeTree()" in SEALED_DECISIONS_TABLE
        assert "ORDER BY (tenant_id, cycle_id, decision_id)" in SEALED_DECISIONS_TABLE

    def test_a_decision_always_lands_in_the_same_partition(self):
        partition = re.search(r"PARTITION BY (.+)", SEALED_DECISIONS_TABLE).group(1)

        assert "opened_date" in partition and "sealed" not in partition

    def test_a_score_without_an_outcome_has_no_value(self):
        assert "value Nullable(Float64)" in SEALED_DECISIONS_TABLE


class TestLedgerTime:
    def test_decisions_and_outcomes_have_a_ledger_time(self):
        assert "ledger_ms" in _table_columns(SELECTION_EVENTS_TABLE)
        assert "ledger_ms" in _table_columns(METRIC_EVENTS_TABLE)
        assert "ledger_ms" in ClickHouseClient.SELECTION_COLUMNS
        assert "ledger_ms" in ClickHouseClient.METRIC_COLUMNS

    def test_an_existing_metric_table_gains_it(self):
        added = {
            re.search(r"ADD COLUMN IF NOT EXISTS (\w+)", alter).group(1)
            for alter in METRIC_EVENTS_ALTERS
        }

        assert added == {"ledger_ms"}

    def test_rows_carry_the_stamp_they_are_given(self):
        selection = dict(
            zip(
                ClickHouseClient.SELECTION_COLUMNS,
                ClickHouseClient._selection_to_row(a_selection(), 42),
            )
        )
        metric = dict(
            zip(
                ClickHouseClient.METRIC_COLUMNS,
                ClickHouseClient._metric_to_row(a_metric(), 43),
            )
        )

        assert selection["ledger_ms"] == 42
        assert metric["ledger_ms"] == 43

    def test_without_a_stamp_rows_fall_back_to_their_own_time(self):
        selection = a_selection()
        metric = a_metric()

        assert (
            ClickHouseClient._selection_to_row(selection)[-1] == selection.timestamp_ms
        )
        assert ClickHouseClient._metric_to_row(metric)[-1] == metric.received_ms

    def test_the_sealers_range_reads_are_indexed(self):
        assert any(
            "greatest(timestamp_ms + window_ms, ledger_ms)" in i for i in LEDGER_INDEXES
        )
        assert any("metric_events" in i and "ledger_ms" in i for i in LEDGER_INDEXES)
