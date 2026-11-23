"""how an event sent with only a unit finds the decisions it credits.

in each loop that improves the event's metric, the event credits the unit's
most recent decision that was open when it happened. a decision is a
candidate only if it reached the ledger before the event was judged, one race
after the event did, so the same ledger matches the same way on every pass.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from typing import Iterable

from qbrixstore.clickhouse.ledger import LedgerDecision
from qbrixstore.clickhouse.ledger import UnitEvent
from qbrixstore.clickhouse.ledger import UnitMatch


@dataclass
class Attribution:
    matches: list[UnitMatch] = field(default_factory=list)
    unattributed: dict[tuple[str, str], int] = field(default_factory=dict)


def match_units(
    events: Iterable[UnitEvent],
    decisions: Iterable[LedgerDecision],
    race_ms: int,
) -> Attribution:
    candidates: dict[tuple[str, str, str], list[LedgerDecision]] = defaultdict(list)
    for decision in decisions:
        candidates[(decision.tenant_id, decision.unit, decision.metric_id)].append(
            decision
        )

    result = Attribution()
    for event in events:
        judged_ms = event.ledger_ms + race_ms
        latest: dict[str, LedgerDecision] = {}
        for decision in candidates[(event.tenant_id, event.unit, event.metric_id)]:
            if not decision.opened_ms <= event.at_ms <= decision.closes_ms:
                continue
            if decision.ledger_ms >= judged_ms:
                continue
            held = latest.get(decision.loop_id)
            if held is None or (decision.opened_ms, decision.decision_id) > (
                held.opened_ms,
                held.decision_id,
            ):
                latest[decision.loop_id] = decision

        if not latest:
            key = (event.tenant_id, event.metric_id)
            result.unattributed[key] = result.unattributed.get(key, 0) + 1
            continue
        for decision in sorted(latest.values(), key=lambda d: d.loop_id):
            result.matches.append(
                UnitMatch(
                    tenant_id=event.tenant_id,
                    loop_id=decision.loop_id,
                    cycle_id=decision.cycle_id,
                    decision_id=decision.decision_id,
                    option_index=decision.option_index,
                    opened_ms=decision.opened_ms,
                    metric_id=event.metric_id,
                    event_id=event.event_id,
                    value=event.value,
                    at_ms=event.at_ms,
                    received_ms=event.received_ms,
                    ledger_ms=judged_ms,
                )
            )
    return result
