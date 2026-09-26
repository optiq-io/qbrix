from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Invoice
from qbrixstore.postgres.models import StripeCustomer
from qbrixstore.postgres.models import Subscription


class StripeCustomerRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, tenant_id: str, stripe_customer_id: str) -> StripeCustomer:
        customer = StripeCustomer(
            tenant_id=tenant_id,
            stripe_customer_id=stripe_customer_id,
        )
        self._session.add(customer)
        await self._session.flush()
        return customer

    async def get_by_tenant_id(self, tenant_id: str) -> StripeCustomer | None:
        stmt = select(StripeCustomer).where(StripeCustomer.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_stripe_id(self, stripe_customer_id: str) -> StripeCustomer | None:
        stmt = select(StripeCustomer).where(
            StripeCustomer.stripe_customer_id == stripe_customer_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class SubscriptionRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        tenant_id: str,
        stripe_subscription_id: str,
        stripe_customer_id: str,
        plan_tier: str,
        current_period_start: datetime,
        current_period_end: datetime,
        status: str = "active",
    ) -> Subscription:
        subscription = Subscription(
            tenant_id=tenant_id,
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
            plan_tier=plan_tier,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            status=status,
        )
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def get_by_tenant_id(self, tenant_id: str) -> Subscription | None:
        stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_stripe_id(
        self, stripe_subscription_id: str
    ) -> Subscription | None:
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        stripe_subscription_id: str,
        status: str | None = None,
        cancel_at_period_end: bool | None = None,
        canceled_at: datetime | None = None,
        plan_tier: str | None = None,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
    ) -> None:
        values: dict = {}
        if status is not None:
            values["status"] = status
        if cancel_at_period_end is not None:
            values["cancel_at_period_end"] = cancel_at_period_end
        if canceled_at is not None:
            values["canceled_at"] = canceled_at
        if plan_tier is not None:
            values["plan_tier"] = plan_tier
        if current_period_start is not None:
            values["current_period_start"] = current_period_start
        if current_period_end is not None:
            values["current_period_end"] = current_period_end
        if not values:
            return
        stmt = (
            update(Subscription)
            .where(Subscription.stripe_subscription_id == stripe_subscription_id)
            .values(**values)
        )
        await self._session.execute(stmt)
        await self._session.flush()


class InvoiceRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        tenant_id: str,
        stripe_invoice_id: str,
        stripe_subscription_id: str,
        amount_due: int,
        amount_paid: int,
        currency: str,
        status: str,
        invoice_pdf: str | None = None,
    ) -> Invoice:
        invoice = Invoice(
            tenant_id=tenant_id,
            stripe_invoice_id=stripe_invoice_id,
            stripe_subscription_id=stripe_subscription_id,
            amount_due=amount_due,
            amount_paid=amount_paid,
            currency=currency,
            status=status,
            invoice_pdf=invoice_pdf,
        )
        self._session.add(invoice)
        await self._session.flush()
        return invoice

    async def list_by_tenant(self, tenant_id: str) -> list[Invoice]:
        stmt = (
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .order_by(Invoice.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
