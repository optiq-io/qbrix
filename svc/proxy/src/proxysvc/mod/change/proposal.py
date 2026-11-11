from __future__ import annotations

from dataclasses import dataclass

WAITING = "waiting"
DECLINED = "declined"
HAPPENED = ("applied", "undone")
STATUSES = ("applied", "undone", WAITING, DECLINED)


@dataclass(frozen=True, slots=True)
class Draft:
    """the change a write would record, had its actor not had to ask first."""

    kind: str
    target_type: str
    target_id: str
    before: dict | None
    after: dict | None
    learning: dict | None
    reason: str | None
    evidence: dict | None
    undoes_id: str | None


class Proposed(Exception):
    """raised by the change log in place of recording a change that must ask
    first. it unwinds the write's transaction, so the write's every check has
    run and nothing applied; whoever asked stores the draft as waiting."""

    def __init__(self, draft: Draft):
        super().__init__(f"{draft.kind} waits for approval")
        self.draft = draft


@dataclass(frozen=True, slots=True)
class Waiting:
    """a change stored as waiting for its person's answer, beside the value
    it would change as that value is now."""

    value: dict | None
    change: dict
