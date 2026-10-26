"""the sealing rules: when a decision seals, with what, and how each outcome
is counted, all by ledger time."""

from __future__ import annotations

import pytest

from qbrixstore.clickhouse.ledger import LedgerDecision
from qbrixstore.clickhouse.ledger import LedgerOutcome
from qbrixstore.redis import OutcomeDisposition

from cortexsvc.seal import seal_slice

pytestmark = pytest.mark.unit

OPENED = 1_000_000
WINDOW = 60_000
CLOSES = OPENED + WINDOW

LEARNED = OutcomeDisposition.LEARNED
LATE = OutcomeDisposition.LATE
DUPLICATE = OutcomeDisposition.DUPLICATE


def decision(
    metric_type: str = "conversion", decision_id: str = "dec-1", **overrides
) -> LedgerDecision:
    fields = dict(
        tenant_id="t1",
        loop_id="loop-1",
        cycle_id="cyc-1",
        decision_id=decision_id,
        option_index=1,
        unit="user-1",
        metric_id="m-1",
        metric_version="1.0",
        metric_type=metric_type,
        opened_ms=OPENED,
        window_ms=WINDOW,
        ledger_ms=OPENED,
    )
    fields.update(overrides)
    return LedgerDecision(**fields)


def outcome(
    value: float,
    ledger_ms: int,
    event_id: str | None = None,
    at_ms: int | None = None,
    decision_id: str = "dec-1",
) -> LedgerOutcome:
    return LedgerOutcome(
        tenant_id="t1",
        decision_id=decision_id,
        event_id=event_id or f"ev-{ledger_ms}",
        value=value,
        at_ms=at_ms if at_ms is not None else ledger_ms,
        received_ms=ledger_ms,
        ledger_ms=ledger_ms,
    )


def everything(decisions, outcomes):
    """the whole ledger in one slice."""
    return seal_slice(decisions, outcomes, 0, 10**15)


def dispositions(result) -> list[OutcomeDisposition]:
    return [classified.disposition for classified in result.classified]


class TestConversion:
    def test_seals_with_1_at_its_first_outcome(self):
        result = everything([decision()], [outcome(1, OPENED + 5_000)])

        [sealed] = result.sealed
        assert sealed.value == 1.0
        assert sealed.sealed_ms == OPENED + 5_000
        assert sealed.sealed_by == "outcome"
        assert sealed.outcomes == 1

    def test_a_first_outcome_of_0_seals_0(self):
        result = everything(
            [decision()], [outcome(0, OPENED + 5_000), outcome(1, OPENED + 6_000)]
        )

        assert result.sealed[0].value == 0.0
        assert dispositions(result) == [LEARNED, DUPLICATE]

    def test_seals_0_when_its_window_closes_without_one(self):
        result = everything([decision()], [])

        [sealed] = result.sealed
        assert (sealed.value, sealed.sealed_ms, sealed.sealed_by) == (
            0.0,
            CLOSES,
            "window",
        )
        assert sealed.outcomes == 0

    def test_outcomes_after_the_first_are_duplicates_even_after_the_window(self):
        result = everything(
            [decision()],
            [
                outcome(1, OPENED + 5_000),
                outcome(1, CLOSES + 10, at_ms=OPENED + 6_000),
                outcome(1, CLOSES + 20, at_ms=CLOSES + 20),
            ],
        )

        assert dispositions(result) == [LEARNED, DUPLICATE, LATE]


class TestCountAndValue:
    @pytest.mark.parametrize("metric_type", ["count", "value"])
    def test_seal_the_sum_when_the_window_closes(self, metric_type):
        result = everything(
            [decision(metric_type)],
            [outcome(2, OPENED + 1_000), outcome(3.5, OPENED + 2_000)],
        )

        [sealed] = result.sealed
        assert (sealed.value, sealed.sealed_ms, sealed.outcomes) == (5.5, CLOSES, 2)
        assert dispositions(result) == [LEARNED, LEARNED]

    def test_seals_0_without_outcomes(self):
        assert everything([decision("value")], []).sealed[0].value == 0.0


class TestScore:
    def test_the_last_outcome_by_event_time_counts(self):
        result = everything(
            [decision("score")],
            [
                outcome(4, OPENED + 2_000, at_ms=OPENED + 2_000),
                outcome(2, OPENED + 3_000, at_ms=OPENED + 1_000),
            ],
        )

        assert result.sealed[0].value == 4.0

    def test_no_outcome_seals_with_nothing_to_learn(self):
        [sealed] = everything([decision("score")], []).sealed

        assert sealed.value is None
        assert sealed.outcomes == 0


