from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import select

from qbrixlog import get_logger
from qbrixstore.postgres.models import Alert
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import MetricVersion
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import ALERT_CLEAR_HOLD_MINUTES
from qbrixstore.redis.health import Intake
from qbrixstore.redis.health import LoopSelectReason
from qbrixstore.redis.health import NOT_LEARNED_LEDGER_STALE_MS
from qbrixstore.redis.health import NOT_LEARNED_WINDOW_MINUTES
from qbrixstore.redis.health import OUTCOMES_STOPPED_ACTIVE_MINUTES
from qbrixstore.redis.health import OUTCOMES_STOPPED_MIN_DECISIONS
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import OutcomeHealth

from proxysvc.core.actor import Actor
from proxysvc.mod.safety.repository import AlertRepository
from proxysvc.mod.safety.rule import NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_NOT_LEARNED
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED
from proxysvc.mod.safety.rule import WARNINGS
from proxysvc.mod.safety.rule import not_learned_evidence
from proxysvc.mod.safety.rule import outcomes_not_learned
from proxysvc.mod.safety.rule import outcomes_stopped
from proxysvc.mod.safety.rule import stopped_evidence
from proxysvc.mod.safety.service import CLEARED
from proxysvc.mod.safety.service import AlertService

logger = get_logger(__name__)

WATCHED = ("live", "committed")
DECIDING = (LoopSelectReason.LIVE.value, LoopSelectReason.COMMITTED.value)
HOLD = timedelta(minutes=ALERT_CLEAR_HOLD_MINUTES)


@dataclass(frozen=True)
class _Watched:
    tenant_id: str
    loop_id: str
    cycle_id: str
    window_ms: int
    serving_since_ms: int


@dataclass(frozen=True)
class _Verdict:
    watched: _Watched
    signal: str
    unhealthy: bool
    evidence: dict


def _ms(at: datetime | None) -> int:
    if at is None:
        return 0
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return int(at.timestamp() * 1000)


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


