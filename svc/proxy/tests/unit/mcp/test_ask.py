"""a question in the chat: asked only of a client that can ask on a revision
with input-required results, and read as approve, decline with an optional
reason, or closed, which leaves the change waiting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp_types import ClientCapabilities
from mcp_types import ElicitationCapability
from mcp_types import ElicitResult
from mcp_types import FormElicitationCapability
from mcp_types import UrlElicitationCapability

from proxysvc.transport.mcp import ask

pytestmark = pytest.mark.unit


def _ctx(version, elicitation):
    capabilities = (
        ClientCapabilities(elicitation=elicitation)
        if elicitation is not False
        else None
    )
    return SimpleNamespace(protocol_version=version, client_capabilities=capabilities)


@pytest.mark.parametrize(
    "version, elicitation, expected",
    [
        ("2026-07-28", ElicitationCapability(form=FormElicitationCapability()), True),
        ("2026-07-28", ElicitationCapability(), True),
        ("2026-07-28", ElicitationCapability(url=UrlElicitationCapability()), False),
        ("2026-07-28", None, False),
        ("2026-07-28", False, False),
        ("2025-11-25", ElicitationCapability(form=FormElicitationCapability()), False),
        (None, ElicitationCapability(), False),
    ],
)
def test_who_can_be_asked(version, elicitation, expected):
    assert ask.can_ask(_ctx(version, elicitation)) is expected


def _reply(action, content=None):
    return {ask.QUESTION: ElicitResult(action=action, content=content)}


@pytest.mark.parametrize(
    "responses, expected",
    [
        (_reply("accept", {"answer": "approve"}), ask.Answer("approve")),
        (
            _reply("accept", {"answer": "decline", "reason": " not yet "}),
            ask.Answer("decline", "not yet"),
        ),
        (
            _reply("accept", {"answer": "decline", "reason": "  "}),
            ask.Answer("decline"),
        ),
        (_reply("decline"), ask.Answer("decline")),
        (_reply("cancel"), ask.Answer("closed")),
        (_reply("accept", {"answer": "maybe"}), ask.Answer("closed")),
        (_reply("accept"), ask.Answer("closed")),
        ({}, ask.Answer("closed")),
        (None, ask.Answer("closed")),
    ],
)
def test_reading_the_answer(responses, expected):
    assert ask.read(responses) == expected


def test_the_state_names_the_change_and_connection():
    assert ask.unseal(ask.seal("chg-1", "con-1")) == ("chg-1", "con-1")


@pytest.mark.parametrize("state", ["", "{}", "[1]", "not json"])
def test_a_state_qbrix_never_wrote_is_refused(state):
    with pytest.raises(ValueError):
        ask.unseal(state)


def test_the_question_carries_the_reason_and_offers_approve_first():
    [request] = ask.question(
        "Claude Code asks to launch Checkout headline.", "ready"
    ).values()

    assert request.params.message == (
        'Claude Code asks to launch Checkout headline. Reason: "ready". '
        "Nothing applies until you answer."
    )
    answer = request.params.requested_schema["properties"]["answer"]
    assert [choice["const"] for choice in answer["oneOf"]] == ["approve", "decline"]
    assert answer["default"] == "approve"
