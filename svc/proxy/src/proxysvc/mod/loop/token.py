from __future__ import annotations

from dataclasses import dataclass

from proxysvc.core.error import TokenInvalidError
from proxysvc.mod.agent.token import sign
from proxysvc.mod.agent.token import verify


@dataclass(frozen=True)
class Decision:
    """a decision as its request_id carries it: what outcome needs to find it."""

    decision_id: str
    tenant_id: str
    loop_id: str
    cycle_id: str
    option_index: int
    unit: str
    metric_version: str
    timestamp_ms: int


class DecisionToken:
    """a decision's request_id: signed, so nothing is stored to look it up."""

    @staticmethod
    def encode(secret: bytes, decision: Decision) -> str:
        return sign(
            secret,
            {
                "did": decision.decision_id,
                "tnt_id": decision.tenant_id,
                "loop": decision.loop_id,
                "cyc": decision.cycle_id,
                "opt": decision.option_index,
                "unit": decision.unit,
                "mv": decision.metric_version,
                "ts": decision.timestamp_ms,
            },
        )

    @staticmethod
    def decode(secret: bytes, token: str, tenant_id: str) -> Decision:
        payload = verify(secret, token)
        if "did" not in payload:
            raise TokenInvalidError("not a decision's request_id")
        if payload["tnt_id"] != tenant_id:
            raise TokenInvalidError("token was not issued to this workspace")
        return Decision(
            decision_id=payload["did"],
            tenant_id=payload["tnt_id"],
            loop_id=payload["loop"],
            cycle_id=payload["cyc"],
            option_index=payload["opt"],
            unit=payload["unit"],
            metric_version=payload["mv"],
            timestamp_ms=payload["ts"],
        )
