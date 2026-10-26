"""unit tests for the statistics behind a loop's results.

invariants verified:
  the series step is the smallest on the ladder that fits the span in 48
  columns, and the columns are step-aligned and never more than 48. lift is
  the mean per sealed decision over the even split of option means, exact on
  the worked example, and absent while any option has no sealed decision.
  an option's range narrows with its decisions: wilson for a conversion, the
  observed spread for the other types, none from a single value.
"""

from __future__ import annotations

import pytest

from proxysvc.mod.loop.stat import DAY_MS
from proxysvc.mod.loop.stat import HOUR_MS
from proxysvc.mod.loop.stat import MAX_COLUMNS
from proxysvc.mod.loop.stat import MINUTE_MS
from proxysvc.mod.loop.stat import columns
from proxysvc.mod.loop.stat import lift
from proxysvc.mod.loop.stat import normal
from proxysvc.mod.loop.stat import option_range
from proxysvc.mod.loop.stat import step_for
from proxysvc.mod.loop.stat import wilson

pytestmark = pytest.mark.unit


class TestLadder:
    @pytest.mark.parametrize(
        ("span_ms", "step_ms"),
        [
            (30 * MINUTE_MS, MINUTE_MS),
            (48 * MINUTE_MS, MINUTE_MS),
            (49 * MINUTE_MS, 5 * MINUTE_MS),
            (DAY_MS, 30 * MINUTE_MS),
            (7 * DAY_MS, 6 * HOUR_MS),
            (90 * DAY_MS, DAY_MS),
        ],
    )
    def test_picks_the_smallest_step_that_fits(self, span_ms, step_ms):
        assert step_for(span_ms) == step_ms

    def test_columns_are_aligned_to_the_step(self):
        cells = columns(90_000, 4 * MINUTE_MS + 1, MINUTE_MS)

        assert cells == [MINUTE_MS, 2 * MINUTE_MS, 3 * MINUTE_MS, 4 * MINUTE_MS]

    def test_never_more_than_48_columns(self):
        step = 30 * MINUTE_MS
        until = 100 * DAY_MS + 7 * MINUTE_MS

        cells = columns(until - DAY_MS, until, step)

        assert len(cells) == MAX_COLUMNS
        assert cells[-1] == until // step * step

    def test_an_empty_span_has_no_columns(self):
        assert columns(5_000, 5_000, MINUTE_MS) == []


class TestLift:
    def test_the_worked_example(self):
        """10% and 20% conversion with a 1:3 split: 0.175 over 0.15."""
        value = lift([(1_000, 100.0), (3_000, 600.0)])

        assert value == pytest.approx(0.175 / 0.15 - 1)
        assert round(value * 100, 1) == 16.7

    def test_an_even_split_has_no_lift(self):
        assert lift([(1_000, 100.0), (1_000, 200.0)]) == pytest.approx(0.0)

    def test_none_while_an_option_has_no_sealed_decision(self):
        assert lift([(1_000, 100.0), (0, 0.0)]) is None

    def test_none_when_nothing_converted(self):
        assert lift([(10, 0.0), (10, 0.0)]) is None

    def test_none_without_options(self):
        assert lift([]) is None


class TestRanges:
    def test_wilson_matches_known_values(self):
        low, high = wilson(10, 100)

        assert low == pytest.approx(0.0552, abs=1e-4)
        assert high == pytest.approx(0.1744, abs=1e-4)

    def test_wilson_stays_inside_zero_and_one(self):
        assert wilson(0, 5)[0] == 0.0
        assert wilson(5, 5)[1] == 1.0

    def test_a_thin_option_has_a_wider_range(self):
        thin = option_range("conversion", 20, 4.0, 4.0)
        thick = option_range("conversion", 2_000, 400.0, 400.0)

        assert (thin[1] - thin[0]) > 5 * (thick[1] - thick[0])

    def test_value_uses_the_observed_spread(self):
        low, high = normal(4, 20.0, 104.0)

        assert (low + high) / 2 == pytest.approx(5.0)
        assert high - low == pytest.approx(2 * 1.96 * (4 / 3) ** 0.5 / 2, abs=1e-3)

    def test_one_value_has_no_range(self):
        assert option_range("value", 1, 3.0, 9.0) is None

    def test_no_decisions_have_no_range(self):
        assert option_range("conversion", 0, 0.0, 0.0) is None
