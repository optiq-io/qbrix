"""loop_get's paused line: who paused a paused loop, when and why, read from
its latest change, and nothing for any other state or change."""

from __future__ import annotations

import pytest

from proxysvc.transport.mcp.tool import _paused_line

pytestmark = pytest.mark.unit

EVIDENCE = {
    "signal": "decision_errors",
    "rate": 0.0612,
    "errors": 7,
    "calls": 114,
    "window_start": "2026-10-27T09:58:00+00:00",
    "window_end": "2026-10-27T10:01:40+00:00",
    "reasons": {"motor_unavailable": 4, "targeting_unavailable": 3},
}


def _loop(state: str = "paused", **entry) -> dict:
    return {
        "state": state,
        "latest_change": {
            "kind": "loop.pause",
            "at": "2026-10-27T10:01:40+00:00",
            "who": {"kind": "qbrix", "user_id": None, "name": None},
            "via": None,
            "reason": "decision errors",
            "evidence": EVIDENCE,
            **entry,
        },
    }


def test_a_window_shorter_than_ten_minutes_says_how_long_it_was():
    assert _paused_line(_loop()) == (
        "Paused by qbrix at 2026-10-27 10:01 UTC: 6.1% of 114 calls failed over "
        "4 minutes (motor_unavailable 4, targeting_unavailable 3). Everyone gets "
        "the fallback until a person resumes it."
    )


def test_a_person_reads_with_their_client_and_reason():
    loop = _loop(
        who={"kind": "connection", "user_id": "u", "name": "Ada"},
        via={"connection_id": "c", "client": "Claude Code"},
        reason="checkout is being rebuilt",
        evidence=None,
    )

    assert _paused_line(loop) == (
        "Paused by Ada via Claude Code at 2026-10-27 10:01 UTC: checkout is being "
        "rebuilt. Everyone gets the fallback until a person resumes it."
    )


@pytest.mark.parametrize(
    "loop",
    [
        _loop(state="live"),
        _loop(kind="loop.rename"),
        {"state": "paused", "latest_change": None},
    ],
)
def test_says_nothing_unless_the_latest_change_paused_it(loop):
    assert _paused_line(loop) is None
