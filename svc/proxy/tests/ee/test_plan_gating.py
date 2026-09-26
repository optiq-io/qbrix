"""integration tests for feature gating on ee insight/event endpoints."""

from __future__ import annotations

import pytest

from svc.proxy.tests.integration.http.conftest import as_tenant

INSIGHT_ROUTE = "/api/v1/insight/experiment/exp-1"
EVENT_ROUTE = "/api/v1/event"
ACTIVITY_ROUTE = "/api/v1/event/experiment/exp-1/activity"

# per the FEATURE_MIN_TIER matrix: insights -> growth+, event_log -> scale+
GATE_CASES_DENIED = [
    *[(INSIGHT_ROUTE, tier) for tier in ("free", "starter")],
    *[(EVENT_ROUTE, tier) for tier in ("free", "starter", "growth")],
    *[(ACTIVITY_ROUTE, tier) for tier in ("free", "starter", "growth")],
]

GATE_CASES_ALLOWED = [
    *[(INSIGHT_ROUTE, tier) for tier in ("growth", "scale", "enterprise")],
    *[(EVENT_ROUTE, tier) for tier in ("scale", "enterprise")],
    *[(ACTIVITY_ROUTE, tier) for tier in ("scale", "enterprise")],
]


class TestFeatureGatingDenied:

    @pytest.mark.parametrize("route,tier", GATE_CASES_DENIED)
    async def test_insufficient_tier_is_forbidden(
        self, client, wired_app, tenant_a, route, tier
    ):
        with as_tenant(
            wired_app.app, tenant_id=tenant_a.id, user_id="user-a", plan_tier=tier
        ):
            response = await client.get(route)

        assert response.status_code == 403, response.text
        assert response.json()["code"] == "PLAN_TIER_REQUIRED"


class TestFeatureGatingAllowed:

    @pytest.mark.parametrize("route,tier", GATE_CASES_ALLOWED)
    async def test_sufficient_tier_passes_gate(
        self, client, wired_app, tenant_a, route, tier
    ):
        # assert the gate passes, not 200: the handler then hits clickhouse,
        # which is not wired here.
        with as_tenant(
            wired_app.app, tenant_id=tenant_a.id, user_id="user-a", plan_tier=tier
        ):
            response = await client.get(route)

        assert response.status_code != 403
        if response.status_code >= 400:
            assert response.json().get("code") != "PLAN_TIER_REQUIRED"
