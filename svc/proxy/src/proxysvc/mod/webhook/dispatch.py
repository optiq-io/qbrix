from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update

from qbrixlog import get_logger
from qbrixstore.postgres.models import Alert
from qbrixstore.postgres.models import AlertNotice
from qbrixstore.postgres.models import WebhookDelivery
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient
from qbrixruntime.task import drain

from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.milestone.entry import LoopName
from proxysvc.mod.people import People
from proxysvc.mod.safety.entry import alert_entry
from proxysvc.mod.webhook.repository import WebhookRepository
from proxysvc.mod.webhook.sender import Attempt
from proxysvc.mod.webhook.service import ALERT
from proxysvc.mod.webhook.service import DELIVERED
from proxysvc.mod.webhook.service import FAILING
from proxysvc.mod.webhook.service import GAVE_UP
from proxysvc.mod.webhook.service import PENDING
from proxysvc.mod.webhook.service import WebhookService
from proxysvc.mod.webhook.text import Notice
from proxysvc.mod.webhook.text import message

logger = get_logger(__name__)

LEASE = "webhook"
LEASE_MS = 60_000
GATHER = timedelta(seconds=60)
RETRY_AFTER = (
    timedelta(seconds=30),
    timedelta(minutes=1),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
)
RETRY_EVERY = timedelta(hours=1)
GIVE_UP_AFTER = timedelta(hours=24)
UNFINISHED = (PENDING, FAILING)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class _Raced(Exception):
    pass


def after(
    attempt: Attempt, tried: int, first: datetime, now: datetime
) -> tuple[str, datetime | None]:
    """the delivery's status after a try, and when to try next: retries back
    off to hourly and stop a day after the first try."""
    if attempt.ok:
        return DELIVERED, None
    deadline = first + GIVE_UP_AFTER
    if now >= deadline:
        return GAVE_UP, None
    wait = RETRY_AFTER[tried] if tried < len(RETRY_AFTER) else RETRY_EVERY
    return FAILING, min(now + wait, deadline)


