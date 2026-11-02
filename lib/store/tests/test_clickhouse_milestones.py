"""the milestones table and the trailing read against a real clickhouse, in a
scratch database.

skipped when no clickhouse answers on localhost (as in ci); run locally with
`make infra` up.
"""

from __future__ import annotations

import time
import uuid

import pytest

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.migrations import create_tables
from qbrixstore.config import ClickHouseSettings
from qbrixstore.event import MilestoneEvent

from lib.store.tests.test_event import a_selection

pytestmark = pytest.mark.integration

NOW = int(time.time() * 1000)
HOUR = 60 * 60 * 1000
DAY = 24 * HOUR


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


def event(event_id: str, **overrides) -> MilestoneEvent:
    return MilestoneEvent(
        **{
            "event_id": event_id,
            "kind": "loop.leader_changed",
            "tenant_id": "t1",
            "loop_id": "loop-1",
            "cycle_id": "cyc-1",
            "payload": {"from": None, "to": 1},
            "at_ms": NOW,
            **overrides,
        }
    )


class TestMilestones:
    def test_it_keeps_no_ttl(self, ledger):
        created = ledger.client.command("SHOW CREATE TABLE milestones")

        assert "TTL" not in created

    def test_an_event_written_twice_is_one_row(self, ledger):
        ledger.insert_milestones([event("a")])
        ledger.insert_milestones([event("a")])

        assert [e.event_id for e in ledger.query_milestones("t1")] == ["a"]

    def test_the_payload_round_trips(self, ledger):
        ledger.insert_milestones([event("a")])

        assert ledger.query_milestones("t1")[0] == event("a")

    def test_it_reads_newest_first_and_filters(self, ledger):
        ledger.insert_milestones(
            [
                event("old", at_ms=NOW - HOUR),
                event("new", at_ms=NOW),
                event("seal", kind="loop.first_seal", at_ms=NOW - DAY),
                event("other", loop_id="loop-2"),
                event("theirs", tenant_id="t2"),
            ]
        )

        ids = lambda **kw: [e.event_id for e in ledger.query_milestones("t1", **kw)]
        assert ids() == ["new", "other", "old", "seal"]
        assert ids(loop_ids=["loop-1"]) == ["new", "old", "seal"]
        assert ids(kinds=["loop.first_seal"]) == ["seal"]
        assert ids(since_ms=NOW - HOUR, loop_ids=["loop-1"]) == ["new", "old"]
        assert ids(limit=1) == ["new"]

    def test_no_loops_allowed_reads_none(self, ledger):
        ledger.insert_milestones([event("a")])

        assert ledger.query_milestones("t1", loop_ids=[]) == []


class TestTrailingDecisions:
    def decide(self, ledger, decision_id, option, ledger_ms, opened_ms=None):
        ledger.insert_selection_events(
            [
                a_selection(
                    tenant_id="t1",
                    experiment_id="cyc-1",
                    loop_id="loop-1",
                    cycle_id="cyc-1",
                    decision_id=decision_id,
                    arm_index=option,
                    timestamp_ms=opened_ms or ledger_ms,
                    window_ms=DAY,
                )
            ],
            ledger_ms=[ledger_ms],
        )

    def test_it_counts_each_decision_once_inside_the_range(self, ledger):
        self.decide(ledger, "a", 0, NOW - HOUR)
        self.decide(ledger, "a", 0, NOW - HOUR)
        self.decide(ledger, "b", 1, NOW - 2 * HOUR)
        self.decide(ledger, "c", 1, NOW - HOUR)
        self.decide(ledger, "before", 1, NOW - 2 * DAY)
        self.decide(ledger, "after", 1, NOW)

        rows = ledger.trailing_decisions(NOW - DAY, NOW)

        assert {r.option_index: r.decisions for r in rows} == {0: 1, 1: 2}
        assert {r.window_ms for r in rows} == {DAY}
        assert min(r.first_ms for r in rows) == NOW - 2 * HOUR

    def test_it_ignores_a_call_that_was_no_decision(self, ledger):
        self.decide(ledger, "", 0, NOW - HOUR)

        assert ledger.trailing_decisions(NOW - DAY, NOW) == []
