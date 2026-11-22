"""the sealer's queries against a real clickhouse, in a scratch database.

skipped when no clickhouse answers on localhost (as in ci); run locally with
`make infra` up.
"""

from __future__ import annotations

import time
import uuid

import pytest

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.ledger import MetricVersion
from qbrixstore.clickhouse.ledger import OutcomeRef
from qbrixstore.clickhouse.migrations import create_tables
from qbrixstore.config import ClickHouseSettings

from lib.store.tests.test_clickhouse_ledger import a_sealed
from lib.store.tests.test_event import a_metric
from lib.store.tests.test_event import a_selection

pytestmark = pytest.mark.integration

# recent, or the tables' ttl drops the rows
OPENED = (int(time.time()) - 3_600) * 1000
WINDOW = 60_000


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


def decide(ledger, decision_id: str, opened_ms: int, ledger_ms: int | None = None):
    event = a_selection(
        tenant_id="t1",
        experiment_id="cyc-1",
        loop_id="loop-1",
        cycle_id="cyc-1",
        decision_id=decision_id,
        arm_index=1,
        unit="user-1",
        metric_id="m-1",
        metric_version="1.0",
        metric_type="conversion",
        window_ms=WINDOW,
        timestamp_ms=opened_ms,
    )
    ledger.insert_selection_events([event], ledger_ms=[ledger_ms or opened_ms])
    return event


def answer(ledger, decision_id: str, ledger_ms: int, event_id: str = "ev-1"):
    event = a_metric(
        tenant_id="t1",
        decisions=[
            {
                "decision_id": decision_id,
                "loop_id": "loop-1",
                "cycle_id": "cyc-1",
                "option_index": 1,
                "opened_ms": OPENED,
            }
        ],
        event_id=event_id,
        at_ms=ledger_ms,
        received_ms=ledger_ms,
        value=1.0,
    )
    ledger.insert_metric_events([event], ledger_ms=[ledger_ms])


def test_window_seals_are_read_by_close_once_each(ledger):
    decide(ledger, "a", OPENED)
    decide(ledger, "a", OPENED)
    decide(ledger, "b", OPENED + 10_000)
    decide(ledger, "late", OPENED, ledger_ms=OPENED + WINDOW + 5_000)

    closing = ledger.query_window_seals(OPENED + WINDOW, OPENED + WINDOW + 1)
    later = ledger.query_window_seals(OPENED + WINDOW + 1, OPENED + 2 * WINDOW)

    assert [d.decision_id for d in closing] == ["a"]
    assert closing[0].option_index == 1
    assert closing[0].closes_ms == OPENED + WINDOW
    assert sorted(d.decision_id for d in later) == ["b", "late"]


def test_arrived_outcomes_name_their_decision(ledger):
    answer(ledger, "a", OPENED + 1_000)
    answer(ledger, "a", OPENED + 1_000)

    refs = ledger.query_arrived_outcomes(OPENED, OPENED + 2_000)

    assert refs == [OutcomeRef("t1", "cyc-1", "a", OPENED)]
    assert ledger.query_arrived_outcomes(OPENED + 2_000, OPENED + 3_000) == []


def test_decisions_are_found_from_their_refs(ledger):
    decide(ledger, "a", OPENED)
    decide(ledger, "b", OPENED)

    found = ledger.query_decisions([OutcomeRef("t1", "cyc-1", "a", OPENED)])

    assert [d.decision_id for d in found] == ["a"]


def test_outcomes_count_redeliveries_once_and_resends_apart(ledger):
    decision = decide(ledger, "a", OPENED)
    answer(ledger, "a", OPENED + 1_000)
    answer(ledger, "a", OPENED + 1_000)
    answer(ledger, "a", OPENED + 2_000)
    answer(ledger, "a", OPENED + 9_000)
    [found] = ledger.query_window_seals(OPENED + WINDOW, OPENED + WINDOW + 1)

    outcomes = ledger.query_outcomes([found], OPENED + 5_000)

    assert sorted(o.ledger_ms for o in outcomes) == [OPENED + 1_000, OPENED + 2_000]
    assert decision.decision_id == outcomes[0].decision_id


