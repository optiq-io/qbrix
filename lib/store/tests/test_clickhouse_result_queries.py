"""the results queries against a real clickhouse, in a scratch database.

skipped when no clickhouse answers on localhost (as in ci); run locally with
`make infra` up.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.ledger import CycleSpan
from qbrixstore.clickhouse.ledger import DecisionBucket
from qbrixstore.clickhouse.ledger import DecisionCount
from qbrixstore.clickhouse.ledger import SealedStats
from qbrixstore.clickhouse.migrations import create_tables
from qbrixstore.config import ClickHouseSettings

from lib.store.tests.test_clickhouse_ledger import a_sealed
from lib.store.tests.test_event import a_selection

pytestmark = pytest.mark.integration

# recent, or the tables' ttl drops the rows
OPENED = (int(time.time()) - 3_600) * 1000 // 60_000 * 60_000
MINUTE = 60_000


@pytest.fixture
def ledger():
    database = f"qbrix_test_{uuid.uuid4().hex[:8]}"
    client = ClickHouseClient(ClickHouseSettings(database=database))
    try:
        client.connect()
    except Exception:
        pytest.skip("no clickhouse on localhost")
    create_tables(client.client)
    yield client
    client.client.command(f"DROP DATABASE IF EXISTS {database}")
    client.close()


def decide(
    ledger,
    decision_id: str,
    opened_ms: int,
    option_index: int = 0,
    cycle_id: str = "cyc-1",
    ledger_ms: int | None = None,
):
    event = a_selection(
        tenant_id="t1",
        experiment_id=cycle_id,
        loop_id="loop-1",
        cycle_id=cycle_id,
        decision_id=decision_id,
        arm_index=option_index,
        timestamp_ms=opened_ms,
    )
    ledger.insert_selection_events([event], ledger_ms=[ledger_ms or opened_ms])


def seal(ledger, decision_id: str, opened_ms: int, value: float | None, **kw):
    ledger.insert_sealed_decisions(
        [
            a_sealed(
                decision_id=decision_id,
                opened_ms=opened_ms,
                value=value,
                option_index=kw.pop("option_index", 0),
                **kw,
            )
        ]
    )


def test_a_decision_written_twice_counts_once_in_its_step(ledger):
    decide(ledger, "a", OPENED + 1_000)
    decide(ledger, "a", OPENED + 1_000)
    decide(ledger, "b", OPENED + 2_000, option_index=1)
    decide(ledger, "c", OPENED + MINUTE + 1_000, option_index=1)
    decide(ledger, "other-cycle", OPENED, cycle_id="cyc-2")

    series = ledger.decision_series("t1", "cyc-1", OPENED, OPENED + 2 * MINUTE, MINUTE)

    assert series == [
        DecisionBucket(OPENED, 0, 1),
        DecisionBucket(OPENED, 1, 1),
        DecisionBucket(OPENED + MINUTE, 1, 1),
    ]


def test_the_series_reads_only_its_range(ledger):
    decide(ledger, "before", OPENED - 1)
    decide(ledger, "inside", OPENED)
    decide(ledger, "after", OPENED + MINUTE)

    series = ledger.decision_series("t1", "cyc-1", OPENED, OPENED + MINUTE, MINUTE)

    assert series == [DecisionBucket(OPENED, 0, 1)]


def test_waiting_and_sealed_add_up_to_what_reached_the_ledger_in_time(ledger):
    decide(ledger, "sealed", OPENED)
    decide(ledger, "sealed", OPENED, ledger_ms=OPENED + 500)
    decide(ledger, "open", OPENED + 1_000)
    decide(ledger, "not-yet", OPENED + 2_000, ledger_ms=OPENED + 9_000)
    seal(ledger, "sealed", OPENED, 1.0)
    seal(ledger, "sealed", OPENED, 1.0)

    counts = ledger.decision_counts(
        "t1", [CycleSpan("cyc-1", OPENED, OPENED + MINUTE)], OPENED + 5_000
    )

    assert counts == [DecisionCount("cyc-1", 0, 3, sealed=1, waiting=1)]


def test_without_complete_up_to_every_decision_in_the_ledger_counts(ledger):
    decide(ledger, "open", OPENED, ledger_ms=OPENED + 9_000)

    counts = ledger.decision_counts(
        "t1", [CycleSpan("cyc-1", OPENED, OPENED + MINUTE)], None
    )

    assert counts == [DecisionCount("cyc-1", 0, 1, sealed=0, waiting=1)]


def test_counts_batch_cycles_each_in_its_own_span(ledger):
    decide(ledger, "a", OPENED, cycle_id="cyc-1")
    decide(ledger, "a-late", OPENED + MINUTE, cycle_id="cyc-1")
    decide(ledger, "b", OPENED + MINUTE, cycle_id="cyc-2", option_index=1)
    decide(ledger, "c", OPENED, cycle_id="cyc-3")

    counts = ledger.decision_counts(
        "t1",
        [
            CycleSpan("cyc-1", OPENED, OPENED + MINUTE),
            CycleSpan("cyc-2", OPENED, OPENED + 2 * MINUTE),
        ],
        None,
    )

    assert sorted(counts, key=lambda c: c.cycle_id) == [
        DecisionCount("cyc-1", 0, 1, sealed=0, waiting=1),
        DecisionCount("cyc-2", 1, 1, sealed=0, waiting=1),
    ]


def test_sealed_stats_count_each_decision_once_and_skip_no_value(ledger):
    seal(ledger, "a", OPENED, 1.0)
    seal(ledger, "a", OPENED, 1.0)
    seal(ledger, "b", OPENED, 3.0)
    seal(ledger, "c", OPENED, 2.0, option_index=1)
    seal(ledger, "nothing", OPENED, None)

    stats = ledger.sealed_stats("t1", [CycleSpan("cyc-1", OPENED, OPENED + MINUTE)])

    assert sorted(stats, key=lambda s: s.option_index) == [
        SealedStats("cyc-1", 0, 2, 4.0, 10.0),
        SealedStats("cyc-1", 1, 1, 2.0, 4.0),
    ]


def test_sealed_stats_read_decisions_by_when_they_were_made(ledger):
    seal(ledger, "before", OPENED - 1, 1.0)
    seal(ledger, "inside", OPENED, 1.0)
    seal(ledger, "after", OPENED + MINUTE, 1.0)
    seal(ledger, "other", OPENED, 1.0, cycle_id="cyc-2")

    stats = ledger.sealed_stats("t1", [CycleSpan("cyc-1", OPENED, OPENED + MINUTE)])

    assert stats == [SealedStats("cyc-1", 0, 1, 1.0, 1.0)]


def test_one_client_answers_queries_from_several_threads_at_once(ledger):
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(
            pool.map(
                lambda _: ledger.client.query("SELECT sleep(0.2)").result_rows,
                range(4),
            )
        )

    assert len(rows) == 4


def test_no_spans_read_nothing(ledger):
    assert ledger.decision_counts("t1", [], None) == []
    assert ledger.sealed_stats("t1", []) == []
