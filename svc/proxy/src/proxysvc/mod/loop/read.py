from __future__ import annotations

from collections.abc import Collection
from collections.abc import Sequence
from datetime import timezone

from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Mention
from qbrixstore.postgres.session import get_session

from proxysvc.core import cursor as pages
from proxysvc.mod.change.note import HISTORY_SHOW
from proxysvc.mod.change.note import HistoryShow
from proxysvc.mod.change.proposal import HAPPENED
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.serialize import history_entry
from proxysvc.mod.change.service import workspace_rows
from proxysvc.mod.github.mention import mention_entry
from proxysvc.mod.github.repository import MentionRepository
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.result import LoopResultService
from proxysvc.mod.loop.serialize import cycle_to_dict
from proxysvc.mod.loop.serialize import loop_to_dict
from proxysvc.mod.people import People
from proxysvc.mod.safety.entry import iso
from proxysvc.mod.safety.repository import AlertRepository


class LoopReadService:
    """loops as people, agents and the console read them: one loop, the list
    with each loop's latest change, open alerts and results, a loop's cycles
    and its history.

    every read is a fixed number of queries, whatever the page holds.
    """

    @staticmethod
    async def get_loop(tenant_id: str, ref: str) -> dict | None:
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            latest = await ChangeRepository(session, tenant_id).latest_for_each(
                "loop", [loop.id]
            )
            change = latest.get(loop.id)
            people = await People.load(
                session,
                tenant_id,
                [loop.owner_user_id] + ([change.actor_user_id] if change else []),
            )
            return {
                **loop_to_dict(loop, people),
                "latest_change": history_entry(change, people) if change else None,
            }

    @staticmethod
    async def keys(tenant_id: str) -> set[str]:
        async with get_session() as session:
            return await LoopRepository(session, tenant_id).keys_from("")

    @staticmethod
    async def list_loops(
        tenant_id: str,
        *,
        states: Sequence[str] = (),
        cursor: str | None = None,
        limit: int,
        results: LoopResultService,
    ) -> dict:
        before = pages.decode(cursor) if cursor else None
        async with get_session() as session:
            rows = await LoopRepository(session, tenant_id).page(
                states, before, limit + 1
            )
            loops, next_cursor = pages.page(rows, limit)
            latest = await ChangeRepository(session, tenant_id).latest_for_each(
                "loop", [loop.id for loop in loops]
            )
            alerts: dict[str, list[dict]] = {loop.id: [] for loop in loops}
            for alert in await AlertRepository(session, tenant_id).open_on(
                list(alerts)
            ):
                alerts[alert.loop_id].append(
                    {"signal": alert.signal, "opened_at": iso(alert.opened_at)}
                )
            people = await People.load(
                session,
                tenant_id,
                [loop.owner_user_id for loop in loops]
                + [change.actor_user_id for change in latest.values()],
            )
            items = [
                {
                    **loop_to_dict(loop, people),
                    "latest_change": (
                        history_entry(latest[loop.id], people)
                        if loop.id in latest
                        else None
                    ),
                    "alerts": alerts[loop.id],
                }
                for loop in loops
            ]
        summaries = await results.summaries(tenant_id, loops)
        return {
            "loops": [{**item, "results": summaries.get(item["id"])} for item in items],
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
        show: HistoryShow = "all",
        statuses: Collection[str] = HAPPENED,
        cursor: str | None = None,
        limit: int,
    ) -> dict | None:
        """a loop's history newest first: its changes and notes, and the pull
        requests and commits that mention it, in one page under one cursor.
        show narrows it to one of them."""
        before = pages.decode(cursor) if cursor else None
        read = HISTORY_SHOW[show]
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            rows: list[Change | Mention] = []
            if read.changes:
                rows += await ChangeRepository(session, tenant_id).page_for(
                    "loop",
                    loop.id,
                    before,
                    limit + 1,
                    kinds=read.kinds,
                    except_kinds=read.except_kinds,
                    statuses=statuses,
                )
            if read.mentions:
                rows += await MentionRepository(session, tenant_id).page_for(
                    loop.id, before, limit + 1
                )
            rows.sort(key=_position, reverse=True)
            rows, next_cursor = pages.page(rows[: limit + 1], limit, position=_position)
            changes = [row for row in rows if isinstance(row, Change)]
            rendered = await workspace_rows(
                session, tenant_id, [[change] for change in changes]
            )
            by_id = {entry["id"]: entry for entry in rendered}
            return {
                "loop": loop.key,
                "entries": [
                    (
                        {"type": "change", **by_id[row.id]}
                        if isinstance(row, Change)
                        else mention_entry(row)
                    )
                    for row in rows
                ],
                "next_cursor": next_cursor,
            }


def _position(row: Change | Mention) -> pages.Position:
    """where a row sits in history: a change when it was made, a mention when
    its pull request or commit last moved."""
    at = row.created_at if isinstance(row, Change) else row.at
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)), row.id
