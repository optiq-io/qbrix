"""each alert reads as one sentence built from the evidence its rule records:
an opening says what is wrong, an ending says how it ended and, for a safety
pause, who resumed it and how long the loop was on its fallback. several
alerts get one first line, and every line links to its loop. no sentence
uses the words people don't use."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from qbrixstore.postgres.models import Alert
from qbrixstore.redis.health import Intake
from qbrixstore.redis.health import OutcomeHealth
from qbrixstore.redis.health import SelectHealth

from proxysvc.mod.milestone.entry import LoopName
from proxysvc.mod.people import People
from proxysvc.mod.safety.entry import alert_entry
from proxysvc.mod.safety.rule import CALLS_STOPPED
from proxysvc.mod.safety.rule import DECISION_ERRORS
from proxysvc.mod.safety.rule import OUTCOMES_NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED
from proxysvc.mod.safety.rule import calls_evidence
from proxysvc.mod.safety.rule import evidence
from proxysvc.mod.safety.rule import not_learned_evidence
from proxysvc.mod.safety.rule import stopped_evidence
from proxysvc.mod.safety.service import CLEARED
from proxysvc.mod.safety.service import OPENED
from proxysvc.mod.safety.service import RECOVERED
from proxysvc.mod.safety.service import RESUMED
from proxysvc.mod.safety.service import RETIRED
from proxysvc.mod.webhook.text import Notice
from proxysvc.mod.webhook.text import duration
from proxysvc.mod.webhook.text import line
from proxysvc.mod.webhook.text import message

pytestmark = pytest.mark.unit

ORIGIN = "https://console.acme.test"
OPENED_AT = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)
NOW_MS = int(OPENED_AT.timestamp() * 1000)
LOOP = LoopName("search-ranking", "Search ranking")
PEOPLE = People({"user-ada": "Ada"})
NEVER = ("error rate", "arm", "policy", "bandit")

EVIDENCE = {
    DECISION_ERRORS: evidence(
        SelectHealth(ok=382, error=30, by_reason={"motor_unavailable": 30}),
        first_minute=NOW_MS // 60_000 - 9,
        now_sec=NOW_MS / 1000,
    ),
    OUTCOMES_STOPPED: stopped_evidence(
        Intake(decisions=1500, outcomes=40, since_outcome=1240),
        window_ms=3_600_000,
        silent_since_ms=NOW_MS - 3_600_000,
        now_ms=NOW_MS,
    ),
    OUTCOMES_NOT_LEARNED: not_learned_evidence(
        OutcomeHealth(learned=160, not_learned=40, by_reason={"late": 40}), NOW_MS
    ),
    CALLS_STOPPED: calls_evidence(
        yesterday=1312, hour=NOW_MS // 3_600_000, now_ms=NOW_MS
    ),
}


def _entry(
    signal: str,
    *,
    resolution: str | None = None,
    by: str | None = "user-ada",
    after: timedelta = timedelta(hours=2),
    loop: LoopName = LOOP,
    loop_id: str = "loop-1",
) -> dict:
    alert = Alert(
        id=f"alert-{signal}",
        tenant_id="t",
        loop_id=loop_id,
        signal=signal,
        evidence=EVIDENCE[signal],
        opened_at=OPENED_AT,
    )
    if resolution is not None:
        alert.resolved_at = OPENED_AT + after
        alert.resolution = resolution
        alert.resolved_kind = "qbrix" if by is None else "member"
        alert.resolved_user_id = by
    return alert_entry(alert, loop, PEOPLE)


def test_a_safety_pause_says_what_failed_and_what_everyone_gets():
    text = line(Notice(_entry(DECISION_ERRORS), OPENED))

    assert text == (
        "qbrix paused Search ranking: 7% of its decisions failed."
        " Everyone gets the fallback until a person resumes it."
    )


@pytest.mark.parametrize(
    "signal, expected",
    [
        (
            OUTCOMES_STOPPED,
            "Search ranking stopped receiving outcomes: none in its last 1,240"
            " decisions.",
        ),
        (
            OUTCOMES_NOT_LEARNED,
            "Search ranking couldn't learn from 20% of its outcomes in the last hour.",
        ),
        (
            CALLS_STOPPED,
            "Search ranking stopped receiving calls: none in an hour that had"
            " 1,312 yesterday.",
        ),
    ],
)
def test_a_warning_opens_with_the_value_its_rule_recorded(signal, expected):
    assert line(Notice(_entry(signal), OPENED)) == expected


def test_a_resumed_pause_names_who_and_how_long_on_the_fallback():
    entry = _entry(DECISION_ERRORS, resolution=RESUMED)

    assert line(Notice(entry, RECOVERED)) == (
        "Search ranking resumed by Ada after 2 h on the fallback."
    )


def test_a_retired_pause_says_it_was_retired():
    entry = _entry(DECISION_ERRORS, resolution=RETIRED, after=timedelta(minutes=25))

    assert line(Notice(entry, RECOVERED)) == (
        "Search ranking retired by Ada after 25 min on the fallback."
    )


@pytest.mark.parametrize(
    "signal, expected",
    [
        (OUTCOMES_STOPPED, "Search ranking is receiving outcomes again."),
        (OUTCOMES_NOT_LEARNED, "Search ranking is learning from its outcomes again."),
        (CALLS_STOPPED, "Search ranking is receiving calls again."),
    ],
)
def test_a_cleared_warning_says_the_loop_is_healthy_again(signal, expected):
    entry = _entry(signal, resolution=CLEARED, by=None)

    assert line(Notice(entry, RECOVERED)) == expected


def test_retiring_ends_a_warning_by_name():
    entry = _entry(OUTCOMES_STOPPED, resolution=RETIRED)

    assert line(Notice(entry, RECOVERED)) == (
        "Search ranking was retired by Ada, which ends its warning."
    )


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (20, "1 min"),
        (59 * 60, "59 min"),
        (2 * 3600, "2 h"),
        (47 * 3600, "47 h"),
        (3 * 86400, "3 days"),
    ],
)
def test_durations(seconds, expected):
    assert duration(seconds) == expected


def test_one_alert_is_one_line_with_its_link():
    body = message([Notice(_entry(DECISION_ERRORS), OPENED)], "Acme", ORIGIN)

    assert body["text"].endswith(f" {ORIGIN}/next/loops/search-ranking")
    assert "\n" not in body["text"]
    (item,) = body["alerts"]
    assert item == {
        "event": OPENED,
        "loop": {"key": "search-ranking", "name": "Search ranking"},
        "signal": DECISION_ERRORS,
        "value": {k: v for k, v in EVIDENCE[DECISION_ERRORS].items() if k != "signal"},
        "opened_at": OPENED_AT.isoformat(),
        "url": f"{ORIGIN}/next/loops/search-ranking",
    }


def test_a_recovery_carries_how_it_ended():
    entry = _entry(DECISION_ERRORS, resolution=RESUMED)
    (item,) = message([Notice(entry, RECOVERED)], "Acme", ORIGIN)["alerts"]

    assert item["resolution"] == RESUMED
    assert item["resolved_by"] == "Ada"
    assert item["resolved_at"] == (OPENED_AT + timedelta(hours=2)).isoformat()


def _three(event: str, resolution: str | None = None) -> list[Notice]:
    return [
        Notice(
            _entry(
                OUTCOMES_STOPPED,
                resolution=resolution,
                by=None,
                loop=LoopName(f"loop-{i}", f"Loop {i}"),
                loop_id=f"loop-{i}",
            ),
            event,
        )
        for i in range(3)
    ]


def test_several_alerts_get_one_first_line():
    lines = message(_three(OPENED), "Acme", ORIGIN)["text"].split("\n")

    assert lines[0] == "3 loops need a look in Acme"
    assert len(lines) == 4
    assert lines[3].endswith(f"{ORIGIN}/next/loops/loop-2")


def test_the_first_line_says_how_many_are_healthy_again():
    recovered = _three(RECOVERED, CLEARED)

    assert message(recovered, "Acme", ORIGIN)["text"].split("\n")[0] == (
        "3 loops are healthy again in Acme"
    )
    mixed = _three(OPENED)[:2] + recovered[2:]
    assert message(mixed, "Acme", ORIGIN)["text"].split("\n")[0] == (
        "Acme: 2 loops need a look, 1 is healthy again"
    )


def test_no_text_uses_words_people_dont_use():
    texts = [message(_three(OPENED), "Acme", ORIGIN)["text"]]
    for signal in EVIDENCE:
        texts.append(line(Notice(_entry(signal), OPENED)))
        for resolution in (CLEARED, RESUMED, RETIRED):
            texts.append(line(Notice(_entry(signal, resolution=resolution), RECOVERED)))

    for text in texts:
        for word in NEVER:
            assert word not in text.lower().split(), (word, text)
        assert "error rate" not in text.lower()
