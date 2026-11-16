"""the warnings' rules, read from counts alone.

invariants verified:
  outcomes stopped needs decisions in the last hour and at least 100 since
  the last outcome; then a whole window of silence warns whatever its
  length, or half an hour does once the decisions since are more than ten
  times the usual decisions per outcome. a cycle that never had an outcome
  has only the whole-window test, and the clock starts at the latest of the
  last outcome and when the loop started serving. outcomes not learned warns
  above 10% of at least 100 outcomes, counting late, duplicate and invalid
  but never train_error or earlier_cycle. calls stopped warns when a loop
  serving through both hours had no call since the last full hour began and
  at least 60 in the same hour yesterday.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

import pytest

from qbrixstore.redis.health import Intake
from qbrixstore.redis.health import OutcomeHealth

from proxysvc.mod.safety.rule import CALLS_STOPPED
from proxysvc.mod.safety.rule import OUTCOMES_NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED
from proxysvc.mod.safety.rule import calls_evidence
from proxysvc.mod.safety.rule import calls_silent
from proxysvc.mod.safety.rule import calls_stopped
from proxysvc.mod.safety.rule import not_learned_evidence
from proxysvc.mod.safety.rule import outcomes_not_learned
from proxysvc.mod.safety.rule import outcomes_stopped
from proxysvc.mod.safety.rule import stopped_evidence

pytestmark = pytest.mark.unit

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
DAY_MS = 24 * HOUR_MS
WEEK_MS = 7 * DAY_MS
NOW_MS = 1_800_000_000_000


def _stopped(
    intake: Intake,
    *,
    silent_minutes: float,
    window_ms: int = WEEK_MS,
    deciding: bool = True,
) -> bool:
    return outcomes_stopped(
        intake,
        window_ms=window_ms,
        silent_since_ms=NOW_MS - int(silent_minutes * MINUTE_MS),
        now_ms=NOW_MS,
        deciding=deciding,
    )


def _usual(per_outcome: int, outcomes: int, since: int) -> Intake:
    """a cycle that saw one outcome every ``per_outcome`` decisions, then
    ``since`` decisions with none."""
    return Intake(
        decisions=per_outcome * outcomes + since,
        outcomes=outcomes,
        since_outcome=since,
        last_outcome_ms=NOW_MS - HOUR_MS,
    )


class TestOutcomesStopped:
    @pytest.mark.parametrize("window_ms", [HOUR_MS, 2 * DAY_MS, WEEK_MS, 30 * DAY_MS])
    def test_a_whole_silent_window_warns_whatever_its_length(self, window_ms):
        intake = _usual(1_000, 3, 100)

        assert _stopped(
            intake, silent_minutes=window_ms / MINUTE_MS, window_ms=window_ms
        )
        assert not _stopped(
            intake, silent_minutes=window_ms / MINUTE_MS - 1, window_ms=window_ms
        )

    def test_ten_times_the_usual_gap_warns_after_half_an_hour_on_a_long_window(self):
        assert _stopped(_usual(20, 50, 201), silent_minutes=30)
        assert not _stopped(_usual(20, 50, 200), silent_minutes=30)
        assert not _stopped(_usual(20, 50, 201), silent_minutes=29)

    def test_a_rare_outcome_needs_proportionally_more_silence(self):
        assert not _stopped(_usual(100, 50, 200), silent_minutes=120)
        assert _stopped(_usual(100, 50, 1_001), silent_minutes=120)

    def test_fewer_than_100_decisions_since_the_last_outcome_never_warn(self):
        assert not _stopped(_usual(5, 50, 99), silent_minutes=WEEK_MS / MINUTE_MS)
        assert _stopped(_usual(5, 50, 100), silent_minutes=30)

    def test_a_quiet_hour_without_decisions_warns_nothing(self):
        intake = _usual(20, 50, 5_000)

        assert not _stopped(intake, silent_minutes=WEEK_MS, deciding=False)

    def test_a_cycle_that_never_had_an_outcome_has_only_the_window(self):
        never = Intake(decisions=5_000, since_outcome=5_000)

        assert not _stopped(never, silent_minutes=WEEK_MS / MINUTE_MS - 1)
        assert _stopped(never, silent_minutes=WEEK_MS / MINUTE_MS)

    def test_the_evidence_says_how_silent_and_against_what(self):
        intake = _usual(20, 50, 300)
        found = stopped_evidence(
            intake,
            window_ms=WEEK_MS,
            silent_since_ms=NOW_MS - HOUR_MS,
            now_ms=NOW_MS,
        )

        assert found["signal"] == OUTCOMES_STOPPED
        assert found["decisions_since_outcome"] == 300
        assert found["usual_decisions_per_outcome"] == 20.0
        assert found["window_sec"] == WEEK_MS // 1000
        assert found["last_outcome_at"] == found["silent_since"]


def _health(learned: int, **missed: int) -> OutcomeHealth:
    return OutcomeHealth(
        learned=learned, not_learned=sum(missed.values()), by_reason=missed
    )


class TestOutcomesNotLearned:
    def test_above_a_tenth_of_100_outcomes_warns(self):
        assert outcomes_not_learned(_health(89, late=6, duplicate=3, invalid=2))

    def test_exactly_a_tenth_warns_nothing(self):
        assert not outcomes_not_learned(_health(90, late=10))

    def test_99_outcomes_warn_nothing(self):
        assert not outcomes_not_learned(_health(49, invalid=50))

    def test_train_errors_and_earlier_cycles_say_nothing_of_the_wiring(self):
        assert not outcomes_not_learned(
            _health(80, train_error=50, earlier_cycle=50, late=5)
        )

    def test_the_evidence_names_the_rate_and_its_reasons(self):
        found = not_learned_evidence(_health(80, late=15, train_error=4), NOW_MS)

        assert found["signal"] == OUTCOMES_NOT_LEARNED
        assert found["rate"] == round(15 / 95, 4)
        assert found["outcomes"] == 95
        assert found["reasons"] == {"late": 15}
        assert found["window_minutes"] == 60


HOUR = NOW_MS // HOUR_MS
YESTERDAY_START_MS = (HOUR - 25) * HOUR_MS


def _calls(
    *,
    last_hour: int = 0,
    this_hour: int = 0,
    yesterday: int = 60,
    serving_since_ms: int = YESTERDAY_START_MS,
) -> bool:
    return calls_stopped(
        last_hour=last_hour,
        this_hour=this_hour,
        yesterday=yesterday,
        hour=HOUR,
        serving_since_ms=serving_since_ms,
    )


class TestCallsStopped:
    def test_a_silent_hour_after_60_calls_yesterday_warns(self):
        assert _calls()

    def test_59_calls_yesterday_warn_nothing(self):
        assert not _calls(yesterday=59)

    def test_a_call_in_either_hour_warns_nothing(self):
        assert not _calls(last_hour=1)
        assert not _calls(this_hour=1)

    def test_a_loop_not_serving_for_all_of_both_hours_warns_nothing(self):
        assert not _calls(serving_since_ms=YESTERDAY_START_MS + MINUTE_MS)

    def test_silence_is_no_call_since_the_last_full_hour_began(self):
        assert calls_silent(last_hour=0, this_hour=0)
        assert not calls_silent(last_hour=0, this_hour=3)

    def test_the_evidence_names_yesterdays_calls_and_the_hours(self):
        found = calls_evidence(yesterday=240, hour=HOUR, now_ms=NOW_MS)

        assert found["signal"] == CALLS_STOPPED
        assert found["calls_same_hour_yesterday"] == 240
        assert found["silent_since"] == _iso((HOUR - 1) * HOUR_MS)
        assert found["yesterday_hour_start"] == _iso(YESTERDAY_START_MS)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()
