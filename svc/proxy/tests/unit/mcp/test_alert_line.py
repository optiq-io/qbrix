"""an alert in the words agents read: an open one as what needs a look, with
its signal's value from its evidence, and one that ended as how and when it
recovered and how long it was open."""

from __future__ import annotations

import pytest

from proxysvc.transport.mcp.tool import _list_alerts_line
from proxysvc.transport.mcp.tool import _needs_a_look_line
from proxysvc.transport.mcp.tool import _recovered_line

pytestmark = pytest.mark.unit

OPENED = "2026-11-16T03:12:00+00:00"


def _alert(signal: str, evidence: dict, **ended) -> dict:
    return {
        "signal": signal,
        "opened_at": OPENED,
        "resolved_at": None,
        "resolution": None,
        "resolved_by": None,
        "evidence": evidence,
        **ended,
    }


def _ended(signal: str, resolution: str, at: str, by: dict | None = None) -> dict:
    return _alert(
        signal,
        {"signal": signal},
        resolved_at=at,
        resolution=resolution,
        resolved_by=by or {"kind": "qbrix", "user_id": None, "name": None},
    )


@pytest.mark.parametrize(
    "signal, evidence, said",
    [
        (
            "outcomes_stopped",
            {"decisions_since_outcome": 1240, "usual_decisions_per_outcome": 18.5},
            "outcomes stopped. 1,240 decisions since the last outcome; "
            "usually one every 18.5.",
        ),
        (
            "outcomes_stopped",
            {"decisions_since_outcome": 240, "usual_decisions_per_outcome": None},
            "outcomes stopped. 240 decisions since the last outcome; "
            "none yet this cycle.",
        ),
        (
            "outcomes_not_learned",
            {"rate": 0.125, "outcomes": 400, "reasons": {}},
            "outcomes not learned. 12% of the last hour's 400 outcomes couldn't "
            "be learned from.",
        ),
        (
            "decision_errors",
            {"rate": 0.0612, "calls": 114},
            "qbrix paused it. 6.1% of 114 calls failed.",
        ),
        ("decision_errors", {}, "qbrix paused it."),
    ],
)
def test_an_open_alert_says_its_signal_and_value(signal, evidence, said):
    line = _needs_a_look_line(_alert(signal, evidence))

    assert line == f"Needs a look since 16 Nov 03:12 UTC: {said}"


@pytest.mark.parametrize(
    "alert, said",
    [
        (
            _ended("outcomes_stopped", "cleared", "2026-11-16T05:40:00+00:00"),
            "Recovered 16 Nov 05:40 UTC: outcomes arriving again, after 2h 28m "
            "(outcomes stopped).",
        ),
        (
            _ended("outcomes_not_learned", "cleared", "2026-11-16T03:52:00+00:00"),
            "Recovered 16 Nov 03:52 UTC: outcomes learned again, after 40 minutes "
            "(outcomes not learned).",
        ),
        (
            _ended(
                "decision_errors",
                "resumed",
                "2026-11-19T03:12:00+00:00",
                {"kind": "connection", "user_id": "u", "name": "Ada"},
            ),
            "Recovered 19 Nov 03:12 UTC: resumed by Ada through a connection, "
            "after 3 days (qbrix paused it).",
        ),
        (
            _ended("outcomes_stopped", "retired", "2026-11-16T03:12:30+00:00"),
            "Ended 16 Nov 03:12 UTC: the loop was retired, after under a minute "
            "(outcomes stopped).",
        ),
    ],
)
def test_an_ended_alert_says_how_when_and_after_how_long(alert, said):
    assert _recovered_line(alert) == said


def test_the_list_names_every_open_signal():
    alerts = [{"signal": "decision_errors"}, {"signal": "outcomes_stopped"}]

    assert _list_alerts_line(alerts) == (
        "needs a look (qbrix paused it, outcomes stopped)"
    )
