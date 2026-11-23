"""which decision an event sent with only a unit credits in each loop."""

from __future__ import annotations

import pytest

from qbrixstore.clickhouse.ledger import LedgerDecision
from qbrixstore.clickhouse.ledger import UnitEvent

from cortexsvc.attribution import match_units

pytestmark = pytest.mark.unit

RACE = 60_000
WINDOW = 3_600_000


def decision(
    decision_id: str,
    opened_ms: int,
    loop_id: str = "headline",
    unit: str = "visitor-7",
    metric_id: str = "purchase",
    ledger_ms: int | None = None,
) -> LedgerDecision:
    return LedgerDecision(
        tenant_id="t1",
        loop_id=loop_id,
        cycle_id=f"{loop_id}-cycle",
        decision_id=decision_id,
        option_index=1,
        unit=unit,
        metric_id=metric_id,
        metric_version="1.0",
        metric_type="conversion",
        opened_ms=opened_ms,
        window_ms=WINDOW,
        ledger_ms=opened_ms if ledger_ms is None else ledger_ms,
    )


def event(
    at_ms: int,
    unit: str = "visitor-7",
    metric_id: str = "purchase",
    ledger_ms: int | None = None,
) -> UnitEvent:
    return UnitEvent(
        tenant_id="t1",
        metric_id=metric_id,
        unit=unit,
        event_id="order-1",
        value=1.0,
        at_ms=at_ms,
        received_ms=at_ms,
        ledger_ms=at_ms if ledger_ms is None else ledger_ms,
    )


def credited(result) -> set[str]:
    return {match.decision_id for match in result.matches}


def test_the_most_recent_open_decision_in_the_loop_is_credited():
    result = match_units(
        [event(5_000_000)],
        [decision("older", 2_000_000), decision("latest", 4_000_000)],
        RACE,
    )

    assert credited(result) == {"latest"}
    assert result.unattributed == {}


def test_each_loop_that_improves_the_metric_gets_its_own_match():
    result = match_units(
        [event(5_000_000)],
        [
            decision("headline-d", 4_000_000, loop_id="headline"),
            decision("button-d", 3_000_000, loop_id="button"),
        ],
        RACE,
    )

    assert credited(result) == {"headline-d", "button-d"}


def test_a_closed_decision_or_one_opened_after_the_event_is_not_credited():
    result = match_units(
        [event(5_000_000)],
        [
            decision("closed", 5_000_000 - WINDOW - 1),
            decision("after", 5_000_001, loop_id="button"),
        ],
        RACE,
    )

    assert credited(result) == set()
    assert result.unattributed == {("t1", "purchase"): 1}


def test_decisions_for_another_metric_or_unit_are_ignored():
    result = match_units(
        [event(5_000_000)],
        [
            decision("click", 4_000_000, metric_id="click"),
            decision("someone-else", 4_000_000, unit="visitor-8"),
        ],
        RACE,
    )

    assert credited(result) == set()
    assert result.unattributed == {("t1", "purchase"): 1}


def test_a_decision_that_reached_the_ledger_after_the_race_is_not_seen():
    result = match_units(
        [event(5_000_000)],
        [
            decision("in-time", 4_000_000, ledger_ms=5_000_000 + RACE - 1),
            decision("too-late", 4_500_000, ledger_ms=5_000_000 + RACE),
        ],
        RACE,
    )

    assert credited(result) == {"in-time"}


def test_a_match_is_judged_one_race_after_the_event_reached_the_ledger():
    [match] = match_units(
        [event(5_000_000, ledger_ms=5_000_100)], [decision("d", 4_000_000)], RACE
    ).matches

    assert match.ledger_ms == 5_000_100 + RACE
    assert (match.event_id, match.value, match.at_ms) == ("order-1", 1.0, 5_000_000)
