from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from proxysvc.core.error import GitHubStateError
from proxysvc.core.error import TokenInvalidError
from proxysvc.mod.agent.token import sign
from proxysvc.mod.agent.token import verify

Step = Literal["created", "installed"]

TTL_SEC = 15 * 60


@dataclass(frozen=True, slots=True)
class State:
    """one leg of the round trip through github: which workspace and admin
    started it, and the events token of the app it is making."""

    tenant_id: str
    user_id: str
    step: Step
    events_token: str


class StateSigner:

    def __init__(self, key: bytes):
        self._key = key

    def sign(self, state: State, *, now: float) -> str:
        return sign(
            self._key,
            {
                "tid": state.tenant_id,
                "uid": state.user_id,
                "step": state.step,
                "tok": state.events_token,
                "exp": int(now) + TTL_SEC,
            },
        )

    def verify(self, token: str, *, step: Step, now: float) -> State:
        try:
            payload = verify(self._key, token)
        except TokenInvalidError as e:
            raise GitHubStateError("the state isn't one qbrix signed") from e
        if payload.get("step") != step:
            raise GitHubStateError(f"the state isn't for the {step} step")
        if not isinstance(payload.get("exp"), int) or payload["exp"] < now:
            raise GitHubStateError("the state expired; connect again")
        return State(
            tenant_id=payload["tid"],
            user_id=payload["uid"],
            step=step,
            events_token=payload["tok"],
        )
