from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from uuid import uuid4

from qbrixlog import get_logger
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import DECISION_ERROR_WINDOW_MINUTES
from qbrixruntime.task import drain

from proxysvc.core.actor import Actor
from proxysvc.core.error import LoopStateError
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.service import LoopService
from proxysvc.mod.safety.rule import evidence
from proxysvc.mod.safety.rule import unhealthy

logger = get_logger(__name__)

LEASE = "safety"
LEASE_MS = 60_000
PAUSE_REASON = "decision errors"


def _first_minute(live_since: datetime | None) -> int:
    if live_since is None:
        return 0
    if live_since.tzinfo is None:
        live_since = live_since.replace(tzinfo=timezone.utc)
    return math.ceil(live_since.timestamp() / 60)


class SafetyWatch:
    """pauses a live loop when qbrix fails too many of its decisions.

    every replica runs one, and the replica holding the lease evaluates: a
    pass reads only the cycles that had an error in the window, so a quiet
    install costs one read. the window never reaches back before the loop
    went live, so errors from before a resume never pause it again. the
    watch never resumes a loop; a person does.
    """

    def __init__(self, redis: RedisClient, loops: LoopService, *, interval_sec: float):
        self._redis = redis
        self._loops = loops
        self._interval_sec = interval_sec
        self._holder = uuid4().hex
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="safety-watch")

    async def stop(self) -> None:
        if self._task:
            await drain(self._task)
            self._task = None
            await self._redis.release_lease(LEASE, self._holder)

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as e:
                logger.error("safety pass failed: %s", e)
            await asyncio.sleep(self._interval_sec)

    async def run_once(self, now: float | None = None) -> None:
        if not await self._redis.acquire_lease(LEASE, self._holder, LEASE_MS):
            return
        now = time.time() if now is None else now
        now_minute = int(now) // 60
        erroring = await self._redis.erroring(
            DECISION_ERROR_WINDOW_MINUTES, now_minute=now_minute
        )
        if not erroring:
            return

        by_tenant: dict[str, list[str]] = defaultdict(list)
        for tenant_id, cycle_id in erroring:
            by_tenant[tenant_id].append(cycle_id)
        async with get_session() as session:
            live = {
                tenant_id: await LoopRepository(session, tenant_id).live_cycles(ids)
                for tenant_id, ids in by_tenant.items()
            }

        oldest = now_minute - DECISION_ERROR_WINDOW_MINUTES + 1
        for tenant_id, loops in live.items():
            for loop, cycle_id in loops:
                first = max(oldest, _first_minute(loop.live_since))
                if first > now_minute:
                    continue
                health = await self._redis.select_health(
                    tenant_id, cycle_id, now_minute - first + 1, now_minute=now_minute
                )
                if unhealthy(health):
                    await self._pause(tenant_id, loop.id, evidence(health, first, now))

    async def _pause(self, tenant_id: str, loop_id: str, found: dict) -> None:
        try:
            await self._loops.pause_loop(
                tenant_id,
                loop_id,
                actor=Actor.qbrix(),
                reason=PAUSE_REASON,
                evidence=found,
            )
        except LoopStateError:
            logger.info("loop %s of tenant %s already moved", loop_id, tenant_id)
            return
        logger.warning(
            "paused loop %s of tenant %s: %.1f%% of %d calls failed (%s)",
            loop_id,
            tenant_id,
            found["rate"] * 100,
            found["calls"],
            ", ".join(f"{r} {n}" for r, n in sorted(found["reasons"].items())),
        )
