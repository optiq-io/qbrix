"""the oss edition is unlimited: a free tenant hits none of the plan caps.

every tenant of a self-hosted deployment is free forever — there is no billing
to upgrade through — so each cap the cloud enforces on the free tier must be
absent here, not merely generous.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient

import proxysvc.config as _config_module
import proxysvc.mod.auth.operator as _op_module
from proxysvc import edition
from proxysvc.config import ProxySettings
from proxysvc.core.entitlements import Entitlements

from svc.proxy.tests.integration.http.conftest import as_tenant


@pytest.fixture
def oss(wired_app) -> Entitlements:
    entitlements = edition.entitlements(
        ProxySettings(ee_enabled=False, analytics_enabled=True), wired_app.svc._redis
    )
    wired_app.svc._entitlements = entitlements
    wired_app.svc._build_services()
    _op_module.auth_operator._service._entitlements = entitlements
    return entitlements


@pytest_asyncio.fixture
async def auth_client(wired_app, monkeypatch) -> AsyncGenerator[AsyncClient, Any]:
    """a client that authenticates for real, so caps see a real free tenant."""
    monkeypatch.setattr(_config_module.settings, "runenv", "test")
    transport = ASGITransport(app=wired_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _verify_email(user_id: str) -> None:
    redis = _op_module.auth_operator._service._redis.client
    for key in await redis.keys("qbrix:email_verify:*"):
        if await redis.get(key) == user_id:
            await _op_module.auth_operator.verify_email(
                key.removeprefix("qbrix:email_verify:")
            )
            return


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _founding_admin(client: AsyncClient) -> dict:
    reg = await client.post(
        "/api/auth/register",
        json={"email": "admin@example.com", "password": "admin-pw-123"},
    )
    assert reg.status_code == 201, reg.text
    await _verify_email(reg.json()["id"])
    login = await _login(client, "admin@example.com", "admin-pw-123")
    return {"Authorization": f"Bearer {login['access_token']}"}


async def _invite(client: AsyncClient, admin: dict, email: str):
    return await client.post(
        "/api/auth/workspace/invites",
        json={"email": email, "role": "member"},
        headers=admin,
    )


async def _create_experiment(client: AsyncClient, pool_id: str, name: str):
    return await client.post(
        "/api/v1/experiments",
        json={
            "name": name,
            "pool_id": pool_id,
            "policy": "RandomPolicy",
            "policy_params": {},
            "enabled": True,
        },
    )


async def _create_pool(client: AsyncClient) -> tuple[str, list[dict]]:
    resp = await client.post(
        "/api/v1/pools",
        json={"name": "pool", "arms": [{"name": "a"}, {"name": "b"}]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], resp.json()["arms"]


async def _usage_keys(wired_app) -> list[str]:
    return await wired_app.fake_redis.keys("qbrix:tenant:*:usage:*")


async def _demote_a_member(client: AsyncClient, admin: dict):
    invite = await _invite(client, admin, "member@example.com")
    accepted = await client.post(
        f"/api/auth/invites/{invite.json()['token']}/accept",
        json={"name": "Member", "password": "member-pw-123"},
    )
    return await client.put(
        f"/api/auth/users/{accepted.json()['id']}/role",
        json={"role": "viewer"},
        headers=admin,
    )


async def _select_once(client: AsyncClient, wired_app, tenant_id: str) -> None:
    with as_tenant(wired_app.app, tenant_id=tenant_id, plan_tier="free"):
        pool_id, arms = await _create_pool(client)
        exp = (await _create_experiment(client, pool_id, "exp")).json()
        wired_app.motor_mock.select.return_value = {
            "arm": {k: arms[0][k] for k in ("id", "name", "index")},
            "policy": "RandomPolicy",
        }
        resp = await client.post(
            "/api/v1/agent/select",
            json={"experiment_id": exp["id"], "context": {"id": "ctx-1"}},
        )
    assert resp.status_code == 200, resp.text


class TestProfile:
    async def test_publishes_the_oss_edition_unlimited(
        self, auth_client, app_with_db, oss
    ):
        admin = await _founding_admin(auth_client)

        profile = (await auth_client.get("/api/auth/profile", headers=admin)).json()

        assert profile["plan_tier"] is None
        assert profile["edition"] == "oss"
        assert set(profile["limits"].values()) == {-1}
        assert profile["locked_features"] == []
        assert profile["features"] == ["event_log", "insights", "rbac"]
        assert profile["usage"]["selections_this_period"] is None


class TestNoCaps:
    async def test_fourth_active_experiment(self, client, wired_app, tenant_a, oss):
        with as_tenant(wired_app.app, tenant_id=tenant_a.id, plan_tier="free"):
            pool_id, _ = await _create_pool(client)
            for i in range(4):
                resp = await _create_experiment(client, pool_id, f"exp-{i}")
                assert resp.status_code == 201, resp.text

    async def test_third_api_key(self, auth_client, app_with_db, oss):
        admin = await _founding_admin(auth_client)

        for i in range(3):
            resp = await auth_client.post(
                "/api/auth/api-keys", json={"name": f"key-{i}"}, headers=admin
            )
            assert resp.status_code == 201, resp.text

    async def test_fourth_seat(self, auth_client, app_with_db, oss):
        admin = await _founding_admin(auth_client)

        for i in range(3):
            resp = await _invite(auth_client, admin, f"member-{i}@example.com")
            assert resp.status_code == 201, resp.text

    async def test_role_change(self, auth_client, app_with_db, oss):
        admin = await _founding_admin(auth_client)

        resp = await _demote_a_member(auth_client, admin)

        assert resp.status_code == 200, resp.text


class TestSelectionIsNotMetered:
    async def test_oss_writes_no_usage_counter(self, client, wired_app, tenant_a, oss):
        await _select_once(client, wired_app, tenant_a.id)

        assert await _usage_keys(wired_app) == []
