from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from datetime import timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixlog import get_logger
from qbrixstore.postgres.models import Alert

from proxysvc.core.actor import Actor
from proxysvc.mod.safety.repository import AlertRepository
from proxysvc.mod.webhook.repository import WebhookRepository

logger = get_logger(__name__)

CLEARED = "cleared"
RESUMED = "resumed"
RETIRED = "retired"

OPENED = "opened"
RECOVERED = "recovered"


class AlertService:
    """the only way an alert opens or ends, inside the caller's transaction,
    so whatever else that transaction writes lands with it or not at all,
    the notice for the workspace webhook included."""

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id
        self._alerts = AlertRepository(session, tenant_id)
        self._webhook = WebhookRepository(session, tenant_id)

    async def open(
        self,
        loop_id: str,
        signal: str,
        evidence: dict,
        *,
        cycle_id: str | None = None,
        at: datetime | None = None,
    ) -> Alert:
        """open an alert for the loop and signal, or return the one already
        open: a loop has at most one open alert per signal."""
        found = await self._alerts.open_for(loop_id, signal)
        if found is not None:
            return found
        alert = Alert(
            id=uuid4().hex,
            tenant_id=self._tenant_id,
            loop_id=loop_id,
            cycle_id=cycle_id,
            signal=signal,
            evidence=evidence,
            opened_at=at or datetime.now(timezone.utc),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(alert)
                await self._session.flush()
                await self._webhook.queue_notice(alert.id, OPENED, alert.opened_at)
        except IntegrityError:
            found = await self._alerts.open_for(loop_id, signal)
            if found is None:
                raise
            return found
        logger.info("opened %s alert on loop %s", signal, loop_id)
        return alert

    async def resolve(
        self,
        alert: Alert,
        resolution: str,
        actor: Actor,
        *,
        at: datetime | None = None,
    ) -> None:
        alert.resolved_at = at or datetime.now(timezone.utc)
        alert.resolution = resolution
        alert.resolved_kind = actor.kind
        alert.resolved_user_id = actor.user_id
        alert.clear_since = None
        await self._webhook.queue_notice(alert.id, RECOVERED, alert.resolved_at)
        await self._session.flush()
        logger.info(
            "resolved %s alert on loop %s: %s", alert.signal, alert.loop_id, resolution
        )

    async def resolve_loop(
        self,
        loop_id: str,
        resolution: str,
        actor: Actor,
        *,
        signals: Collection[str] | None = None,
    ) -> list[Alert]:
        """end the loop's open alerts, or only those of ``signals``."""
        found = list(await self._alerts.open_on([loop_id], signals))
        for alert in found:
            await self.resolve(alert, resolution, actor)
        return found
