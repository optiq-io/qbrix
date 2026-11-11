from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from mcp.server.mcpserver import Context
from mcp_types import ElicitRequest
from mcp_types import ElicitRequestFormParams
from mcp_types import InputRequests
from mcp_types import InputResponses
from mcp_types.version import is_version_at_least

QUESTION = "answer"
ASKS_SINCE = "2026-07-28"

_FORM = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "title": "Your answer",
            "oneOf": [
                {"const": "approve", "title": "Approve"},
                {"const": "decline", "title": "Decline"},
            ],
            "default": "approve",
        },
        "reason": {
            "type": "string",
            "title": "Reason for declining",
            "description": "Optional. Kept with the decline, so agents read it "
            "before proposing this again.",
        },
    },
    "required": ["answer"],
}


@dataclass(frozen=True)
class Answer:
    verdict: Literal["approve", "decline", "closed"]
    reason: str | None = None


def can_ask(ctx: Context) -> bool:
    """whether the client asks its person in the chat: on a revision with
    input-required results, and having declared form elicitation."""
    version = ctx.protocol_version
    if version is None or not is_version_at_least(version, ASKS_SINCE):
        return False
    capabilities = ctx.client_capabilities
    elicitation = capabilities.elicitation if capabilities is not None else None
    return elicitation is not None and (
        elicitation.form is not None or elicitation.url is None
    )


def question(sentence: str, reason: str | None) -> InputRequests:
    """the change in the words of its page, and the person's answer."""
    words = [sentence.strip()]
    if reason:
        words.append(f'Reason: "{reason}".')
    words.append("Nothing applies until you answer.")
    return {
        QUESTION: ElicitRequest(
            params=ElicitRequestFormParams(
                message=" ".join(words), requested_schema=_FORM
            )
        )
    }


def seal(change_id: str, connection_id: str) -> str:
    return json.dumps({"change": change_id, "connection": connection_id})


def unseal(state: str) -> tuple[str, str]:
    """the change and connection a question was asked for. the sdk has already
    verified the state, so anything else here is a state qbrix never wrote."""
    try:
        data = json.loads(state)
        return str(data["change"]), str(data["connection"])
    except (ValueError, TypeError, KeyError) as e:
        raise ValueError("not a question qbrix asked") from e


def read(responses: InputResponses | None) -> Answer:
    """the person's answer. the client's own decline turns the change down;
    closing the question, or an answer that isn't one, leaves it waiting."""
    response = (responses or {}).get(QUESTION)
    action = getattr(response, "action", None)
    if action == "decline":
        return Answer("decline")
    if action != "accept":
        return Answer("closed")
    content = getattr(response, "content", None) or {}
    verdict = content.get("answer")
    if verdict == "approve":
        return Answer("approve")
    if verdict == "decline":
        reason = content.get("reason")
        reason = reason.strip() if isinstance(reason, str) else ""
        return Answer("decline", reason or None)
    return Answer("closed")