class AlertPass:
    """opens and resolves the warnings on every loop that is deciding.

    outcomes stopped reads what the proxy received, so a stalled ledger never
    looks like a broken integration; outcomes not learned reads the sealer's
    counts, and waits while the ledger is behind, since they are stale. a
    warning ends once its signal has stayed clear for the hold, so a value
    sitting on its threshold can't flap. a loop that stops deciding keeps its
    open warnings, judged again when it serves again.
    """

    def __init__(self, redis: RedisClient):
        self._redis = redis

    async def run_once(self, now: float) -> None:
        now_ms = int(now * 1000)
        now_minute = int(now) // 60
        watched = await self._watched()
        if not watched:
            return
        cycles = [(w.tenant_id, w.cycle_id) for w in watched]
        intakes = await self._redis.intakes(cycles)
        deciding = await self._deciding(watched, intakes, now_minute)
        learnable = await self._learnable(watched, intakes, now_minute)

        verdicts: dict[str, list[_Verdict]] = defaultdict(list)
        for w in watched:
            intake = intakes[(w.tenant_id, w.cycle_id)]
            silent_since_ms = max(intake.last_outcome_ms or 0, w.serving_since_ms)
            verdicts[w.tenant_id].append(
                _Verdict(
                    w,
                    OUTCOMES_STOPPED,
                    outcomes_stopped(
                        intake,
                        window_ms=w.window_ms,
                        silent_since_ms=silent_since_ms,
                        now_ms=now_ms,
                        deciding=w.loop_id in deciding,
                    ),
                    stopped_evidence(
                        intake,
                        window_ms=w.window_ms,
                        silent_since_ms=silent_since_ms,
                        now_ms=now_ms,
                    ),
                )
            )
            if learnable is not None:
                health = learnable.get((w.tenant_id, w.cycle_id), OutcomeHealth())
                verdicts[w.tenant_id].append(
                    _Verdict(
                        w,
                        OUTCOMES_NOT_LEARNED,
                        outcomes_not_learned(health),
                        not_learned_evidence(health, now_ms),
                    )
                )
        await self._apply(verdicts, datetime.fromtimestamp(now, timezone.utc))

    async def _watched(self) -> list[_Watched]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(
                        Loop.tenant_id,
                        Loop.id,
                        Loop.live_since,
                        Cycle.id,
                        Cycle.started_at,
                        MetricVersion.window_sec,
                    )
                    .join(Cycle, Cycle.loop_id == Loop.id)
                    .join(MetricVersion, MetricVersion.id == Cycle.metric_version_id)
                    .where(Loop.state.in_(WATCHED), Cycle.ended_at.is_(None))
                )
            ).all()
        return [
            _Watched(
                tenant_id=tenant_id,
                loop_id=loop_id,
                cycle_id=cycle_id,
                window_ms=window_sec * 1000,
                serving_since_ms=max(_ms(live_since), _ms(started_at)),
            )
            for tenant_id, loop_id, live_since, cycle_id, started_at, window_sec in rows
        ]

    async def _deciding(
        self,
        watched: list[_Watched],
        intakes: dict[tuple[str, str], Intake],
        now_minute: int,
    ) -> set[str]:
        """the loops that made a decision in the last hour, asked only of the
        loops already silent by their count."""
        by_tenant: dict[str, list[str]] = defaultdict(list)
        for w in watched:
            intake = intakes[(w.tenant_id, w.cycle_id)]
            if intake.since_outcome >= OUTCOMES_STOPPED_MIN_DECISIONS:
                by_tenant[w.tenant_id].append(w.loop_id)
        deciding = set()
        for tenant_id, loop_ids in by_tenant.items():
            counts = await self._redis.loops_selects(
                tenant_id,
                loop_ids,
                OUTCOMES_STOPPED_ACTIVE_MINUTES,
                now_minute=now_minute,
            )
            deciding |= {
                loop_id
                for loop_id, by_reason in counts.items()
                if any(by_reason[reason] for reason in DECIDING)
            }
        return deciding

    async def _learnable(
        self,
        watched: list[_Watched],
        intakes: dict[tuple[str, str], Intake],
        now_minute: int,
    ) -> dict[tuple[str, str], OutcomeHealth] | None:
        """the last hour's outcomes of the cycles that received any, or None
        while the sealer's counts are stale."""
        progress = await self._redis.ledger_progress()
        if progress is None or progress.lag_ms > NOT_LEARNED_LEDGER_STALE_MS:
            return None
        cycles = [
            (w.tenant_id, w.cycle_id)
            for w in watched
            if intakes[(w.tenant_id, w.cycle_id)].outcomes
        ]
        return await self._redis.outcomes_health(
            cycles,
            NOT_LEARNED_WINDOW_MINUTES,
            [OutcomeDisposition.LEARNED, *NOT_LEARNED],
            now_minute=now_minute,
        )

    async def _apply(self, verdicts: dict[str, list[_Verdict]], now: datetime) -> None:
        async with get_session() as session:
            for tenant_id, found in verdicts.items():
                opened = {
                    (a.loop_id, a.signal): a
                    for a in await AlertRepository(session, tenant_id).open_on(
                        {v.watched.loop_id for v in found}, WARNINGS
                    )
                }
                alerts = AlertService(session, tenant_id)
                for verdict in found:
                    alert = opened.get((verdict.watched.loop_id, verdict.signal))
                    await _judge(alerts, alert, verdict, now)


async def _judge(
    alerts: AlertService, alert: Alert | None, verdict: _Verdict, now: datetime
) -> None:
    """open on an unhealthy signal, and resolve once it has stayed clear for
    the hold; a return during the hold starts the hold again."""
    w = verdict.watched
    if verdict.unhealthy:
        if alert is None:
            await alerts.open(
                w.loop_id, verdict.signal, verdict.evidence, cycle_id=w.cycle_id, at=now
            )
            logger.warning(
                "%s on loop %s of tenant %s", verdict.signal, w.loop_id, w.tenant_id
            )
        else:
            alert.clear_since = None
    elif alert is not None:
        if alert.clear_since is None:
            alert.clear_since = now
        elif now - _aware(alert.clear_since) >= HOLD:
            await alerts.resolve(alert, CLEARED, Actor.qbrix(), at=now)
