"""the cloud counterparts of the oss edition's unlimited posture."""

from __future__ import annotations

from svc.proxy.tests.integration.http import test_oss_edition as _oss

auth_client = _oss.auth_client


class TestProfile:
    async def test_publishes_what_the_free_tier_is_missing(
        self, auth_client, app_with_db
    ):
        admin = await _oss._founding_admin(auth_client)

        profile = (await auth_client.get("/api/auth/profile", headers=admin)).json()

        assert profile["edition"] == "cloud"
        assert profile["features"] == []
        assert profile["locked_features"] == ["event_log", "insights", "rbac", "sso"]
        assert profile["limits"] == {
            "included_selections_per_month": 100_000,
            "max_api_keys": 2,
            "max_seats": 3,
            "max_active_experiments": 3,
        }
        assert profile["usage"]["selections_this_period"] == 0
        assert profile["usage"]["period_start"] < profile["usage"]["period_end"]


class TestGates:
    async def test_role_change_needs_a_tier_that_includes_it(
        self, auth_client, app_with_db
    ):
        admin = await _oss._founding_admin(auth_client)

        resp = await _oss._demote_a_member(auth_client, admin)

        assert resp.status_code == 403
        assert resp.json()["context"]["required_tiers"] == ["scale", "enterprise"]


class TestSelectionIsMetered:
    async def test_writes_the_usage_counter(self, client, wired_app, tenant_a):
        await _oss._select_once(client, wired_app, tenant_a.id)

        assert len(await _oss._usage_keys(wired_app)) == 1