class TestDuplicates:
    def test_a_resent_event_counts_once(self):
        result = everything(
            [decision("count")],
            [
                outcome(1, OPENED + 1_000, event_id="order-7"),
                outcome(1, OPENED + 2_000, event_id="order-7"),
            ],
        )

        assert result.sealed[0].value == 1.0
        assert dispositions(result) == [LEARNED, DUPLICATE]


class TestLate:
    def test_an_event_after_the_window_is_late(self):
        result = everything(
            [decision("count")],
            [outcome(1, CLOSES + 5_000, at_ms=CLOSES + 1)],
        )

        assert result.sealed[0].value == 0.0
        assert dispositions(result) == [LATE]

    def test_arriving_after_the_window_closed_is_late_even_if_it_happened_within(
        self,
    ):
        result = everything(
            [decision("value")],
            [outcome(9, CLOSES + 30_000, at_ms=OPENED + 1_000)],
        )

        assert result.sealed[0].value == 0.0
        assert dispositions(result) == [LATE]

    def test_a_conversion_without_a_first_outcome_counts_a_late_one_as_late(self):
        result = everything([decision()], [outcome(1, CLOSES + 1, at_ms=OPENED)])

        assert result.sealed[0].sealed_by == "window"
        assert dispositions(result) == [LATE]


class TestSlices:
    def test_nothing_seals_at_or_past_the_end(self):
        result = seal_slice([decision("count")], [], 0, CLOSES)

        assert result.sealed == []

    def test_a_decision_sealed_before_the_slice_is_not_sealed_again(self):
        result = seal_slice(
            [decision()], [outcome(1, OPENED + 5_000)], OPENED + 5_001, 10**15
        )

        assert result.sealed == []

    def test_outcomes_are_counted_in_the_slice_they_reached_the_ledger(self):
        outcomes = [outcome(1, OPENED + 1_000), outcome(1, OPENED + 9_000)]

        early = seal_slice([decision("count")], outcomes, 0, OPENED + 5_000)
        later = seal_slice([decision("count")], outcomes, OPENED + 5_000, 10**15)

        assert dispositions(early) == [LEARNED]
        assert dispositions(later) == [LEARNED]

    def test_every_split_seals_each_decision_once_with_the_same_value(self):
        decisions = [
            decision("conversion", "a"),
            decision("count", "b"),
            decision("score", "c"),
            decision("conversion", "d"),
        ]
        outcomes = [
            outcome(1, OPENED + 3_000, decision_id="a"),
            outcome(1, OPENED + 4_000, decision_id="a"),
            outcome(2, OPENED + 1_000, decision_id="b"),
            outcome(5, CLOSES + 1, decision_id="b"),
            outcome(3, OPENED + 2_000, decision_id="c"),
        ]
        whole = everything(decisions, outcomes)

        for step in (1_000, 7_000, 25_000):
            bounds = list(range(0, CLOSES + 2 * step, step))
            parts = [
                seal_slice(decisions, outcomes, start, end)
                for start, end in zip(bounds, bounds[1:])
            ]
            sealed = [s for part in parts for s in part.sealed]
            classified = [c for part in parts for c in part.classified]

            assert sorted(sealed, key=lambda s: s.decision_id) == sorted(
                whole.sealed, key=lambda s: s.decision_id
            )
            assert sorted(classified, key=lambda c: c.ledger_ms) == sorted(
                whole.classified, key=lambda c: c.ledger_ms
            )


class TestDecisionReachesTheLedgerLate:
    def test_an_outcome_is_counted_once_its_decision_is_in_the_ledger(self):
        late_decision = decision(ledger_ms=OPENED + 8_000)
        result = everything([late_decision], [outcome(1, OPENED + 5_000)])

        assert result.sealed[0].sealed_ms == OPENED + 8_000
        assert result.classified[0].ledger_ms == OPENED + 8_000

    def test_a_decision_that_reached_the_ledger_after_its_window_seals_then(self):
        result = everything([decision("count", ledger_ms=CLOSES + 500)], [])

        assert result.sealed[0].sealed_ms == CLOSES + 500


def test_an_unknown_metric_type_is_not_sealed():
    assert everything([decision("revenue")], []).sealed == []