class WebhookDispatch:
    """sends alerts to each workspace's webhook.

    every replica runs one, and the replica holding the lease sends. a pass
    first gathers a workspace's notices into one delivery once the oldest has
    waited a minute, so alerts that open together arrive as one message, then
    tries each workspace's oldest unfinished delivery: a failing one holds the
    later ones behind it, so an ending never arrives before its opening. the
    result is written after the send, so a holder that dies mid-send leaves
    the delivery to be sent again under the same id.
    """

    def __init__(
        self,
        redis: RedisClient,
        webhooks: WebhookService,
        *,
        console_origin: str,
        interval_sec: float,
        clock: Callable[[], datetime] = _now,
    ):
        self._redis = redis
        self._webhooks = webhooks
        self._console_origin = console_origin
        self._interval_sec = interval_sec
        self._clock = clock
        self._holder = uuid4().hex
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="webhook-dispatch")

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
                logger.error("webhook pass failed: %s", e)
            await asyncio.sleep(self._interval_sec)

    async def _hold(self) -> bool:
        return await self._redis.acquire_lease(LEASE, self._holder, LEASE_MS)

    async def run_once(self, now: datetime | None = None) -> None:
        if not await self._hold():
            return
        now = now or self._clock()
        for tenant_id in await self._gathered(now):
            try:
                await self._compose(tenant_id, now)
            except _Raced:
                logger.info("notices of tenant %s were already claimed", tenant_id)
            except Exception:
                logger.error(
                    "composing alerts for tenant %s failed", tenant_id, exc_info=True
                )
        for tenant_id, delivery_id in await self._due(now):
            if not await self._hold():
                return
            try:
                await self._deliver(tenant_id, delivery_id, now)
            except Exception:
                logger.error(
                    "delivering %s of tenant %s failed",
                    delivery_id,
                    tenant_id,
                    exc_info=True,
                )

    async def _gathered(self, now: datetime) -> list[str]:
        """the workspaces whose oldest unsent notice has waited long enough."""
        stmt = (
            select(AlertNotice.tenant_id)
            .where(AlertNotice.delivery_id.is_(None))
            .group_by(AlertNotice.tenant_id)
            .having(func.min(AlertNotice.created_at) <= now - GATHER)
        )
        async with get_session() as session:
            return list((await session.execute(stmt)).scalars())

    async def _compose(self, tenant_id: str, now: datetime) -> None:
        async with get_session() as session:
            stmt = (
                select(AlertNotice)
                .where(
                    AlertNotice.tenant_id == tenant_id,
                    AlertNotice.delivery_id.is_(None),
                )
                .order_by(AlertNotice.created_at, AlertNotice.id)
            )
            notices = list((await session.execute(stmt)).scalars())
            if not notices:
                return
            alerts = {
                a.id: a
                for a in (
                    await session.execute(
                        select(Alert).where(Alert.id.in_({n.alert_id for n in notices}))
                    )
                ).scalars()
            }
            names = await LoopRepository(session, tenant_id).names(
                {a.loop_id for a in alerts.values()}
            )
            people = await People.load(
                session,
                tenant_id,
                (
                    a.resolved_user_id
                    for a in alerts.values()
                    if a.resolved_kind != "qbrix"
                ),
            )
            repo = WebhookRepository(session, tenant_id)
            told = [
                Notice(
                    alert_entry(alerts[n.alert_id], LoopName(*names[loop_id]), people),
                    n.event,
                )
                for n in notices
                if (loop_id := alerts[n.alert_id].loop_id) in names
            ]
            if not told:
                return
            body = message(told, await repo.workspace_name(), self._console_origin)
            delivery_id = uuid4().hex
            repo.add_delivery(
                WebhookDelivery(
                    id=delivery_id,
                    tenant_id=tenant_id,
                    kind=ALERT,
                    summary=body["text"],
                    payload=body,
                    status=PENDING,
                    attempts=0,
                    results=[],
                    next_attempt_at=now,
                    created_at=now,
                )
            )
            await session.flush()
            ids = [n.id for n in notices]
            claimed = await session.execute(
                update(AlertNotice)
                .where(AlertNotice.id.in_(ids), AlertNotice.delivery_id.is_(None))
                .values(delivery_id=delivery_id)
            )
            if claimed.rowcount != len(ids):
                raise _Raced()
        logger.info(
            "gathered %d alert notices of tenant %s into one delivery",
            len(told),
            tenant_id,
        )

    async def _due(self, now: datetime) -> list[tuple[str, str]]:
        """each workspace's oldest unfinished delivery, when its try is due."""
        stmt = (
            select(
                WebhookDelivery.tenant_id,
                WebhookDelivery.id,
                WebhookDelivery.next_attempt_at,
            )
            .where(WebhookDelivery.status.in_(UNFINISHED))
            .order_by(
                WebhookDelivery.tenant_id,
                WebhookDelivery.created_at,
                WebhookDelivery.id,
            )
        )
        async with get_session() as session:
            rows = (await session.execute(stmt)).all()
        heads: dict[str, tuple[str, datetime | None]] = {}
        for row in rows:
            heads.setdefault(row.tenant_id, (row.id, row.next_attempt_at))
        return [
            (tenant_id, delivery_id)
            for tenant_id, (delivery_id, at) in heads.items()
            if at is None or _utc(at) <= now
        ]

    async def _deliver(self, tenant_id: str, delivery_id: str, now: datetime) -> None:
        async with get_session() as session:
            webhook = await WebhookRepository(session, tenant_id).get()
            delivery = await session.get(WebhookDelivery, delivery_id)
            if delivery is None or delivery.status not in UNFINISHED:
                return
            if webhook is None:
                await session.delete(delivery)
                return
        tried = delivery.attempts
        first = _utc(delivery.first_attempt_at) if delivery.first_attempt_at else now
        body = {**delivery.payload, "sent_at": now.isoformat()}

        attempt = await self._webhooks.attempt(webhook, delivery_id, body, at=now)

        status, next_at = after(attempt, tried, first, now)
        async with get_session() as session:
            written = await session.execute(
                update(WebhookDelivery)
                .where(
                    WebhookDelivery.id == delivery_id,
                    WebhookDelivery.attempts == tried,
                )
                .values(
                    status=status,
                    attempts=tried + 1,
                    results=[*delivery.results, attempt.to_dict()],
                    payload=body,
                    last_status_code=attempt.status_code,
                    last_error=attempt.error,
                    first_attempt_at=first,
                    next_attempt_at=next_at,
                    delivered_at=now if attempt.ok else None,
                )
            )
        if written.rowcount == 0:
            logger.warning("delivery %s changed during its send", delivery_id)
            return
        log = logger.info if attempt.ok else logger.warning
        log(
            "webhook delivery %s of tenant %s: %s",
            delivery_id,
            tenant_id,
            status if attempt.ok else f"{status} ({attempt.error})",
        )
