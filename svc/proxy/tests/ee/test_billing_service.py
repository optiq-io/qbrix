"""tests for base + metered checkout wiring (usage-based billing)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import qbrixstore.postgres.session as _session_module
import proxysvc.ee.billing.service as _billing_module
from sqlalchemy import select
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User

import pytest

from proxysvc.config import settings
from proxysvc.ee.billing.announcer import NullTenantAnnouncer
from proxysvc.ee.billing.service import BillingService
from proxysvc.ee.billing.service import ActiveSubscriptionExistsError
from proxysvc.ee.billing.service import NoStripeCustomerError
from proxysvc.ee.billing.service import NoActiveSubscriptionError
from proxysvc.ee.billing.service import InvalidTierChangeError
from proxysvc.ee.billing.service import UnknownPriceError
from proxysvc.mod.auth.repository import TenantRepository
from proxysvc.ee.billing.repository import StripeCustomerRepository
from proxysvc.ee.billing.repository import SubscriptionRepository


async def _seed_tenant_with_customer(tenant_id: str, customer_id: str) -> None:
    async with _session_module.get_session() as session:
        session.add(Tenant(id=tenant_id, name=tenant_id, slug=tenant_id))
        await session.flush()
        await StripeCustomerRepository(session).create(tenant_id, customer_id)


async def _seed_subscription(
    tenant_id: str, stripe_sub_id: str, plan_tier: str
) -> None:
    async with _session_module.get_session() as session:
        session.add(Tenant(id=tenant_id, name=tenant_id, slug=tenant_id))
        await session.flush()
        session.add(
            User(
                tenant_id=tenant_id,
                email=f"{tenant_id}@test.local",
                password_hash="x",
            )
        )
        await SubscriptionRepository(session).create(
            tenant_id=tenant_id,
            stripe_subscription_id=stripe_sub_id,
            stripe_customer_id="cus_x",
            plan_tier=plan_tier,
            current_period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            current_period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
            status="active",
        )
        await session.flush()


def _sub_updated_event(
    stripe_sub_id: str,
    items: list[dict],
    period_start: datetime,
    period_end: datetime,
    status: str = "active",
    cancel_at_period_end: bool = False,
) -> dict:
    return {
        "id": stripe_sub_id,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "current_period_start": int(period_start.timestamp()),
        "current_period_end": int(period_end.timestamp()),
        "items": {"data": items},
    }


def _billing(announcer=None) -> BillingService:
    """a billing service that announces nowhere unless a recorder is passed."""
    return BillingService(announcer=announcer or NullTenantAnnouncer())


def _billing_service_with_stripe_mock() -> BillingService:
    svc = _billing()
    svc._stripe = MagicMock()
    svc._stripe.checkout.Session.create.return_value = MagicMock(
        id="cs_test_1", url="https://checkout.stripe.test/cs_test_1"
    )
    return svc


class TestCheckoutLineItems:
    async def test_attaches_base_and_metered_item(self, app_with_db, monkeypatch):
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        monkeypatch.setattr(
            settings, "stripe_metered_price_id_growth", "price_growth_metered"
        )
        await _seed_tenant_with_customer("tenant-a", "cus_test_a")

        svc = _billing_service_with_stripe_mock()
        await svc.create_checkout_session("tenant-a", "user-a", "price_growth_base")

        kwargs = svc._stripe.checkout.Session.create.call_args.kwargs
        assert kwargs["line_items"] == [
            {"price": "price_growth_base", "quantity": 1},
            {"price": "price_growth_metered"},
        ]
        # metadata carries the BASE price so webhook tier provisioning is unchanged
        assert kwargs["metadata"]["price_id"] == "price_growth_base"

    async def test_base_only_when_metered_unconfigured(self, app_with_db, monkeypatch):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_metered_price_id_starter", "")
        await _seed_tenant_with_customer("tenant-a", "cus_test_a")

        svc = _billing_service_with_stripe_mock()
        await svc.create_checkout_session("tenant-a", "user-a", "price_starter_base")

        kwargs = svc._stripe.checkout.Session.create.call_args.kwargs
        assert kwargs["line_items"] == [{"price": "price_starter_base", "quantity": 1}]


class TestPortalSession:
    async def test_create_portal_session_returns_url(self, app_with_db):
        await _seed_tenant_with_customer("tenant-a", "cus_test_a")

        svc = _billing()
        svc._stripe = MagicMock()
        svc._stripe.billing_portal.Session.create.return_value = MagicMock(
            url="https://billing.stripe.test/session/ps_1"
        )

        result = await svc.create_portal_session("tenant-a", "https://console/settings")

        assert result.url == "https://billing.stripe.test/session/ps_1"
        kwargs = svc._stripe.billing_portal.Session.create.call_args.kwargs
        assert kwargs["customer"] == "cus_test_a"
        assert kwargs["return_url"] == "https://console/settings"

    async def test_portal_session_without_customer_raises(self, app_with_db):
        async with _session_module.get_session() as session:
            session.add(Tenant(id="tenant-a", name="tenant-a", slug="tenant-a"))
            await session.flush()

        svc = _billing()
        svc._stripe = MagicMock()

        with pytest.raises(NoStripeCustomerError):
            await svc.create_portal_session("tenant-a")

        svc._stripe.billing_portal.Session.create.assert_not_called()


class TestCheckoutGuard:
    async def test_checkout_blocked_when_active_subscription_exists(
        self, app_with_db, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        await _seed_subscription("tenant-a", "sub_1", "starter")

        svc = _billing_service_with_stripe_mock()

        with pytest.raises(ActiveSubscriptionExistsError):
            await svc.create_checkout_session("tenant-a", "user-a", "price_growth_base")

        svc._stripe.checkout.Session.create.assert_not_called()

    async def test_checkout_allowed_when_subscription_canceled(
        self, app_with_db, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_metered_price_id_starter", "")
        await _seed_subscription("tenant-a", "sub_1", "starter")
        async with _session_module.get_session() as session:
            await StripeCustomerRepository(session).create("tenant-a", "cus_test_a")
            await SubscriptionRepository(session).update_status("sub_1", "canceled")

        svc = _billing_service_with_stripe_mock()
        await svc.create_checkout_session("tenant-a", "user-a", "price_starter_base")

        svc._stripe.checkout.Session.create.assert_called_once()


class TestChangeSubscription:
    @staticmethod
    def _stripe_for_change(updated_items: list[dict]) -> MagicMock:
        """mock stripe whose modify returns the authoritative post-change sub.

        retrieve yields the current (starter) two items so item ids can be
        reused; modify returns a subscription.updated-shaped object carrying the
        target-tier items, which change_subscription reconciles from.
        """
        stripe_mock = MagicMock()
        stripe_mock.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"id": "si_base", "price": {"id": "price_starter_base"}},
                    {"id": "si_metered", "price": {"id": "price_starter_metered"}},
                ]
            }
        }
        stripe_mock.Subscription.modify.return_value = _sub_updated_event(
            "sub_1",
            items=updated_items,
            period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        return stripe_mock

    async def test_upgrade_swaps_both_items_and_reconciles_from_stripe(
        self, app_with_db, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        monkeypatch.setattr(
            settings, "stripe_metered_price_id_starter", "price_starter_metered"
        )
        monkeypatch.setattr(
            settings, "stripe_metered_price_id_growth", "price_growth_metered"
        )
        await _seed_subscription("tenant-a", "sub_1", "starter")

        svc = _billing()
        svc._stripe = self._stripe_for_change(
            [
                {"price": {"id": "price_growth_base"}},
                {"price": {"id": "price_growth_metered"}},
            ]
        )

        result = await svc.change_subscription("tenant-a", "growth")

        kwargs = svc._stripe.Subscription.modify.call_args.kwargs
        assert kwargs["proration_behavior"] == "create_prorations"
        assert kwargs["items"] == [
            {"id": "si_base", "price": "price_growth_base"},
            {"id": "si_metered", "price": "price_growth_metered"},
        ]

        async with _session_module.get_session() as session:
            sub = await SubscriptionRepository(session).get_by_tenant_id("tenant-a")
            tenant = await TenantRepository(session).get("tenant-a")
        assert sub.plan_tier == "growth"
        assert tenant.plan_tier == "growth"
        # period comes from the object stripe returned, not our intent
        assert sub.current_period_end.replace(tzinfo=timezone.utc) == datetime(
            2026, 8, 1, tzinfo=timezone.utc
        )
        assert result.plan_tier == "growth"

    async def test_swaps_base_only_when_target_metered_unconfigured(
        self, app_with_db, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        monkeypatch.setattr(
            settings, "stripe_metered_price_id_starter", "price_starter_metered"
        )
        monkeypatch.setattr(settings, "stripe_metered_price_id_growth", "")
        await _seed_subscription("tenant-a", "sub_1", "starter")

        svc = _billing()
        svc._stripe = self._stripe_for_change([{"price": {"id": "price_growth_base"}}])

        await svc.change_subscription("tenant-a", "growth")

        kwargs = svc._stripe.Subscription.modify.call_args.kwargs
        assert kwargs["items"] == [{"id": "si_base", "price": "price_growth_base"}]

    async def test_invalid_target_tier_raises(self, app_with_db):
        await _seed_subscription("tenant-a", "sub_1", "starter")

        svc = _billing()
        svc._stripe = MagicMock()

        with pytest.raises(InvalidTierChangeError):
            await svc.change_subscription("tenant-a", "enterprise")

        svc._stripe.Subscription.modify.assert_not_called()

    async def test_same_tier_is_rejected(self, app_with_db):
        await _seed_subscription("tenant-a", "sub_1", "growth")

        svc = _billing()
        svc._stripe = MagicMock()

        with pytest.raises(InvalidTierChangeError):
            await svc.change_subscription("tenant-a", "growth")

        svc._stripe.Subscription.modify.assert_not_called()

    async def test_no_active_subscription_raises(self, app_with_db):
        async with _session_module.get_session() as session:
            session.add(Tenant(id="tenant-a", name="tenant-a", slug="tenant-a"))
            await session.flush()

        svc = _billing()
        svc._stripe = MagicMock()

        with pytest.raises(NoActiveSubscriptionError):
            await svc.change_subscription("tenant-a", "growth")

        svc._stripe.Subscription.modify.assert_not_called()


class TestPreviewSubscriptionChange:
    async def test_preview_returns_net_proration_and_total(
        self, app_with_db, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        monkeypatch.setattr(
            settings, "stripe_metered_price_id_starter", "price_starter_metered"
        )
        monkeypatch.setattr(
            settings, "stripe_metered_price_id_growth", "price_growth_metered"
        )
        await _seed_subscription("tenant-a", "sub_1", "starter")

        svc = _billing()
        svc._stripe = MagicMock()
        svc._stripe.Subscription.retrieve.return_value = {
            "items": {
                "data": [
                    {"id": "si_base", "price": {"id": "price_starter_base"}},
                    {"id": "si_metered", "price": {"id": "price_starter_metered"}},
                ]
            }
        }
        svc._stripe.Invoice.create_preview.return_value = {
            "currency": "usd",
            "amount_due": 6733,
            "lines": {
                "data": [
                    {"amount": 1833, "proration": True},
                    {"amount": -900, "proration": True},
                    {"amount": 4900, "proration": False},
                ]
            },
        }

        result = await svc.preview_subscription_change("tenant-a", "growth")

        kwargs = svc._stripe.Invoice.create_preview.call_args.kwargs
        assert kwargs["subscription"] == "sub_1"
        assert kwargs["subscription_details"]["items"] == [
            {"id": "si_base", "price": "price_growth_base"},
            {"id": "si_metered", "price": "price_growth_metered"},
        ]
        # only proration lines net together; the recurring line is excluded
        assert result.proration_amount == 933
        assert result.next_invoice_total == 6733
        assert result.currency == "usd"
        assert result.target_tier == "growth"

    async def test_preview_rejects_invalid_tier(self, app_with_db):
        await _seed_subscription("tenant-a", "sub_1", "starter")

        svc = _billing()
        svc._stripe = MagicMock()

        with pytest.raises(InvalidTierChangeError):
            await svc.preview_subscription_change("tenant-a", "enterprise")

        svc._stripe.Invoice.create_preview.assert_not_called()


class TestMeteredPriceForTier:
    def test_resolves_paid_tiers_and_none_otherwise(self, monkeypatch):
        monkeypatch.setattr(settings, "stripe_metered_price_id_starter", "m_starter")
        monkeypatch.setattr(settings, "stripe_metered_price_id_growth", "m_growth")
        monkeypatch.setattr(settings, "stripe_metered_price_id_scale", "m_scale")

        svc = _billing()
        assert svc._metered_price_for_tier("starter") == "m_starter"
        assert svc._metered_price_for_tier("growth") == "m_growth"
        assert svc._metered_price_for_tier("scale") == "m_scale"
        # enterprise is custom, free never checks out, unknown falls through
        assert svc._metered_price_for_tier("enterprise") is None
        assert svc._metered_price_for_tier("free") is None
        assert svc._metered_price_for_tier("bogus") is None


class TestWebhookTolerance:
    async def test_checkout_completed_provisions_tier_from_base_price(
        self, app_with_db, monkeypatch
    ):
        # metadata keeps the base price_id, so tier provisioning is unaffected
        # by the presence of a second (metered) subscription item.
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        async with _session_module.get_session() as session:
            session.add(Tenant(id="tenant-a", name="tenant-a", slug="tenant-a"))
            await session.flush()

        svc = _billing()
        svc._stripe = MagicMock()
        stripe_sub = MagicMock(id="sub_1", customer="cus_test_a", status="active")
        stripe_sub.start_date = int(
            datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
        )
        svc._stripe.Subscription.retrieve.return_value = stripe_sub

        await svc._handle_checkout_completed(
            {
                "metadata": {"tenant_id": "tenant-a", "price_id": "price_growth_base"},
                "subscription": "sub_1",
            }
        )

        async with _session_module.get_session() as session:
            created = await SubscriptionRepository(session).get_by_tenant_id("tenant-a")
            tenant_tier = await session.scalar(
                select(Tenant.plan_tier).where(Tenant.id == "tenant-a")
            )
        assert created is not None
        assert created.plan_tier == "growth"
        assert tenant_tier == "growth"


class TestTenantTierOnCancellation:
    async def test_subscription_deleted_downgrades_the_tenant(self, app_with_db):
        await _seed_subscription("tenant-a", "sub_1", "growth")
        async with _session_module.get_session() as session:
            await TenantRepository(session).update_plan_tier("tenant-a", "growth")

        await _billing()._handle_subscription_deleted({"id": "sub_1"})

        async with _session_module.get_session() as session:
            assert (
                await session.scalar(
                    select(Tenant.plan_tier).where(Tenant.id == "tenant-a")
                )
                == "free"
            )

    async def test_tier_write_shares_the_subscription_transaction(self, app_with_db):
        """the tenant tier and the subscription row move together, never apart."""
        await _seed_subscription("tenant-a", "sub_1", "growth")
        async with _session_module.get_session() as session:
            await TenantRepository(session).update_plan_tier("tenant-a", "growth")

        await _billing()._handle_subscription_deleted({"id": "sub_1"})

        async with _session_module.get_session() as session:
            sub = await SubscriptionRepository(session).get_by_stripe_id("sub_1")
            tenant_tier = await session.scalar(
                select(Tenant.plan_tier).where(Tenant.id == "tenant-a")
            )
        assert sub.status == "canceled"
        assert tenant_tier == "free"


class TestSubscriptionUpdated:
    async def test_reconciles_paid_tier_upgrade(self, app_with_db, monkeypatch):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        await _seed_subscription("tenant-a", "sub_1", "starter")

        new_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
        new_end = datetime(2026, 8, 1, tzinfo=timezone.utc)
        event = _sub_updated_event(
            "sub_1",
            items=[
                {"price": {"id": "price_growth_metered"}},
                {"price": {"id": "price_growth_base"}},
            ],
            period_start=new_start,
            period_end=new_end,
        )

        await _billing()._handle_subscription_updated(event)

        async with _session_module.get_session() as session:
            sub = await SubscriptionRepository(session).get_by_tenant_id("tenant-a")
            tenant = await TenantRepository(session).get("tenant-a")
        assert sub.plan_tier == "growth"
        assert sub.current_period_start.replace(tzinfo=timezone.utc) == new_start
        assert sub.current_period_end.replace(tzinfo=timezone.utc) == new_end
        assert tenant.plan_tier == "growth"

    async def test_corrects_placeholder_period(self, app_with_db, monkeypatch):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        await _seed_subscription("tenant-a", "sub_1", "starter")

        real_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
        real_end = datetime(2026, 8, 1, tzinfo=timezone.utc)
        event = _sub_updated_event(
            "sub_1",
            items=[{"price": {"id": "price_starter_base"}}],
            period_start=real_start,
            period_end=real_end,
        )

        await _billing()._handle_subscription_updated(event)

        async with _session_module.get_session() as session:
            sub = await SubscriptionRepository(session).get_by_tenant_id("tenant-a")
        assert sub.plan_tier == "starter"
        assert sub.current_period_start.replace(tzinfo=timezone.utc) == real_start
        assert sub.current_period_end.replace(tzinfo=timezone.utc) == real_end

    async def test_selects_base_item_never_maps_metered(self, app_with_db, monkeypatch):
        # metered item listed first; if it were mapped it would default to
        # "starter", so a "growth" result proves the base item was selected.
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        await _seed_subscription("tenant-a", "sub_1", "growth")

        event = _sub_updated_event(
            "sub_1",
            items=[
                {"price": {"id": "price_growth_metered"}},
                {"price": {"id": "price_growth_base"}},
            ],
            period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

        await _billing()._handle_subscription_updated(event)

        async with _session_module.get_session() as session:
            sub = await SubscriptionRepository(session).get_by_tenant_id("tenant-a")
        assert sub.plan_tier == "growth"

    async def test_writes_the_tenant_tier(self, app_with_db, monkeypatch):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        await _seed_subscription("tenant-a", "sub_1", "starter")

        await _billing()._handle_subscription_updated(
            _sub_updated_event(
                "sub_1",
                items=[{"price": {"id": "price_growth_base"}}],
                period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
                period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        )

        async with _session_module.get_session() as session:
            assert (
                await session.scalar(
                    select(Tenant.plan_tier).where(Tenant.id == "tenant-a")
                )
                == "growth"
            )

    async def test_unknown_subscription_is_noop(self, app_with_db):
        event = _sub_updated_event(
            "sub_missing",
            items=[{"price": {"id": "price_x"}}],
            period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

        # must not raise
        await _billing()._handle_subscription_updated(event)

        async with _session_module.get_session() as session:
            sub = await SubscriptionRepository(session).get_by_stripe_id("sub_missing")
        assert sub is None


class _RecordingBus:
    """stands in for TenantInvalidation, recording each announcement along
    with how many database sessions were open when it was made."""

    def __init__(self, session_depth):
        self.published: list[tuple[str, int]] = []
        self._session_depth = session_depth

    async def publish(self, tenant_id: str) -> None:
        self.published.append((tenant_id, self._session_depth()))

    @property
    def tenants(self) -> list[str]:
        return [tenant_id for tenant_id, _ in self.published]

    @property
    def depths(self) -> list[int]:
        return [depth for _, depth in self.published]


@pytest.fixture
def bus(monkeypatch) -> _RecordingBus:
    """a recording bus, plus a session wrapper that tracks nesting depth.

    get_session commits on exit, so "no session open" is the observable proxy
    for "the tier write is committed". aiosqlite pools a single connection, so
    a second session could not see the pre-commit state — the depth counter is
    what makes the ordering testable at all.
    """
    depth = {"open": 0}
    real_get_session = _session_module.get_session

    @asynccontextmanager
    async def _counting_session():
        depth["open"] += 1
        try:
            async with real_get_session() as session:
                yield session
        finally:
            depth["open"] -= 1

    monkeypatch.setattr(_billing_module, "get_session", _counting_session)
    return _RecordingBus(lambda: depth["open"])


class TestTierChangeAnnouncement:
    """every tier write has to reach the other replicas' caches, and it has to
    do so only once the write is visible to them."""

    async def test_checkout_announces_after_the_session_commits(
        self, app_with_db, bus, monkeypatch
    ):
        """announcing inside the session block would have subscribers evict,
        re-read the uncommitted row, and re-cache the tier they just dropped."""
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        async with _session_module.get_session() as session:
            session.add(Tenant(id="tenant-a", name="tenant-a", slug="tenant-a"))
            await session.flush()

        svc = _billing(bus)
        svc._stripe = MagicMock()
        stripe_sub = MagicMock(id="sub_1", customer="cus_test_a", status="active")
        stripe_sub.start_date = int(
            datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
        )
        svc._stripe.Subscription.retrieve.return_value = stripe_sub

        await svc._handle_checkout_completed(
            {
                "metadata": {"tenant_id": "tenant-a", "price_id": "price_growth_base"},
                "subscription": "sub_1",
            }
        )

        assert bus.tenants == ["tenant-a"]
        assert bus.depths == [0]

    async def test_cancellation_announces_after_the_session_commits(
        self, app_with_db, bus
    ):
        await _seed_subscription("tenant-a", "sub_1", "growth")
        svc = _billing(bus)

        await svc._handle_subscription_deleted({"id": "sub_1"})

        assert bus.tenants == ["tenant-a"]
        assert bus.depths == [0]

    async def test_upgrade_announces_once_after_the_session_commits(
        self, app_with_db, bus, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        await _seed_subscription("tenant-a", "sub_1", "starter")
        svc = _billing(bus)

        await svc._handle_subscription_updated(
            _sub_updated_event(
                "sub_1",
                items=[{"price": {"id": "price_growth_base"}}],
                period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
                period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        )

        assert bus.tenants == ["tenant-a"]
        assert bus.depths == [0]

    async def test_unchanged_tier_announces_nothing(
        self, app_with_db, bus, monkeypatch
    ):
        """renewals and cancel-flag flips arrive on the same webhook; treating
        them as tier changes would flush every replica's cache on each one."""
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        await _seed_subscription("tenant-a", "sub_1", "growth")
        svc = _billing(bus)

        await svc._handle_subscription_updated(
            _sub_updated_event(
                "sub_1",
                items=[{"price": {"id": "price_growth_base"}}],
                period_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                period_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
                cancel_at_period_end=True,
            )
        )

        assert bus.published == []

    async def test_unknown_subscription_announces_nothing(self, app_with_db, bus):
        svc = _billing(bus)

        await svc._handle_subscription_updated(
            _sub_updated_event(
                "sub_missing",
                items=[{"price": {"id": "price_x"}}],
                period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
                period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        )

        assert bus.published == []

    async def test_usage_view_is_dropped_on_a_tier_change(self, app_with_db):
        """the console usage meter's allowance is tier-derived, so it goes
        stale on exactly the same event."""
        svc = _billing()
        svc._usage_cache["tenant-a"] = "stale usage view"
        svc._usage_cache["tenant-b"] = "untouched"

        svc.invalidate_tenant("tenant-a")

        assert svc._usage_cache.get("tenant-a") is None
        assert svc._usage_cache.get("tenant-b") == "untouched"

    async def test_tier_change_without_a_bus_still_evicts_locally(
        self, app_with_db, monkeypatch
    ):
        """a process wired with the null announcer must not serve a stale
        allowance just because it has nowhere to broadcast."""
        monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter_base")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        await _seed_subscription("tenant-a", "sub_1", "starter")
        svc = _billing()
        svc._usage_cache["tenant-a"] = "stale usage view"

        await svc._handle_subscription_updated(
            _sub_updated_event(
                "sub_1",
                items=[{"price": {"id": "price_growth_base"}}],
                period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
                period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        )

        assert svc._usage_cache.get("tenant-a") is None


class TestTierForBasePrice:
    def test_resolves_configured_prices(self, monkeypatch):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "p_starter")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "p_growth")
        monkeypatch.setattr(settings, "stripe_price_id_scale", "p_scale")
        monkeypatch.setattr(settings, "stripe_price_id_enterprise", "p_enterprise")

        svc = _billing()
        assert svc._tier_for_base_price("p_starter") == "starter"
        assert svc._tier_for_base_price("p_growth") == "growth"
        assert svc._tier_for_base_price("p_scale") == "scale"
        assert svc._tier_for_base_price("p_enterprise") == "enterprise"

    def test_unknown_price_resolves_to_none_not_starter(self, monkeypatch):
        monkeypatch.setattr(settings, "stripe_price_id_starter", "p_starter")

        svc = _billing()
        assert svc._tier_for_base_price("p_rotated") is None
        assert svc._tier_for_base_price(None) is None

    def test_empty_price_never_matches_an_unconfigured_tier(self, monkeypatch):
        # unset settings are "", so a comparison against them would resolve an
        # absent price id to whichever tier happens to be unconfigured
        monkeypatch.setattr(settings, "stripe_price_id_starter", "p_starter")
        monkeypatch.setattr(settings, "stripe_price_id_growth", "")
        monkeypatch.setattr(settings, "stripe_price_id_scale", "")
        monkeypatch.setattr(settings, "stripe_price_id_enterprise", "")

        svc = _billing()
        assert svc._tier_for_base_price("") is None


