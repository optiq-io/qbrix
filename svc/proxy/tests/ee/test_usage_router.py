"""integration tests for the stripe-sourced usage endpoint + free hard-cap mapping."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import User

from proxysvc.core.error import UsageLimitError
from proxysvc.ee.billing.repository import SubscriptionRepository

from svc.proxy.tests.integration.http.conftest import as_tenant

USAGE_ROUTE = "/api/v1/ee/billing/usage"
SELECT_ROUTE = "/api/v1/agent/select"


async def _seed_subscription(
    tenant_id: str, plan_tier: str, status: str = "active"
) -> None:
    """seed a user + active subscription for a tenant already inserted by the
    `tenant_a`/`tenant_b` fixture."""
    async with _session_module.get_session() as session:
        session.add(
            User(
                tenant_id=tenant_id,
                email=f"{tenant_id}@test.local",
                password_hash="x",
            )
        )
        await SubscriptionRepository(session).create(
            tenant_id=tenant_id,
            stripe_subscription_id="sub_x",
            stripe_customer_id="cus_x",
            plan_tier=plan_tier,
            current_period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            current_period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
            status=status,
        )
        await session.flush()


class TestUsageEndpoint:
    async def test_metered_tier_returns_stripe_sourced_usage(
        self, client, wired_app, billing, tenant_a, monkeypatch
    ):
        from proxysvc.config import settings

        monkeypatch.setattr(
            settings, "stripe_metered_price_id_starter", "price_metered"
        )
        await _seed_subscription(tenant_a.id, "starter")

        stripe_mock = MagicMock()
        stripe_mock.Invoice.create_preview.return_value = {
            "currency": "eur",
            "lines": {
                "data": [
                    {
                        "price": {"id": "price_metered"},
                        "quantity": 150_000,
                        "amount": 500,
                    },
                    {
                        "price": {"id": "price_other"},
                        "quantity": 999,
                        "amount": 999,
                    },
                ]
            },
        }
        monkeypatch.setattr(billing, "_stripe", stripe_mock)

        with as_tenant(
            wired_app.app,
            tenant_id=tenant_a.id,
            user_id="user-a",
            role="member",
            plan_tier="starter",
        ):
            response = await client.get(USAGE_ROUTE)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["used"] == 150_000
        assert body["included"] == 1_000_000
        assert body["overage"] == 0
        assert body["overage_cost"] == 500
        assert body["currency"] == "eur"
        assert "period_start" in body and "period_end" in body

        kwargs = stripe_mock.Invoice.create_preview.call_args.kwargs
        assert kwargs["customer"] == "cus_x"
        assert kwargs["subscription"] == "sub_x"

    async def test_free_tenant_returns_404(self, client, wired_app, billing, tenant_a):
        with as_tenant(
            wired_app.app,
            tenant_id=tenant_a.id,
            user_id="user-a",
            role="member",
            plan_tier="free",
        ):
            response = await client.get(USAGE_ROUTE)

        assert response.status_code == 404, response.text

    async def test_enterprise_tenant_returns_404(
        self, client, wired_app, billing, tenant_a
    ):
        await _seed_subscription(tenant_a.id, "enterprise")

        with as_tenant(
            wired_app.app,
            tenant_id=tenant_a.id,
            user_id="user-a",
            role="member",
            plan_tier="enterprise",
        ):
            response = await client.get(USAGE_ROUTE)

        assert response.status_code == 404, response.text

    async def test_no_subscription_returns_404(
        self, client, wired_app, billing, tenant_a
    ):
        with as_tenant(
            wired_app.app,
            tenant_id=tenant_a.id,
            user_id="user-a",
            role="member",
            plan_tier="starter",
        ):
            response = await client.get(USAGE_ROUTE)

        assert response.status_code == 404, response.text


class TestFreeHardCapMapping:
    async def test_usage_limit_maps_to_429(self, client, wired_app):
        # the meter runs at the very top of select(); a quota breach there must
        # surface as a 429 with a code distinct from the abuse rate limiter.
        wired_app.svc.entitlements.on_selection = AsyncMock(
            side_effect=UsageLimitError("over quota")
        )

        response = await client.post(
            SELECT_ROUTE,
            json={"experiment_id": "exp-x", "context": {"id": "ctx-1"}},
        )

        assert response.status_code == 429, response.text
        assert response.json()["code"] == "USAGE_LIMIT_EXCEEDED"
