from __future__ import annotations

import asyncio
import stripe
from datetime import datetime, timedelta, timezone
from typing import Optional

from cachebox import TTLCache

from qbrixlog import get_logger
from qbrixstore.postgres.session import get_session
from proxysvc.config import settings
from proxysvc.mod.auth.repository import TenantRepository
from proxysvc.mod.auth.repository import UserRepository
from proxysvc.ee.plans import PLAN_LIMITS
from proxysvc.ee.billing.announcer import TenantAnnouncer
from proxysvc.ee.billing.repository import StripeCustomerRepository
from proxysvc.ee.billing.repository import SubscriptionRepository
from proxysvc.ee.billing.repository import InvoiceRepository
from proxysvc.ee.billing.models import (
    CheckoutSessionResponse,
    PortalSessionResponse,
    ChangePreviewResponse,
    SubscriptionResponse,
    InvoiceResponse,
    UsageResponse,
)

logger = get_logger(__name__)

_ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing", "past_due"}
_SELF_SERVE_TIERS = {"starter", "growth", "scale"}
_USAGE_CACHE_MAXSIZE = 1000
_USAGE_CACHE_TTL_SEC = 60


class ActiveSubscriptionExistsError(Exception):
    """raised when checkout is attempted for a tenant with an active subscription."""


class NoStripeCustomerError(Exception):
    """raised when a billing action needs a stripe customer the tenant lacks."""


class NoActiveSubscriptionError(Exception):
    """raised when a subscription action needs an active subscription the tenant lacks."""


class InvalidTierChangeError(Exception):
    """raised when a subscription tier change target is invalid."""


class UnknownPriceError(Exception):
    """raised when a stripe price id matches none of the configured tiers."""

    def __init__(self, price_id: str | None):
        self.price_id = price_id
        super().__init__(f"price id {price_id!r} matches no configured plan tier")


