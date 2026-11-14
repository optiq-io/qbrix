from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Final


class Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset()

StagedContext = list[dict[str, Any]] | None | Unset


@dataclass(frozen=True, slots=True)
class BriefEdit:
    purpose: str | None = None
    owner: str | None = None


@dataclass(frozen=True, slots=True)
class CycleEdit:
    options: list[dict[str, Any]] | None = None
    engine: str | None = None
    metric: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryEdit:
    audience: list[dict[str, Any]] | None = None
    rollout: int | None = None
    schedule: dict[str, Any] | None = None
    fallback: str | None = None

    @property
    def placing(self) -> bool:
        """whether it changes who the loop decides for, beside the fallback."""
        return any(
            value is not None for value in (self.audience, self.rollout, self.schedule)
        )


@dataclass(frozen=True, slots=True)
class Edits:
    """edits staged across a loop's tabs, applied together. context is UNSET
    when not staged, since None declares no context."""

    brief: BriefEdit | None = None
    cycle: CycleEdit | None = None
    delivery: DeliveryEdit | None = None
    context: StagedContext = UNSET

    @property
    def empty(self) -> bool:
        return (
            self.brief is None
            and self.cycle is None
            and self.delivery is None
            and self.context is UNSET
        )


@dataclass(frozen=True, slots=True)
class Edited:
    """what an apply did, or would do: one change per kind, each with the
    parts of the edits it carries, and the number of the cycle it started."""

    loop: dict[str, Any]
    changes: list[dict[str, Any]]
    cycle: int | None


class Checked(Exception):
    """unwinds a checked apply's transaction once it has run, so the check is
    the apply itself, with nothing kept."""

    def __init__(self, edited: Edited):
        super().__init__("checked")
        self.edited = edited
