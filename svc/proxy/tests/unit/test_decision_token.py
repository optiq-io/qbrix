"""a decision's request_id: short enough to carry, signed for its workspace,
spelled one way only, and never mistaken for today's selection token."""

from __future__ import annotations

import uuid

import pytest

from proxysvc.core.error import TokenInvalidError
from proxysvc.mod.agent.token import SelectionToken
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken
from proxysvc.mod.loop.token import DecisionsToken

SECRET = b"secret"
TENANT = uuid.uuid4().hex

DECISION = Decision(
    decision_id=uuid.uuid4().hex,
    loop_id=uuid.uuid4().hex,
    cycle_id=uuid.uuid4().hex,
    metric_id=uuid.uuid4().hex,
    option_index=2,
    timestamp_ms=1_700_000_000_000,
)


def test_round_trips():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)

    assert DecisionToken.decode(SECRET, token, TENANT) == DECISION


def test_is_short_enough_to_carry():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)

    assert len(token) <= 115
    assert len(DecisionsToken.join([token] * 4)) <= 500


def test_is_url_safe():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)

    assert set(token) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


def test_another_workspace_is_refused():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)

    with pytest.raises(TokenInvalidError, match="doesn't verify"):
        DecisionToken.decode(SECRET, token, uuid.uuid4().hex)


def test_another_secret_is_refused():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)

    with pytest.raises(TokenInvalidError, match="doesn't verify"):
        DecisionToken.decode(b"other", token, TENANT)


@pytest.mark.parametrize("position", [3, 40, 90, -2])
def test_a_changed_character_is_refused(position):
    token = DecisionToken.encode(SECRET, TENANT, DECISION)
    swapped = "A" if token[position] != "A" else "B"
    forged = token[:position] + swapped + token[position:][1:]

    with pytest.raises(TokenInvalidError):
        DecisionToken.decode(SECRET, forged, TENANT)


def test_only_one_spelling_is_accepted():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)
    last = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    spare = last[last.index(token[-1]) ^ 1]

    with pytest.raises(TokenInvalidError, match="not a decision"):
        DecisionToken.decode(SECRET, token[:-1] + spare, TENANT)
    with pytest.raises(TokenInvalidError, match="not a decision"):
        DecisionToken.decode(SECRET, token + "==", TENANT)


def test_a_truncated_token_is_refused():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)

    with pytest.raises(TokenInvalidError, match="not a decision"):
        DecisionToken.decode(SECRET, token[:-4], TENANT)


def test_an_id_that_is_not_hex_fails_at_encode():
    with pytest.raises(ValueError):
        DecisionToken.encode(
            SECRET, TENANT, Decision(**{**DECISION.__dict__, "loop_id": "loop-1"})
        )


def test_a_selection_token_is_not_a_decision():
    token = SelectionToken.encode(SECRET, TENANT, "exp", 0, "ctx", [], {})

    with pytest.raises(TokenInvalidError, match="not a decision"):
        DecisionToken.decode(SECRET, token, TENANT)


def test_a_decision_is_not_a_selection_token():
    token = DecisionToken.encode(SECRET, TENANT, DECISION)

    with pytest.raises(TokenInvalidError):
        SelectionToken.decode(SECRET, token, TENANT)
