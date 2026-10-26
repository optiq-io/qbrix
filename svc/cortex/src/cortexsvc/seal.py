"""the rules that seal a decision and classify its outcomes, applied to what
the ledger holds.

everything here is decided by ledger time, when a row reached the queue in
front of the ledger, so the same ledger sealed over any split into slices
seals every decision once, at the same time, with the same value.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from typing import Iterable

from qbrixcore.engine import MetricType
from qbrixlog import get_logger
from qbrixstore.clickhouse.ledger import LedgerDecision
from qbrixstore.clickhouse.ledger import LedgerOutcome
from qbrixstore.clickhouse.ledger import SealedDecision
from qbrixstore.redis import OutcomeDisposition

logger = get_logger(__name__)

SEALED_BY_OUTCOME = "outcome"
SEALED_BY_WINDOW = "window"


@dataclass(frozen=True)
class Classified:
    """how one outcome ended, and the ledger time it is counted at."""

    tenant_id: str
    cycle_id: str
    disposition: OutcomeDisposition
    ledger_ms: int


@dataclass
class Slice:
    sealed: list[SealedDecision] = field(default_factory=list)
    classified: list[Classified] = field(default_factory=list)


def _order(outcome: LedgerOutcome) -> tuple:
    return outcome.ledger_ms, outcome.at_ms, outcome.event_id, outcome.value


def seal_slice(
    decisions: Iterable[LedgerDecision],
    outcomes: Iterable[LedgerOutcome],
    start_ms: int,
    end_ms: int,
) -> Slice:
    """the decisions that seal in [start, end) and the outcomes counted in it.

    an outcome is in the window when its event time and its ledger time are
    both at or before the window closes. a conversion seals at its first such
    outcome; everything else seals when its window closes. an outcome is
    counted at the later of its own and its decision's ledger time, since it
    can only be judged once both are in the ledger.
    """
    by_decision: dict[str, list[LedgerOutcome]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.ledger_ms < end_ms:
            by_decision[outcome.decision_id].append(outcome)

    result = Slice()
    seen: set[str] = set()
    for decision in decisions:
        if decision.decision_id in seen:
            continue
        seen.add(decision.decision_id)
        try:
            metric_type = MetricType(decision.metric_type)
        except ValueError:
            logger.error(
                "decision %s has unknown metric type %r, not sealing it",
                decision.decision_id,
                decision.metric_type,
            )
            continue
        _seal_one(
            decision,
            metric_type,
            sorted(by_decision.get(decision.decision_id, ()), key=_order),
            start_ms,
            end_ms,
            result,
        )

    result.sealed.sort(key=lambda sealed: (sealed.sealed_ms, sealed.decision_id))
    return result


def _seal_one(
    decision: LedgerDecision,
    metric_type: MetricType,
    outcomes: list[LedgerOutcome],
    start_ms: int,
    end_ms: int,
    result: Slice,
) -> None:
    closes = decision.closes_ms

    def counted_at(outcome: LedgerOutcome) -> int:
        return max(outcome.ledger_ms, decision.ledger_ms)

    seen_events: set[str] = set()
    repeats: set[int] = set()
    for index, outcome in enumerate(outcomes):
        if outcome.event_id in seen_events:
            repeats.add(index)
        seen_events.add(outcome.event_id)

    in_window = [
        outcome
        for index, outcome in enumerate(outcomes)
        if index not in repeats
        and outcome.at_ms <= closes
        and outcome.ledger_ms <= closes
    ]

    first = in_window[0] if metric_type is MetricType.CONVERSION and in_window else None
    if first is not None:
        sealed_ms, sealed_by = counted_at(first), SEALED_BY_OUTCOME
        value, learned = first.value, [first]
    else:
        sealed_ms, sealed_by = max(closes, decision.ledger_ms), SEALED_BY_WINDOW
        learned = in_window
        if metric_type is MetricType.CONVERSION:
            value = 0.0
        elif metric_type is MetricType.SCORE:
            last = max(
                in_window,
                key=lambda outcome: (outcome.at_ms, *_order(outcome)),
                default=None,
            )
            value = last.value if last is not None else None
        else:
            value = float(sum(outcome.value for outcome in in_window))

    if start_ms <= sealed_ms < end_ms:
        result.sealed.append(
            SealedDecision(
                tenant_id=decision.tenant_id,
                loop_id=decision.loop_id,
                cycle_id=decision.cycle_id,
                decision_id=decision.decision_id,
                option_index=decision.option_index,
                unit=decision.unit,
                metric_id=decision.metric_id,
                metric_version=decision.metric_version,
                metric_type=decision.metric_type,
                opened_ms=decision.opened_ms,
                sealed_ms=sealed_ms,
                sealed_by=sealed_by,
                value=value,
                outcomes=len(learned),
            )
        )

    learned_ids = {id(outcome) for outcome in learned}
    for index, outcome in enumerate(outcomes):
        at = counted_at(outcome)
        if not start_ms <= at < end_ms:
            continue
        if index in repeats:
            disposition = OutcomeDisposition.DUPLICATE
        elif outcome.at_ms > closes:
            disposition = OutcomeDisposition.LATE
        elif id(outcome) in learned_ids:
            disposition = OutcomeDisposition.LEARNED
        elif first is not None:
            disposition = OutcomeDisposition.DUPLICATE
        else:
            disposition = OutcomeDisposition.LATE
        result.classified.append(
            Classified(decision.tenant_id, decision.cycle_id, disposition, at)
        )
