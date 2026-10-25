"""a decision's request_id: signed, scoped to its workspace, and never
mistaken for today's selection token."""

from __future__ import annotations

import pytest

from proxysvc.core.error import TokenInvalidError
from proxysvc.mod.agent.token import SelectionToken
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken

SECRET = b"secret"

DECISION = Decision(
    decision_id="dec-1",
    tenant_id="t1",
    loop_id="loop-1",
    cycle_id="cyc-1",
    option_index=2,
    unit="user-42",
    metric_version="1.0",
    timestamp_ms=1_700_000_000_000,
)


def test_round_trips():
    token = DecisionToken.encode(SECRET, DECISION)

    assert DecisionToken.decode(SECRET, token, "t1") == DECISION


def test_another_workspace_is_refused():
    token = DecisionToken.encode(SECRET, DECISION)

    with pytest.raises(TokenInvalidError, match="not issued to this workspace"):
        DecisionToken.decode(SECRET, token, "t2")


def test_another_secret_is_refused():
    token = DecisionToken.encode(SECRET, DECISION)

    with pytest.raises(TokenInvalidError, match="signature"):
        DecisionToken.decode(b"other", token, "t1")


def test_a_selection_token_is_not_a_decision():
    token = SelectionToken.encode(SECRET, "t1", "exp", 0, "ctx", [], {})

    with pytest.raises(TokenInvalidError, match="not a decision"):
        DecisionToken.decode(SECRET, token, "t1")


def test_a_decision_is_not_a_selection_token():
    token = DecisionToken.encode(SECRET, DECISION)

    with pytest.raises(TokenInvalidError, match="not a selection token"):
        SelectionToken.decode(SECRET, token, "t1")
