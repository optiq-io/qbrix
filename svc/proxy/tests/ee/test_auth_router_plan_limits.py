"""plan limits as the auth router publishes them."""

from __future__ import annotations

from httpx import AsyncClient

from svc.proxy.tests.integration.http import test_auth_router_integration as _core

auth_client = _core.auth_client
_register_and_login = _core._register_and_login
_set_tenant_tier_for_user = _core._set_tenant_tier_for_user


class TestPublishedLimits:
    async def test_unlimited_tiers_publish_minus_one(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: an unlimited limit crosses the wire as -1, never null and
        never a large sentinel.
        """
        login_data = await _register_and_login(
            auth_client,
            email="unlimited@example.com",
            password="unlimited-pw-1",
            name="Unlimited",
        )
        user_id = login_data["user"]["id"]

        await _set_tenant_tier_for_user(user_id, "growth")

        response = await auth_client.get(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {login_data['access_token']}"},
        )

        assert response.status_code == 200
        limits = response.json()["limits"]
        assert limits["max_api_keys"] == -1
        assert limits["max_seats"] == -1
        assert limits["max_active_experiments"] == -1
        assert limits["included_selections_per_month"] == 10_000_000

    async def test_free_tier_stops_at_two_api_keys_across_the_workspace(
        self, auth_client: AsyncClient, app_with_db
    ):
        login = await _register_and_login(
            auth_client, email="owner@example.com", password="owner-pw-123"
        )
        header = {"Authorization": f"Bearer {login['access_token']}"}

        for name in ("first", "second"):
            created = await auth_client.post(
                "/api/auth/api-keys", json={"name": name}, headers=header
            )
            assert created.status_code == 201, created.text

        refused = await auth_client.post(
            "/api/auth/api-keys", json={"name": "third"}, headers=header
        )
        assert refused.status_code == 409, refused.text
