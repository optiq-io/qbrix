from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixcore.engine import ENGINES
from qbrixcore.engine import EngineVersion
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop

from proxysvc.core.actor import Actor
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.loop.serialize import loop_to_dict
from proxysvc.mod.people import People
from proxysvc.mod.status import VERSION

ENGINE_MINOR = "engine.minor"


def _version(text: str) -> EngineVersion:
    major, minor = text.split(".")
    return EngineVersion(int(major), int(minor))


def minor_line(spec: str, recorded: str) -> str:
    """what moving a cycle from its recorded minor to the latest one changes,
    as its history says it: each newer minor's changes, none on a downgrade."""
    latest = ENGINES.get(spec)
    old = _version(recorded)
    line = f"{latest.title()} {recorded} → {latest.version} with qbrix {VERSION}"
    changes = [
        engine.changes
        for engine in ENGINES.versions(latest.name)
        if engine.version.major == old.major
        and old < engine.version <= latest.version
        and engine.changes
    ]
    return f"{line}: {'; '.join(changes)}" if changes else line


async def move_minor(
    session: AsyncSession,
    tenant_id: str,
    loop: Loop,
    cycle: Cycle,
    recorded: str,
) -> str | None:
    """move a cycle that follows its major from its recorded minor to the
    latest this install ships, with a change by qbrix in its loop's history.
    the move is a compare-and-set on the recorded version, so it happens
    once; none when another write moved it first. the caller rewrites the
    cycle's record."""
    latest = str(ENGINES.get(cycle.engine).version)
    moved = await session.execute(
        update(Cycle)
        .where(
            Cycle.id == cycle.id,
            Cycle.ended_at.is_(None),
            Cycle.engine_version == recorded,
        )
        .values(engine_version=latest)
        .execution_options(synchronize_session=False)
    )
    if moved.rowcount != 1:
        return None
    people = await People.load(session, tenant_id, [loop.owner_user_id])
    before = loop_to_dict(loop, people)
    after = {**before, "cycle": {**before["cycle"], "engine_version": latest}}
    await ChangeRepository(session, tenant_id).record(
        ENGINE_MINOR,
        "loop",
        loop.id,
        Actor.qbrix(),
        before=before,
        after=after,
        reason=minor_line(cycle.engine, recorded),
    )
    return latest