class TestCheckoutRejectsUnknownPrice:
    async def test_raises_and_creates_no_stripe_customer(
        self, app_with_db, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        async with _session_module.get_session() as session:
            session.add(Tenant(id="tenant-a", name="tenant-a", slug="tenant-a"))
            await session.flush()

        svc = _billing_service_with_stripe_mock()

        with pytest.raises(UnknownPriceError):
            await svc.create_checkout_session("tenant-a", "user-a", "price_rotated")

        svc._stripe.Customer.create.assert_not_called()
        svc._stripe.checkout.Session.create.assert_not_called()
        async with _session_module.get_session() as session:
            customer = await StripeCustomerRepository(session).get_by_tenant_id(
                "tenant-a"
            )
        assert customer is None


class TestCheckoutCompletedRejectsUnknownPrice:
    async def test_provisions_nothing_and_fails_the_webhook(
        self, app_with_db, monkeypatch
    ):
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        async with _session_module.get_session() as session:
            session.add(Tenant(id="tenant-a", name="tenant-a", slug="tenant-a"))
            await session.flush()

        svc = _billing()
        svc._stripe = MagicMock()

        event = {
            "metadata": {"tenant_id": "tenant-a", "price_id": "price_rotated"},
            "subscription": "sub_1",
        }

        with pytest.raises(UnknownPriceError):
            await svc._handle_checkout_completed(event)

        # the subscription is never even retrieved, so nothing can be written
        svc._stripe.Subscription.retrieve.assert_not_called()
        async with _session_module.get_session() as session:
            created = await SubscriptionRepository(session).get_by_tenant_id("tenant-a")
            tenant_tier = await session.scalar(
                select(Tenant.plan_tier).where(Tenant.id == "tenant-a")
            )
        assert created is None
        assert tenant_tier == "free"

    async def test_webhook_reports_failure_so_stripe_retries(
        self, app_with_db, monkeypatch
    ):
        # handle_webhook returning False is what makes the route answer 400,
        # which is what buys the three days of stripe retries this relies on
        monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_base")
        async with _session_module.get_session() as session:
            session.add(Tenant(id="tenant-a", name="tenant-a", slug="tenant-a"))
            await session.flush()

        svc = _billing()
        svc._stripe = MagicMock()
        svc._stripe.Webhook.construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {
                        "tenant_id": "tenant-a",
                        "price_id": "price_rotated",
                    },
                    "subscription": "sub_1",
                }
            },
        }

        assert await svc.handle_webhook(b"{}", "sig") is False
