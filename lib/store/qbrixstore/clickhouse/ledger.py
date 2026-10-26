from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerDecision:
    """a decision as the ledger holds it, with the metric terms it was opened
    under. ledger_ms is when it reached the queue in front of the ledger."""

    tenant_id: str
    loop_id: str
    cycle_id: str
    decision_id: str
    option_index: int
    unit: str
    metric_id: str
    metric_version: str
    metric_type: str
    opened_ms: int
    window_ms: int
    ledger_ms: int

    @property
    def closes_ms(self) -> int:
        return self.opened_ms + self.window_ms


@dataclass(frozen=True)
class LedgerOutcome:
    """one outcome for one decision. an event for several decisions is one
    outcome per decision."""

    tenant_id: str
    decision_id: str
    event_id: str
    value: float
    at_ms: int
    received_ms: int
    ledger_ms: int


@dataclass(frozen=True)
class OutcomeRef:
    """the decision an outcome names, enough to find it in the ledger."""

    tenant_id: str
    cycle_id: str
    decision_id: str
    opened_ms: int


@dataclass(frozen=True)
class SealedDecision:
    """a decision whose outcome is final. value is none when its metric has
    nothing to learn from no outcome."""

    tenant_id: str
    loop_id: str
    cycle_id: str
    decision_id: str
    option_index: int
    unit: str
    metric_id: str
    metric_version: str
    metric_type: str
    opened_ms: int
    sealed_ms: int
    sealed_by: str
    value: float | None
    outcomes: int


@dataclass(frozen=True)
class CycleSpan:
    """a cycle's decisions made in [since, until)."""

    cycle_id: str
    since_ms: int
    until_ms: int


@dataclass(frozen=True)
class DecisionBucket:
    """decisions one option got in one step of a series, each once."""

    bucket_ms: int
    option_index: int
    decisions: int


@dataclass(frozen=True)
class DecisionCount:
    """decisions one option of a cycle got in a span, each once, and of those
    that reached the ledger before complete up to, how many have sealed and
    how many are waiting."""

    cycle_id: str
    option_index: int
    decisions: int
    sealed: int
    waiting: int


@dataclass(frozen=True)
class SealedStats:
    """the sealed decisions with a value one option of a cycle got in a span:
    their count, the sum of their values and of their squares."""

    cycle_id: str
    option_index: int
    n: int
    total: float
    total_sq: float
