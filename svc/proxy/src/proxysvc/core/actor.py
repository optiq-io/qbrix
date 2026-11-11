from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from qbrixlog.context import generate_request_id

ActorKind = Literal["member", "connection", "qbrix"]

_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


@dataclass(frozen=True, slots=True)
class Approval:
    """a person's yes to a change that waited: the write it re-runs turns the
    waiting change into the applied one."""

    change_id: str
    user_id: str
    where: str


@dataclass(frozen=True, slots=True)
class Actor:
    """who makes a write, and through what.

    a connection always acts for a member, so user_id is set for every kind
    but qbrix. request_id is the transport request's id, not a selection's.
    level is a connection's autonomy for the kind it is making: at "ask", the
    write is recorded as waiting and applies nothing, unless it carries the
    approval.
    """

    kind: ActorKind
    user_id: str
    connection_id: str = ""
    client_name: str = ""
    api_key_id: str = ""
    request_id: str = ""
    level: str = ""
    approval: Approval | None = None

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

    @classmethod
    def connection(
        cls,
        user_id: str,
        *,
        connection_id: str,
        client_name: str,
        request_id: str = "",
    ) -> Actor:
        return cls(
            kind="connection",
            user_id=user_id,
            connection_id=connection_id,
            client_name=client_name,
            request_id=request_id,
        )

    @classmethod
    def qbrix(cls) -> Actor:
        return cls(kind="qbrix", user_id="qbrix")


def inbound_request_id(value: str | None) -> str:
    """the caller's request id when it is safe to log and store, else a new one."""
    if value and _REQUEST_ID.fullmatch(value):
        return value
    return generate_request_id()
