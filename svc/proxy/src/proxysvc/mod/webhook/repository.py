from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import Webhook
from qbrixstore.postgres.models import WebhookDelivery


class WebhookRepository:

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def get(self) -> Webhook | None:
        stmt = select(Webhook).where(Webhook.tenant_id == self._tenant_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def exists(self) -> bool:
        stmt = select(Webhook.id).where(Webhook.tenant_id == self._tenant_id)
        return (await self._session.execute(stmt)).first() is not None

    def add(self, webhook: Webhook) -> None:
        self._session.add(webhook)

    async def delete(self) -> bool:
        """remove the webhook and every delivery it made."""
        await self._session.execute(
            delete(WebhookDelivery).where(WebhookDelivery.tenant_id == self._tenant_id)
        )
        result = await self._session.execute(
            delete(Webhook).where(Webhook.tenant_id == self._tenant_id)
        )
        return result.rowcount > 0

    async def recent_deliveries(self, limit: int) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.tenant_id == self._tenant_id)
            .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars())

    def add_delivery(self, delivery: WebhookDelivery) -> None:
        self._session.add(delivery)

    async def workspace_name(self) -> str:
        stmt = select(Tenant.name).where(Tenant.id == self._tenant_id)
        return (await self._session.execute(stmt)).scalar_one()
