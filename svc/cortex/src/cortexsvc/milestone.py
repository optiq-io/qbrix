from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import replace

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.ledger import TrailingCount
from qbrixstore.event import MilestoneEvent
from qbrixstore.event.milestone import FIRST_SEAL
from qbrixstore.event.milestone import LEADER_CHANGED
from qbrixstore.redis import MilestoneCycle
from qbrixstore.redis import MilestoneState
from qbrixstore.redis.client import RedisClient

CHECK_MS = 5 * 60 * 1000
HOLD_MS = 60 * 60 * 1000
TRAILING_MS = 24 * 60 * 60 * 1000


def lead(
    state: MilestoneState, counts: dict[int, int], check_ms: int
) -> tuple[MilestoneState, dict | None]:
    """who leads a cycle at a check, and the change of leader to announce.

    an option is named only once it has led at every check for the hold. a tie
    keeps the option already leading, so two level options don't trade places.
    """
    most = max(counts.values())
    level = [option for option, count in counts.items() if count == most]
    candidate = state.candidate if state.candidate in level else min(level)
    continuous = candidate == state.candidate and check_ms - state.seen_ms <= CHECK_MS
    since_ms = state.since_ms if continuous else check_ms

    next_state = replace(
        state, candidate=candidate, since_ms=since_ms, seen_ms=check_ms
    )
    if candidate == state.leader or check_ms - since_ms < HOLD_MS:
        return next_state, None
    return (
        replace(next_state, leader=candidate),
        {"from": state.leader, "to": candidate},
    )


class MilestoneWatch:
    """turns ledger time into a cycle's milestones: its first window sealing,
    and a change of leader.

    a check stands on a boundary of ledger time and reads only what reached the
    ledger before it, so a pass catching up gives the same events as passes
    made live, and a pass repeated after a crash changes nothing.
    """

    def __init__(self, redis: RedisClient, clickhouse: ClickHouseClient):
        self._redis = redis
        self._clickhouse = clickhouse

    async def check(self, start_ms: int, end_ms: int) -> None:
        """run the check a slice of ledger time crossed, if it crossed one."""
        check_ms = end_ms // CHECK_MS * CHECK_MS
        if check_ms <= start_ms:
            return

        rows = await asyncio.to_thread(
            self._clickhouse.trailing_decisions, check_ms - TRAILING_MS, check_ms
        )
        cycles = _by_cycle(rows)
        states = await self._redis.milestone_states(list(cycles))
        for cycle, counted in cycles.items():
            if cycle not in states:
                closes_ms = min(r.first_ms for r in counted) + counted[0].window_ms
                await self._redis.expect_first_seal(cycle, closes_ms, MilestoneState())
                states[cycle] = MilestoneState()

        await self._first_seals(check_ms, states)
        for cycle, counted in cycles.items():
            state = states[cycle]
            if state.first_seal:
                await self._leader(cycle, state, counted, check_ms)

    async def _first_seals(
        self, check_ms: int, states: dict[MilestoneCycle, MilestoneState]
    ) -> None:
        for cycle, closes_ms in await self._redis.first_seals_due(check_ms):
            current = states.get(cycle)
            if current is None:
                found = await self._redis.milestone_states([cycle])
                current = found.get(cycle, MilestoneState())
            state = replace(current, first_seal=True)
            await self._redis.commit_milestone(
                cycle,
                state,
                _event(
                    FIRST_SEAL, f"first_seal:{cycle.cycle_id}", cycle, {}, closes_ms
                ),
            )
            states[cycle] = state

    async def _leader(
        self,
        cycle: MilestoneCycle,
        state: MilestoneState,
        counted: list[TrailingCount],
        check_ms: int,
    ) -> None:
        counts = {row.option_index: row.decisions for row in counted}
        next_state, change = lead(state, counts, check_ms)
        event = None
        if change is not None:
            event = _event(
                LEADER_CHANGED,
                f"leader:{cycle.cycle_id}:{next_state.since_ms}",
                cycle,
                change,
                check_ms,
            )
        await self._redis.commit_milestone(cycle, next_state, event)


def _by_cycle(
    rows: list[TrailingCount],
) -> dict[MilestoneCycle, list[TrailingCount]]:
    cycles: dict[MilestoneCycle, list[TrailingCount]] = defaultdict(list)
    for row in rows:
        cycles[MilestoneCycle(row.tenant_id, row.loop_id, row.cycle_id)].append(row)
    return cycles


def _event(
    kind: str, event_id: str, cycle: MilestoneCycle, payload: dict, at_ms: int
) -> MilestoneEvent:
    return MilestoneEvent(
        event_id=event_id,
        kind=kind,
        tenant_id=cycle.tenant_id,
        loop_id=cycle.loop_id,
        cycle_id=cycle.cycle_id,
        payload=payload,
        at_ms=at_ms,
    )