class BillingService:
    """core billing service for Stripe integration."""

    def __init__(self, *, announcer: TenantAnnouncer):
        stripe.api_key = settings.stripe_secret_key
        self._stripe = stripe
        self._usage_cache: TTLCache = TTLCache(
            maxsize=_USAGE_CACHE_MAXSIZE, ttl=_USAGE_CACHE_TTL_SEC
        )
        self._announcer = announcer

    def invalidate_tenant(self, tenant_id: str) -> None:
        """drop the tenant's cached usage view; its allowance is tier-derived."""
        self._usage_cache.pop(tenant_id, None)

    async def _announce_tier_change(self, tenant_id: str) -> None:
        """announce a committed tier change.

        callers must invoke this *after* the session block that wrote the tier
        has exited: get_session commits on exit, so publishing inside it would
        have subscribers re-read the pre-commit row and re-cache the old tier.

        the local eviction is unconditional and does not wait on the announcer,
        so this replica is correct even when the broadcast fails or there is
        none to make.
        """
        self.invalidate_tenant(tenant_id)
        await self._announcer.publish(tenant_id)

    async def create_checkout_session(
        self,
        tenant_id: str,
        user_id: str,
        price_id: str,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> CheckoutSessionResponse:
        """create a new Stripe checkout session for subscription."""
        # resolved before any work: an unmatched price would otherwise leave a
        # stripe customer behind and put the wrong tier's overage price on the
        # subscription for its lifetime
        tier = self._tier_for_base_price(price_id)
        if tier is None:
            raise UnknownPriceError(price_id)

        try:
            async with get_session() as session:
                subscription_repo = SubscriptionRepository(session)
                existing = await subscription_repo.get_by_tenant_id(tenant_id)
                if existing and existing.status in _ACTIVE_SUBSCRIPTION_STATUSES:
                    raise ActiveSubscriptionExistsError(
                        f"tenant {tenant_id} already has an active subscription"
                    )

                customer_repo = StripeCustomerRepository(session)
                customer = await customer_repo.get_by_tenant_id(tenant_id)

                if not customer:
                    user_repo = UserRepository(session)
                    user = await user_repo.get(user_id)

                    if not user:
                        raise ValueError(f"user {user_id} not found")

                    stripe_customer = await asyncio.to_thread(
                        self._stripe.Customer.create,
                        email=user.email,
                        name=user.name or user.email,
                        metadata={
                            "tenant_id": tenant_id,
                            "user_id": user_id,
                        },
                    )

                    customer = await customer_repo.create(
                        tenant_id=tenant_id,
                        stripe_customer_id=stripe_customer.id,
                    )
                    logger.info(
                        f"created Stripe customer {stripe_customer.id} for tenant {tenant_id}"
                    )

                # base licensed item; attach the tier's metered (overage) item
                # when configured
                line_items = [{"price": price_id, "quantity": 1}]
                metered_price_id = self._metered_price_for_tier(tier)
                if metered_price_id:
                    line_items.append({"price": metered_price_id})

                checkout_session = await asyncio.to_thread(
                    self._stripe.checkout.Session.create,
                    customer=customer.stripe_customer_id,
                    payment_method_types=["card"],
                    line_items=line_items,
                    mode="subscription",
                    success_url=success_url
                    or "http://localhost:3001/billing/success?session_id={CHECKOUT_SESSION_ID}",
                    cancel_url=cancel_url or "http://localhost:3001/billing/cancel",
                    metadata={
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "price_id": price_id,
                    },
                )

                logger.info(
                    f"created checkout session {checkout_session.id} for tenant {tenant_id}"
                )

                return CheckoutSessionResponse(
                    session_id=checkout_session.id,
                    url=checkout_session.url,
                )

        except stripe.StripeError as e:
            logger.error(f"stripe error creating checkout session: {e}")
            raise
        except Exception as e:
            logger.error(f"failed to create checkout session: {e}")
            raise

    async def create_portal_session(
        self,
        tenant_id: str,
        return_url: Optional[str] = None,
    ) -> PortalSessionResponse:
        """create a Stripe billing portal session for subscription management."""
        try:
            async with get_session() as session:
                customer_repo = StripeCustomerRepository(session)
                customer = await customer_repo.get_by_tenant_id(tenant_id)

                if not customer:
                    raise NoStripeCustomerError(
                        f"no stripe customer for tenant {tenant_id}"
                    )

            portal_session = await asyncio.to_thread(
                self._stripe.billing_portal.Session.create,
                customer=customer.stripe_customer_id,
                return_url=return_url
                or f"{settings.console_origin}/settings?tab=billing",
            )

            logger.info(f"created billing portal session for tenant {tenant_id}")

            return PortalSessionResponse(url=portal_session.url)

        except stripe.StripeError as e:
            logger.error(f"stripe error creating portal session: {e}")
            raise

    async def handle_webhook(self, payload: bytes, signature: str) -> bool:
        """process Stripe webhook events."""
        try:
            event = self._stripe.Webhook.construct_event(
                payload, signature, settings.stripe_webhook_secret
            )

            logger.info(f"received webhook event: {event['type']}")

            match event["type"]:
                case "checkout.session.completed":
                    await self._handle_checkout_completed(event["data"]["object"])
                case "invoice.paid":
                    await self._handle_invoice_paid(event["data"]["object"])
                case "invoice.payment_failed":
                    await self._handle_payment_failed(event["data"]["object"])
                case "customer.subscription.deleted":
                    await self._handle_subscription_deleted(event["data"]["object"])
                case "customer.subscription.updated":
                    await self._handle_subscription_updated(event["data"]["object"])
                case _:
                    logger.info(f"unhandled webhook event type: {event['type']}")

            return True

        except stripe.SignatureVerificationError as e:
            logger.error(f"webhook signature verification failed: {e}")
            return False
        except Exception as e:
            logger.error(f"failed to handle webhook: {e}")
            return False

    async def _handle_checkout_completed(self, session: dict) -> None:
        """handle successful checkout completion."""
        tenant_id = session.get("metadata", {}).get("tenant_id")
        price_id = session.get("metadata", {}).get("price_id")

        if not tenant_id:
            logger.error("no tenant_id in checkout session metadata")
            return

        async with get_session() as db_session:
            subscription_repo = SubscriptionRepository(db_session)
            tenant_repo = TenantRepository(db_session)

            existing = await subscription_repo.get_by_tenant_id(tenant_id)
            if existing:
                logger.info(
                    f"subscription already exists for tenant {tenant_id}, skipping"
                )
                return

            plan_tier = self._tier_for_base_price(price_id)
            if plan_tier is None:
                # write nothing. the handler short-circuits on an existing
                # subscription row, so provisioning a guessed tier now would
                # make every stripe retry a no-op and strand the tenant on it.
                # failing instead returns 400, and stripe retries for 3 days —
                # long enough to fix the price id and have it land correctly.
                logger.error(
                    f"checkout completed for tenant {tenant_id} with price_id "
                    f"{price_id!r}, which matches no configured plan tier — "
                    "refusing to provision"
                )
                raise UnknownPriceError(price_id)

            stripe_subscription = await asyncio.to_thread(
                self._stripe.Subscription.retrieve, session["subscription"]
            )

            period_start = datetime.fromtimestamp(
                stripe_subscription.start_date, tz=timezone.utc
            )
            # approximate period end as +30 days; webhook updates will correct it
            period_end = period_start + timedelta(days=30)

            await subscription_repo.create(
                tenant_id=tenant_id,
                stripe_subscription_id=stripe_subscription.id,
                stripe_customer_id=stripe_subscription.customer,
                plan_tier=plan_tier,
                current_period_start=period_start,
                current_period_end=period_end,
                status=stripe_subscription.status,
            )

            await tenant_repo.update_plan_tier(tenant_id, plan_tier)

            logger.info(f"provisioned {plan_tier} plan for tenant {tenant_id}")

        await self._announce_tier_change(tenant_id)

    async def _handle_invoice_paid(self, invoice: dict) -> None:
        """handle successful invoice payment."""
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        async with get_session() as db_session:
            subscription_repo = SubscriptionRepository(db_session)
            invoice_repo = InvoiceRepository(db_session)

            subscription = await subscription_repo.get_by_stripe_id(subscription_id)
            if not subscription:
                logger.warning(f"subscription {subscription_id} not found for invoice")
                return

            period_start = invoice.get("period_start")
            period_end = invoice.get("period_end")
            await subscription_repo.update_status(
                subscription_id,
                status="active",
                cancel_at_period_end=False,
                current_period_start=(
                    datetime.fromtimestamp(period_start, tz=timezone.utc)
                    if period_start
                    else None
                ),
                current_period_end=(
                    datetime.fromtimestamp(period_end, tz=timezone.utc)
                    if period_end
                    else None
                ),
            )

            await invoice_repo.create(
                tenant_id=subscription.tenant_id,
                stripe_invoice_id=invoice["id"],
                stripe_subscription_id=subscription_id,
                amount_due=invoice["amount_due"],
                amount_paid=invoice["amount_paid"],
                currency=invoice["currency"],
                status=invoice["status"],
                invoice_pdf=invoice.get("invoice_pdf"),
            )

            logger.info(
                f"recorded paid invoice {invoice['id']} for tenant {subscription.tenant_id}"
            )

    async def _handle_payment_failed(self, invoice: dict) -> None:
        """handle failed invoice payment."""
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        async with get_session() as db_session:
            subscription_repo = SubscriptionRepository(db_session)

            await subscription_repo.update_status(subscription_id, "past_due")

            logger.warning(f"payment failed for subscription {subscription_id}")

    async def _handle_subscription_deleted(self, subscription: dict) -> None:
        """handle subscription cancellation."""
        stripe_sub_id = subscription["id"]

        async with get_session() as db_session:
            subscription_repo = SubscriptionRepository(db_session)
            tenant_repo = TenantRepository(db_session)

            db_subscription = await subscription_repo.get_by_stripe_id(stripe_sub_id)
            if not db_subscription:
                logger.warning(f"subscription {stripe_sub_id} not found for deletion")
                return

            await subscription_repo.update_status(
                stripe_sub_id,
                "canceled",
                canceled_at=datetime.now(timezone.utc),
            )

            await tenant_repo.update_plan_tier(db_subscription.tenant_id, "free")

            logger.info(f"downgraded tenant {db_subscription.tenant_id} to free plan")
            downgraded = db_subscription.tenant_id

        await self._announce_tier_change(downgraded)

    async def _handle_subscription_updated(self, subscription: dict) -> None:
        """reconcile plan tier + billing period from the live stripe subscription.

        this is the single reconciliation point for a paid subscription: a
        mid-cycle upgrade/downgrade or a renewal updates the stripe object, and
        we mirror tier, period, status and cancel flag into our row.
        """
        stripe_sub_id = subscription["id"]

        async with get_session() as db_session:
            subscription_repo = SubscriptionRepository(db_session)
            tenant_repo = TenantRepository(db_session)

            existing = await subscription_repo.get_by_stripe_id(stripe_sub_id)
            if not existing:
                logger.warning(f"subscription {stripe_sub_id} not found for update")
                return

            tenant_id = existing.tenant_id
            previous_tier = existing.plan_tier

            status = subscription["status"]
            cancel_at_period_end = subscription.get("cancel_at_period_end", False)
            period_start, period_end = self._period_from_subscription(subscription)

            base_price_id = self._base_price_from_subscription(subscription)
            plan_tier = (
                self._tier_for_base_price(base_price_id) if base_price_id else None
            )

            await subscription_repo.update_status(
                stripe_sub_id,
                status=status,
                cancel_at_period_end=cancel_at_period_end,
                plan_tier=plan_tier,
                current_period_start=period_start,
                current_period_end=period_end,
            )

            tier_changed = bool(plan_tier and plan_tier != previous_tier)
            if tier_changed:
                await tenant_repo.update_plan_tier(tenant_id, plan_tier)
                logger.info(f"reconciled tenant {tenant_id} to {plan_tier} plan")

            logger.info(
                f"updated subscription {stripe_sub_id}: status={status}, cancel_at_period_end={cancel_at_period_end}"
            )

        if tier_changed:
            await self._announce_tier_change(tenant_id)

    async def _prepare_tier_change(self, tenant_id: str, target_tier: str):
        """validate a tier change and resolve the sub + target item payload.

        shared by preview and change so both reject the same cases and swap the
        identical base + metered items.
        """
        if target_tier not in _SELF_SERVE_TIERS:
            raise InvalidTierChangeError(f"{target_tier} is not a self-serve tier")

        async with get_session() as session:
            subscription_repo = SubscriptionRepository(session)
            subscription = await subscription_repo.get_by_tenant_id(tenant_id)

        if not subscription or subscription.status not in _ACTIVE_SUBSCRIPTION_STATUSES:
            raise NoActiveSubscriptionError(
                f"no active subscription for tenant {tenant_id}"
            )

        if subscription.plan_tier == target_tier:
            raise InvalidTierChangeError(
                f"tenant {tenant_id} is already on the {target_tier} plan"
            )

        stripe_subscription = await asyncio.to_thread(
            self._stripe.Subscription.retrieve, subscription.stripe_subscription_id
        )
        items = self._tier_change_items(stripe_subscription, target_tier)
        return subscription, items

    async def preview_subscription_change(
        self, tenant_id: str, target_tier: str
    ) -> ChangePreviewResponse:
        """preview the proration a tier change would apply, without committing."""
        subscription, items = await self._prepare_tier_change(tenant_id, target_tier)

        try:
            preview = await asyncio.to_thread(
                self._stripe.Invoice.create_preview,
                customer=subscription.stripe_customer_id,
                subscription=subscription.stripe_subscription_id,
                subscription_details={
                    "items": items,
                    "proration_behavior": "create_prorations",
                },
            )
        except stripe.StripeError as e:
            logger.error(f"stripe error previewing subscription change: {e}")
            raise

        proration_amount = sum(
            line.get("amount", 0)
            for line in preview.get("lines", {}).get("data", [])
            if line.get("proration")
        )

        return ChangePreviewResponse(
            target_tier=target_tier,
            currency=preview.get("currency", "usd"),
            proration_amount=proration_amount,
            next_invoice_total=preview.get("amount_due", 0),
        )

    async def change_subscription(
        self, tenant_id: str, target_tier: str
    ) -> Optional[SubscriptionResponse]:
        """upgrade or downgrade a subscription by swapping its base + metered items.

        the portal can't switch metered/multi-item subs, so this modifies both
        items in one call with immediate proration, then reconciles our row from
        the authoritative object stripe returns (same path as the
        subscription.updated webhook, which later repeats it idempotently).
        """
        subscription, items = await self._prepare_tier_change(tenant_id, target_tier)

        try:
            updated = await asyncio.to_thread(
                self._stripe.Subscription.modify,
                subscription.stripe_subscription_id,
                items=items,
                proration_behavior="create_prorations",
            )
        except stripe.StripeError as e:
            logger.error(f"stripe error changing subscription: {e}")
            raise

        await self._handle_subscription_updated(updated)

        logger.info(f"changed tenant {tenant_id} subscription to {target_tier} plan")

        return await self.get_subscription(tenant_id)

    async def get_subscription(self, tenant_id: str) -> Optional[SubscriptionResponse]:
        """get current subscription for tenant."""
        async with get_session() as session:
            subscription_repo = SubscriptionRepository(session)
            subscription = await subscription_repo.get_by_tenant_id(tenant_id)

            if not subscription:
                return None

            return SubscriptionResponse(
                id=subscription.id,
                plan_tier=subscription.plan_tier,
                status=subscription.status,
                current_period_start=int(subscription.current_period_start.timestamp()),
                current_period_end=int(subscription.current_period_end.timestamp()),
                cancel_at_period_end=subscription.cancel_at_period_end,
                canceled_at=(
                    int(subscription.canceled_at.timestamp())
                    if subscription.canceled_at
                    else None
                ),
            )

    async def get_usage(self, tenant_id: str) -> Optional[UsageResponse]:
        """billed usage for the current period, sourced from stripe's upcoming
        invoice preview for the tenant's metered line.

        returns None when usage doesn't apply: no subscription, inactive, or a
        non-metered tier (free/enterprise) — the router maps that to 404.
        """
        cached = self._usage_cache.get(tenant_id)
        if cached is not None:
            return cached

        async with get_session() as session:
            subscription = await SubscriptionRepository(session).get_by_tenant_id(
                tenant_id
            )

        if subscription is None or subscription.status != "active":
            return None
        if subscription.plan_tier not in _SELF_SERVE_TIERS:
            return None
        if (
            not subscription.stripe_subscription_id
            or not subscription.stripe_customer_id
        ):
            return None

        metered_price_id = self._metered_price_for_tier(subscription.plan_tier)
        if not metered_price_id:
            return None

        try:
            preview = await asyncio.to_thread(
                self._stripe.Invoice.create_preview,
                customer=subscription.stripe_customer_id,
                subscription=subscription.stripe_subscription_id,
            )
        except stripe.StripeError as e:
            logger.error(f"stripe error previewing usage for tenant {tenant_id}: {e}")
            raise

        used = 0
        overage_cost = 0
        for line in preview.get("lines", {}).get("data", []):
            if self._line_price_id(line) != metered_price_id:
                continue
            used += line.get("quantity") or 0
            overage_cost += line.get("amount") or 0

        included = PLAN_LIMITS[subscription.plan_tier]["included_selections_per_month"]
        result = UsageResponse(
            used=used,
            included=included,
            overage=max(0, used - included),
            overage_cost=overage_cost,
            currency=preview.get("currency", "eur"),
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
        )
        self._usage_cache[tenant_id] = result
        return result

    async def cancel_subscription(self, tenant_id: str) -> bool:
        """cancel subscription at period end."""
        try:
            async with get_session() as session:
                subscription_repo = SubscriptionRepository(session)
                subscription = await subscription_repo.get_by_tenant_id(tenant_id)

                if not subscription:
                    logger.warning(f"no subscription found for tenant {tenant_id}")
                    return False

                await asyncio.to_thread(
                    self._stripe.Subscription.modify,
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=True,
                )

                await subscription_repo.update_status(
                    subscription.stripe_subscription_id,
                    subscription.status,
                    cancel_at_period_end=True,
                )

                logger.info(
                    f"scheduled cancellation for subscription {subscription.stripe_subscription_id}"
                )
                return True

        except stripe.StripeError as e:
            logger.error(f"stripe error canceling subscription: {e}")
            raise

    async def reactivate_subscription(self, tenant_id: str) -> bool:
        """reactivate a canceled subscription."""
        try:
            async with get_session() as session:
                subscription_repo = SubscriptionRepository(session)
                subscription = await subscription_repo.get_by_tenant_id(tenant_id)

                if not subscription:
                    logger.warning(f"no subscription found for tenant {tenant_id}")
                    return False

                await asyncio.to_thread(
                    self._stripe.Subscription.modify,
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=False,
                )

                await subscription_repo.update_status(
                    subscription.stripe_subscription_id,
                    subscription.status,
                    cancel_at_period_end=False,
                )

                logger.info(
                    f"reactivated subscription {subscription.stripe_subscription_id}"
                )
                return True

        except stripe.StripeError as e:
            logger.error(f"stripe error reactivating subscription: {e}")
            raise

    async def list_invoices(self, tenant_id: str) -> list[InvoiceResponse]:
        """list billing history for tenant."""
        async with get_session() as session:
            invoice_repo = InvoiceRepository(session)
            invoices = await invoice_repo.list_by_tenant(tenant_id)

            return [
                InvoiceResponse(
                    id=invoice.id,
                    amount_due=invoice.amount_due,
                    amount_paid=invoice.amount_paid,
                    currency=invoice.currency,
                    status=invoice.status,
                    invoice_pdf=invoice.invoice_pdf,
                    created_at=int(invoice.created_at.timestamp()),
                )
                for invoice in invoices
            ]

    @staticmethod
    def _base_prices() -> dict[str, str]:
        """tier -> base licensed price id, for the tiers that have one configured.

        unset settings are the empty string, so they are dropped rather than
        left to match an absent price id.
        """
        prices = {
            "starter": settings.stripe_price_id_starter,
            "growth": settings.stripe_price_id_growth,
            "scale": settings.stripe_price_id_scale,
            "enterprise": settings.stripe_price_id_enterprise,
        }
        return {tier: price_id for tier, price_id in prices.items() if price_id}

    @staticmethod
    def _metered_prices() -> dict[str, str]:
        """tier -> metered (overage) price id, for the tiers that have one.

        enterprise is custom and never self-serve checks out, so it has none.
        """
        prices = {
            "starter": settings.stripe_metered_price_id_starter,
            "growth": settings.stripe_metered_price_id_growth,
            "scale": settings.stripe_metered_price_id_scale,
        }
        return {tier: price_id for tier, price_id in prices.items() if price_id}

    def _tier_for_base_price(self, price_id: str | None) -> str | None:
        """resolve a base price id to its tier, or None when it matches none.

        never guesses. the tier decides which overage price a subscription
        carries and what the tenant is entitled to, so a wrong answer bills and
        provisions the wrong plan — every caller has to handle None.
        """
        if not price_id:
            return None
        for tier, configured in self._base_prices().items():
            if configured == price_id:
                return tier
        return None

    def _base_price_from_subscription(self, subscription: dict) -> str | None:
        """pick the base licensed price from a base + metered two-item subscription."""
        base_price_ids = set(self._base_prices().values())
        for item in subscription.get("items", {}).get("data", []):
            price_id = item.get("price", {}).get("id")
            if price_id in base_price_ids:
                return price_id
        return None

    @staticmethod
    def _period_from_subscription(
        subscription: dict,
    ) -> tuple[datetime, datetime] | tuple[None, None]:
        """extract the billing period; newer stripe api versions carry it on the
        line items rather than the subscription itself."""
        start = subscription.get("current_period_start")
        end = subscription.get("current_period_end")
        if start is None or end is None:
            items = subscription.get("items", {}).get("data", [])
            if items:
                start = start or items[0].get("current_period_start")
                end = end or items[0].get("current_period_end")
        if start is None or end is None:
            return None, None
        return (
            datetime.fromtimestamp(start, tz=timezone.utc),
            datetime.fromtimestamp(end, tz=timezone.utc),
        )

    @staticmethod
    def _line_price_id(line: dict) -> str | None:
        """extract a price id from an invoice preview line, tolerating stripe api
        version differences between the legacy `price` field and the newer
        `pricing.price_details` structure."""
        price = line.get("price")
        if isinstance(price, dict) and price.get("id"):
            return price["id"]
        pricing = line.get("pricing") or {}
        price_details = pricing.get("price_details") or {}
        return price_details.get("price")

    def _metered_price_for_tier(self, tier: str) -> str | None:
        """resolve the metered (overage) price id for a tier, or None if unconfigured."""
        return self._metered_prices().get(tier)

    def _base_price_for_tier(self, tier: str) -> str | None:
        """resolve the base licensed price id for a tier, or None if unconfigured."""
        return self._base_prices().get(tier)

    def _tier_change_items(self, subscription: dict, target_tier: str) -> list[dict]:
        """build the items payload that swaps a sub's base + metered prices to target_tier.

        existing item ids are reused so stripe replaces the prices rather than
        adding new items; a metered price absent from the current sub is appended.
        """
        base_price = self._base_price_for_tier(target_tier)
        metered_price = self._metered_price_for_tier(target_tier)

        base_price_ids = set(self._base_prices().values())
        metered_price_ids = set(self._metered_prices().values())

        base_item_id = None
        metered_item_id = None
        for item in subscription.get("items", {}).get("data", []):
            price_id = item.get("price", {}).get("id")
            if price_id in base_price_ids:
                base_item_id = item.get("id")
            elif price_id in metered_price_ids:
                metered_item_id = item.get("id")

        items: list[dict] = []
        if base_item_id:
            items.append({"id": base_item_id, "price": base_price})
        else:
            items.append({"price": base_price})

        if metered_price:
            if metered_item_id:
                items.append({"id": metered_item_id, "price": metered_price})
            else:
                items.append({"price": metered_price})

        return items
