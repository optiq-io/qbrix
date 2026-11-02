from __future__ import annotations

from dataclasses import dataclass

from qbrixstore.event.base import Event

FIRST_CALL = "loop.first_call"
FIRST_SEAL = "loop.first_seal"
LEADER_CHANGED = "loop.leader_changed"


@dataclass
class MilestoneEvent(Event):
    """something a loop reached that isn't anyone's change.

    event_id is deterministic, so writing one twice is one row. cycle_id is
    empty for a draft, which has no cycle yet. payload holds raw values, such
    as option indexes; names and sentences are made when it is read.
    """

    event_id: str
    kind: str
    tenant_id: str
    loop_id: str
    cycle_id: str
    payload: dict
    at_ms: int
