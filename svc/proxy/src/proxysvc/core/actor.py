from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from qbrixlog.context import generate_request_id

ActorKind = Literal["member", "connection", "qbrix"]

_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


@dataclass(frozen=True, slots=True)
class Actor:
    """who makes a write, and through what.

    a connection always acts for a member, so user_id is set for every kind
    but qbrix. request_id is the transport request's id, not a selection's.
    """

    kind: ActorKind
    user_id: str
    connection_id: str = ""
    client_name: str = ""
    api_key_id: str = ""
    request_id: str = ""

    @classmethod
    def member(
        cls, user_id: str, *, api_key_id: str = "", request_id: str = ""
    ) -> Actor:
        return cls(
            kind="member",
            user_id=user_id,
            api_key_id=api_key_id,
            request_id=request_id,
        )


def inbound_request_id(value: str | None) -> str:
    """the caller's request id when it is safe to log and store, else a new one."""
    if value and _REQUEST_ID.fullmatch(value):
        return value
    return generate_request_id()
