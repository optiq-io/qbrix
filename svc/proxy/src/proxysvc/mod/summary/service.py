from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.session import get_session

from proxysvc.core.error import SummaryRangeError
from proxysvc.mod.change.entry import counts
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.result import LoopResultService
from proxysvc.mod.milestone.service import MilestoneService
from proxysvc.mod.people import People
from proxysvc.mod.summary.entry import ALERT_KINDS
from proxysvc.mod.summary.entry import alerts
from proxysvc.mod.summary.entry import by_who

WEEK = timedelta(days=7)
REACH = timedelta(days=30)
OLD_DRAFT = timedelta(days=7)
SHOWN = ("live", "paused", "committed")
MILESTONES_MAX = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def _share_now(loop: Loop, summary: dict | None, now: datetime) -> dict | None:
    if summary is None:
        return None
    cycle = loop.cycles[-1]
    return {
        "at": now.isoformat(),
        "cycle": cycle.number,
        "options": [
            {**item, "name": option["name"]}
            for option, item in zip(cycle.options, summary["share"])
        ],
    }


class SummaryService:
    """the workspace since a moment, as facts: for each loop that is live,
    paused or committed, its share then and now, lift, safety pauses and
    their recoveries, milestones and changes by who; the drafts; and the
    workspace's change counts. nothing ranks, judges or words them.

    every source is read once for all loops, whatever their number.
    """

    def __init__(
        self,
        results: LoopResultService,
        milestones: MilestoneService,
        *,
        clock: Callable[[], datetime] = _now,
    ):
        self._results = results
        self._milestones = milestones
        self._clock = clock

    def _since(self, since: datetime | None, now: datetime) -> datetime:
        if since is None:
            return now - WEEK
        since = _aware(since)
        if since > now:
            raise SummaryRangeError(
                f"since {since.isoformat()} is in the future; pass a time before "
                f"now, or leave it out for the last {WEEK.days} days"
            )
        earliest = now - REACH
        if since < earliest:
            raise SummaryRangeError(
                f"since reaches back {REACH.days} days at most; pass a time on or "
                f"after {earliest.isoformat()}, or leave it out for the last "
                f"{WEEK.days} days"
            )
        return since

    async def week(self, tenant_id: str, since: datetime | None = None) -> dict:
        now = self._clock()
        since = self._since(since, now)
        async with get_session() as session:
            found = await LoopRepository(session, tenant_id).with_states(
                (*SHOWN, "draft")
            )
            loops = [loop for loop in found if loop.state in SHOWN]
            drafts = [loop for loop in found if loop.state == "draft"]
            ids = [loop.id for loop in loops]
            repo = ChangeRepository(session, tenant_id)
            changes = await repo.in_range("loop", ids, since)
            at_since = await repo.latest_for_each(
                "loop", ids, kinds=ALERT_KINDS, before=since
            )
            rows = await repo.count_workspace(since)
            people = await People.load(
                session, tenant_id, [change.actor_user_id for change in changes]
            )

        summaries, then, reached = await asyncio.gather(
            self._results.summaries(tenant_id, loops),
            self._results.shares_at(tenant_id, loops, _ms(since)),
            self._milestones.list_milestones(
                tenant_id, since=since, limit=MILESTONES_MAX
            ),
        )

        per_loop: dict[str, list] = {loop_id: [] for loop_id in ids}
        for change in changes:
            per_loop[change.target_id].append(change)
        milestones: dict[str, list] = {loop_id: [] for loop_id in ids}
        for milestone in reached["milestones"]:
            if milestone["loop"]["id"] in milestones:
                milestones[milestone["loop"]["id"]].append(milestone)

        old = now - OLD_DRAFT
        return {
            "since": since.isoformat(),
            "until": now.isoformat(),
            "loops": [
                {
                    "id": loop.id,
                    "key": loop.key,
                    "name": loop.name,
                    "state": loop.state,
                    "committed": loop.committed_key,
                    "metric": {
                        "id": loop.metric.id,
                        "name": loop.metric.name,
                        "type": loop.metric.type,
                    },
                    "share": {
                        "then": then.get(loop.id),
                        "now": _share_now(loop, summaries.get(loop.id), now),
                    },
                    "lift": (summaries.get(loop.id) or {}).get("lift"),
                    "early": (summaries.get(loop.id) or {}).get("early", False),
                    "alerts": alerts(at_since.get(loop.id), per_loop[loop.id], people),
                    "milestones": milestones[loop.id],
                    "changes": by_who(per_loop[loop.id][::-1], people),
                }
                for loop in loops
            ],
            "drafts": {
                "count": len(drafts),
                "older_than_7_days": [
                    {
                        "id": draft.id,
                        "key": draft.key,
                        "name": draft.name,
                        "created_at": _aware(draft.created_at).isoformat(),
                    }
                    for draft in drafts
                    if _aware(draft.created_at) < old
                ],
            },
            "changes": {"since": since.isoformat(), **counts(rows)},
        }
