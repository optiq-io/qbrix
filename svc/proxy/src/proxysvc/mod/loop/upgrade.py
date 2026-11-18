from __future__ import annotations

from sqlalchemy import select

from qbrixcore.engine import ENGINES
from qbrixcore.engine import EngineError
from qbrixcore.engine import EngineSpec
from qbrixlog import get_logger
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient

from proxysvc.core.error import LoopInvalidError
from proxysvc.mod.loop.minor import move_minor
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.serialize import cycle_record
from proxysvc.mod.loop.service import resolve_engine

logger = get_logger(__name__)

# a committed loop's cycle still seals its open decisions, and reopening returns to it
_RUNNING = ("live", "paused", "committed")


def _behind(cycle: Cycle) -> bool:
    """whether a cycle follows its major and runs another minor than the
    latest this install ships."""
    try:
        spec = EngineSpec.parse(cycle.engine)
        latest = str(ENGINES.get(spec).version)
    except EngineError:
        logger.warning(
            f"cycle {cycle.id} runs an engine this install doesn't ship: "
            f"{cycle.engine} {cycle.engine_version}"
        )
        return False
    return spec.minor is None and latest != cycle.engine_version


async def _move(
    redis: RedisClient, tenant_id: str, loop_id: str, cycle_id: str, recorded: str
) -> bool:
    async with get_session() as session:
        loop = await LoopRepository(session, tenant_id).get(loop_id)
        cycle = loop.cycles[-1] if loop is not None else None
        if cycle is None or cycle.id != cycle_id:
            return False
        if await move_minor(session, tenant_id, loop, cycle, recorded) is None:
            return False
        resolved = resolve_engine(cycle.engine, loop.metric, cycle.context_schema)
        record = cycle_record(tenant_id, loop, cycle, resolved)
        # written before the commit: a crash in between moves the cycle again on
        # the next start, and every minor of a major reads the same learning
        await redis.set_experiment(tenant_id, record["id"], record)
    return True


async def follow_minors(redis: RedisClient) -> int:
    """move every running cycle that follows its engine's major to the latest
    minor this install ships, keeping what it learned, with a change in its
    loop's history. replicas starting together move each cycle once: the
    move is a compare-and-set on the cycle's recorded version."""
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Loop.id, Loop.tenant_id, Cycle)
                .join(Cycle, Cycle.loop_id == Loop.id)
                .where(Loop.state.in_(_RUNNING), Cycle.ended_at.is_(None))
            )
        ).all()
    due = [
        (tenant_id, loop_id, cycle.id, cycle.engine_version)
        for loop_id, tenant_id, cycle in rows
        if _behind(cycle)
    ]
    moved = 0
    for tenant_id, loop_id, cycle_id, recorded in due:
        try:
            moved += await _move(redis, tenant_id, loop_id, cycle_id, recorded)
        except LoopInvalidError as e:
            logger.error(f"cycle {cycle_id} could not move to its latest minor: {e}")
    if moved:
        logger.info(f"moved {moved} cycles to their engine's latest minor")
    return moved
