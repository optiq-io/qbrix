from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass


@dataclass(frozen=True)
class MilestoneCycle:
    """which cycle a milestone belongs to."""

    tenant_id: str
    loop_id: str
    cycle_id: str

    def encode(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def decode(cls, value: str) -> MilestoneCycle:
        return cls(**json.loads(value))


@dataclass(frozen=True)
class MilestoneState:
    """how far a cycle's milestones have got: whether its first window sealed,
    the option in the lead and the check it took the lead at, the last check
    that saw the cycle, and the last leader named."""

    first_seal: bool = False
    candidate: int | None = None
    since_ms: int = 0
    seen_ms: int = 0
    leader: int | None = None

    def encode(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def decode(cls, value: str) -> MilestoneState:
        return cls(**json.loads(value))