def test_a_repeated_pass_records_each_decision_once(ledger):
    ledger.insert_sealed_decisions([a_sealed(), a_sealed(value=None)])
    ledger.insert_sealed_decisions([a_sealed()])

    rows = ledger.client.query(
        "SELECT count(), any(value) FROM sealed_decisions FINAL"
    ).result_rows

    assert rows == [(1, None)]


def test_the_first_decision_is_where_sealing_starts(ledger):
    assert ledger.first_decision_ms() is None

    decide(ledger, "b", OPENED + 5_000)
    decide(ledger, "a", OPENED)

    assert ledger.first_decision_ms() == OPENED


def arrive(
    ledger,
    wait_ms: int,
    event_id: str,
    *,
    decision_id: str | None = None,
    arrived_ms: int | None = None,
    version: str = "1.0",
    tenant_id: str = "t1",
):
    at_ms = OPENED + wait_ms
    received_ms = OPENED + (arrived_ms if arrived_ms is not None else wait_ms)
    event = a_metric(
        tenant_id=tenant_id,
        metric_version=version,
        decisions=[
            {
                "decision_id": decision_id or f"d-{event_id}",
                "loop_id": "loop-1",
                "cycle_id": "cyc-1",
                "option_index": 0,
                "opened_ms": OPENED,
            }
        ],
        event_id=event_id,
        at_ms=at_ms,
        received_ms=received_ms,
    )
    ledger.insert_metric_events([event], ledger_ms=[received_ms])


ARRIVAL_WINDOW = 100_000


def test_arrival_gives_the_times_by_which_half_and_99_percent_happened(ledger):
    for second in range(1, 99):
        arrive(ledger, second * 1_000, f"e{second}")
    arrive(ledger, 100_000, "e99")
    arrive(ledger, 100_000, "e100")

    (arrival,) = ledger.metric_arrivals(
        "t1", [MetricVersion("m-1", "1.0", ARRIVAL_WINDOW)], OPENED
    )

    assert arrival.outcomes == 100
    assert arrival.half_ms == 51_000
    assert arrival.p99_ms == 100_000
    assert arrival.late == 0
    assert sum(arrival.buckets) == 100


def test_arrival_buckets_the_window_and_counts_late_once_per_decision(ledger):
    arrive(ledger, 10_000, "a")
    arrive(ledger, 30_000, "b")
    arrive(ledger, 30_000, "b")
    arrive(ledger, 99_000, "c")
    arrive(ledger, 150_000, "late-happened")
    arrive(ledger, 20_000, "late-arrived", arrived_ms=120_000)
    arrive(ledger, 5_000, "older-version", version="0.1")
    arrive(ledger, 5_000, "elsewhere", tenant_id="t2")

    (arrival,) = ledger.metric_arrivals(
        "t1", [MetricVersion("m-1", "1.0", ARRIVAL_WINDOW)], OPENED, buckets=4
    )

    assert arrival.outcomes == 5
    assert arrival.late == 2
    assert arrival.buckets == (2, 1, 0, 1, 1)


def test_arrival_reads_every_metric_under_its_own_version(ledger):
    arrive(ledger, 10_000, "a")
    arrive(ledger, 10_000, "b", version="2.0")

    arrivals = ledger.metric_arrivals(
        "t1",
        [
            MetricVersion("m-1", "2.0", ARRIVAL_WINDOW),
            MetricVersion("m-9", "1.0", ARRIVAL_WINDOW),
        ],
        OPENED,
    )

    assert [(a.metric_id, a.outcomes) for a in arrivals] == [("m-1", 1)]
    assert ledger.metric_arrivals("t1", [], OPENED) == []


def test_the_pulse_counts_each_event_once_by_the_minute_it_reached_the_ledger(
    ledger,
):
    minute = OPENED // 60_000 * 60_000
    arrive(ledger, minute - OPENED + 1_000, "a")
    arrive(ledger, minute - OPENED + 2_000, "a")
    arrive(ledger, minute - OPENED + 59_000, "b")
    arrive(ledger, minute - OPENED + 61_000, "c")
    arrive(ledger, minute - OPENED + 61_000, "x", tenant_id="t2")

    pulse = ledger.metric_pulse("t1", minute, minute + 120_000)

    assert sorted((p.minute_ms, p.outcomes) for p in pulse) == [
        (minute, 2),
        (minute + 60_000, 1),
    ]
