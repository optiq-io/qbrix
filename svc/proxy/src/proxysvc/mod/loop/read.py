from __future__ import annotations

from collections.abc import Sequence

from qbrixstore.postgres.session import get_session

from proxysvc.core import cursor as pages
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.serialize import history_entry
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.serialize import cycle_to_dict
from proxysvc.mod.loop.serialize import loop_to_dict
from proxysvc.mod.people import People


def _page(rows: list, limit: int) -> tuple[list, str | None]:
    """the page's rows, and the cursor to the next page when there is one."""
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    last = rows[-1]
    return rows, pages.encode(last.created_at, last.id)


class LoopReadService:
    """loops as people, agents and the console read them: one loop, the list
    with each loop's latest change, a loop's cycles and its history.

    every read is a fixed number of queries, whatever the page holds.
    """

    @staticmethod
    async def get_loop(tenant_id: str, ref: str) -> dict | None:
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            people = await People.load(session, tenant_id, [loop.owner_user_id])
            return loop_to_dict(loop, people)

    @staticmethod
    async def list_loops(
        tenant_id: str,
        *,
        states: Sequence[str] = (),
        cursor: str | None = None,
        limit: int,
    ) -> dict:
        before = pages.decode(cursor) if cursor else None
        async with get_session() as session:
            rows = await LoopRepository(session, tenant_id).page(
                states, before, limit + 1
            )
            loops, next_cursor = _page(rows, limit)
            latest = await ChangeRepository(session, tenant_id).latest_for_each(
                "loop", [loop.id for loop in loops]
            )
            people = await People.load(
                session,
                tenant_id,
                [loop.owner_user_id for loop in loops]
                + [change.actor_user_id for change in latest.values()],
            )
            return {
                "loops": [
                    {
                        **loop_to_dict(loop, people),
                        "latest_change": (
                            history_entry(latest[loop.id], people)
                            if loop.id in latest
                            else None
                        ),
                    }
                    for loop in loops
                ],
                "next_cursor": next_cursor,
            }

    @staticmethod
    async def list_cycles(tenant_id: str, ref: str) -> list[dict] | None:
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            return [
                {**cycle_to_dict(cycle), "options": cycle.options}
                for cycle in reversed(loop.cycles)
            ]

    @staticmethod
    async def loop_history(
        tenant_id: str,
        ref: str,
        *,
        cursor: str | None = None,
        limit: int,
    ) -> dict | None:
        before = pages.decode(cursor) if cursor else None
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            rows = await ChangeRepository(session, tenant_id).page_for(
                "loop", loop.id, before, limit + 1
            )
            changes, next_cursor = _page(rows, limit)
            people = await People.load(
                session, tenant_id, [change.actor_user_id for change in changes]
            )
            return {
                "changes": [history_entry(change, people) for change in changes],
                "next_cursor": next_cursor,
            }
