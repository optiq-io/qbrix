from __future__ import annotations

import base64
import binascii
import hmac
import struct
from dataclasses import dataclass

from proxysvc.core.error import TokenInvalidError


@dataclass(frozen=True)
class Decision:
    """a decision as its request_id carries it: what outcome and track need
    to credit it. everything else about it is in the ledger."""

    decision_id: str
    loop_id: str
    cycle_id: str
    metric_id: str
    option_index: int
    timestamp_ms: int


class DecisionToken:
    """a decision's request_id: a fixed binary record, signed together with
    the workspace it was issued in, so nothing is stored to look it up and it
    stays short enough for the places code carries it.

    the first byte names the format. a selection token is json, so it starts
    with "{" and never reads as a decision.
    """

    KIND = 1
    _BODY = struct.Struct(">B16s16s16s16sH6s")
    _SIG_BYTES = 12
    _BYTES = _BODY.size + _SIG_BYTES

    @classmethod
    def encode(cls, secret: bytes, tenant_id: str, decision: Decision) -> str:
        body = cls._BODY.pack(
            cls.KIND,
            bytes.fromhex(decision.decision_id),
            bytes.fromhex(decision.loop_id),
            bytes.fromhex(decision.cycle_id),
            bytes.fromhex(decision.metric_id),
            decision.option_index,
            decision.timestamp_ms.to_bytes(6, "big"),
        )
        return cls._text(body + cls._sign(secret, tenant_id, body))

    @classmethod
    def decode(cls, secret: bytes, token: str, tenant_id: str) -> Decision:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        except (binascii.Error, ValueError) as e:
            raise TokenInvalidError(f"failed to decode request_id: {e}")
        if len(raw) != cls._BYTES or raw[0] != cls.KIND:
            raise TokenInvalidError("not a decision's request_id")
        # the decoder ignores stray characters and the last one's spare bits,
        # so only the one spelling of a request_id is accepted
        if cls._text(raw) != token:
            raise TokenInvalidError("not a decision's request_id")
        body, sig = raw[: cls._BODY.size], raw[cls._BODY.size :]
        if not hmac.compare_digest(sig, cls._sign(secret, tenant_id, body)):
            raise TokenInvalidError("request_id doesn't verify in this workspace")
        _, decision_id, loop_id, cycle_id, metric_id, option, ts = cls._BODY.unpack(
            body
        )
        return Decision(
            decision_id=decision_id.hex(),
            loop_id=loop_id.hex(),
            cycle_id=cycle_id.hex(),
            metric_id=metric_id.hex(),
            option_index=option,
            timestamp_ms=int.from_bytes(ts, "big"),
        )

    @staticmethod
    def _text(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @classmethod
    def _sign(cls, secret: bytes, tenant_id: str, body: bytes) -> bytes:
        message = tenant_id.encode() + body
        return hmac.new(secret, message, "sha256").digest()[: cls._SIG_BYTES]


DECISIONS_MAX = 50


class DecisionsToken:
    """the decisions a device was served, as one string code can carry to
    where the outcome happens: their request_ids joined by a dot, which
    base64url never contains. each is signed on its own, so the token needs
    no secret of its own and can't credit a decision the device never got."""

    SEPARATOR = "."

    @classmethod
    def join(cls, request_ids: list[str]) -> str:
        return cls.SEPARATOR.join(request_ids)

    @classmethod
    def split(cls, token: str) -> list[str]:
        entries = [entry for entry in token.split(cls.SEPARATOR) if entry]
        if not entries:
            raise TokenInvalidError("the decisions token holds no decision")
        if len(entries) > DECISIONS_MAX:
            raise TokenInvalidError(
                f"a decisions token holds at most {DECISIONS_MAX} decisions, "
                f"got {len(entries)}"
            )
        return list(dict.fromkeys(entries))
