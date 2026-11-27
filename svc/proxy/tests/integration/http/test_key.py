"""integration tests for the workspace's keys, a qbrix next surface.

invariants verified:
  an admin creates a key for an app and environment and gets its secret once;
  only its hash is stored, and no list carries a secret. renaming keeps the
  secret; rotating keeps the id, returns a new secret once and refuses the
  old one at once; revoking refuses the key and drops it from the list. labels
  are trimmed and between 1 and 40 characters. the plan's cap holds. members
  and viewers list keys and can't write; a key and a connection's token can't
  reach the routes at all. none of it is a change, and another workspace's
  key is not found.
"""

from __future__ import annotations

import hashlib

import pytest
import pytest_asyncio
from sqlalchemy import func
from sqlalchemy import select

import proxysvc.config
from qbrixstore.postgres.models import APIKey
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User
from qbrixstore.postgres.session import get_session

from proxysvc.mod.auth import operator
from proxysvc.next import next_routes

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
OTHER_TENANT = "other-tenant"
ADA = "user-ada"
BEN = "user-ben"


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    async with get_session() as session:
        session.add(Tenant(id=TENANT, name="Acme", slug="acme"))
        session.add(Tenant(id=OTHER_TENANT, name="Other", slug="other"))
        for user_id, name in ((ADA, "Ada"), (BEN, "Ben")):
            session.add(
                User(
                    id=user_id,
                    tenant_id=TENANT,
                    email=f"{user_id}@example.com",
                    password_hash="x",
                    name=name,
                )
            )
    with as_tenant(app, tenant_id=TENANT, user_id=ADA, role="admin"):
        yield client
    app.router.routes[:] = routes


async def _create(api, app="shop", environment="production") -> dict:
    resp = await api.post("/api/v1/keys", json={"app": app, "environment": environment})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _list(api) -> list[dict]:
    resp = await api.get("/api/v1/keys")
    assert resp.status_code == 200, resp.text
    return resp.json()["keys"]


async def _accepted(secret: str) -> bool:
    return await operator.auth_operator.validate_api_key(secret) is not None


async def _changes() -> int:
    async with get_session() as session:
        count = await session.execute(select(func.count()).select_from(Change))
        return count.scalar_one()


class TestCreate:
    async def test_returns_the_secret_once_and_stores_only_its_hash(self, api):
        created = await _create(api)

        assert created["secret"].startswith("optiq_")
        assert created["app"] == "shop"
        assert created["environment"] == "production"
        assert created["created_by"] == {"id": ADA, "name": "Ada"}
        assert "rotated_at" not in created
        async with get_session() as session:
            key = await session.get(APIKey, created["id"])
        assert key.tenant_id == TENANT
        assert key.created_by_id == ADA
        assert key.user_id is None
        assert key.key_hash == hashlib.sha256(created["secret"].encode()).hexdigest()
        assert await _accepted(created["secret"])

    async def test_no_list_carries_a_secret(self, api):
        created = await _create(api)

        listed = await _list(api)

        assert [k["id"] for k in listed] == [created["id"]]
        assert "secret" not in listed[0]
        assert "key_hash" not in listed[0]

    async def test_trims_labels(self, api):
        created = await _create(api, app="  shop  ", environment=" staging ")

        assert (created["app"], created["environment"]) == ("shop", "staging")

    @pytest.mark.parametrize(
        "body",
        [
            {"app": "   ", "environment": "production"},
            {"app": "shop", "environment": ""},
            {"app": "x" * 41, "environment": "production"},
        ],
    )
    async def test_refuses_a_label_out_of_bounds(self, api, body):
        resp = await api.post("/api/v1/keys", json=body)

        assert resp.status_code == 422
        assert await _list(api) == []

    async def test_a_label_of_forty_characters_is_taken(self, api):
        created = await _create(api, app="x" * 40)

        assert created["app"] == "x" * 40

    async def test_one_app_and_environment_can_hold_two_keys(self, api):
        await _create(api)
        await _create(api)

        assert len(await _list(api)) == 2

    async def test_the_plans_cap_holds(self, wired_app, api):
        class _OneKey:
            def limits(self, tier):
                return {"max_api_keys": 1}

        wired_app.svc.keys._entitlements = _OneKey()
        await _create(api)

        resp = await api.post(
            "/api/v1/keys", json={"app": "shop", "environment": "staging"}
        )

        assert resp.status_code == 409
        assert len(await _list(api)) == 1


class TestRename:
    async def test_changes_the_labels_and_keeps_the_secret(self, api):
        created = await _create(api)

        resp = await api.patch(
            f"/api/v1/keys/{created['id']}", json={"environment": " staging "}
        )

        assert resp.status_code == 200
        assert resp.json()["app"] == "shop"
        assert resp.json()["environment"] == "staging"
        assert "secret" not in resp.json()
        assert await _accepted(created["secret"])

    async def test_refuses_an_empty_label(self, api):
        created = await _create(api)

        resp = await api.patch(f"/api/v1/keys/{created['id']}", json={"app": ""})

        assert resp.status_code == 422
        assert (await _list(api))[0]["app"] == "shop"


class TestRotate:
    async def test_keeps_the_id_and_refuses_the_old_secret_at_once(self, api):
        created = await _create(api)
        assert await _accepted(created["secret"])

        resp = await api.post(f"/api/v1/keys/{created['id']}/rotate")

        assert resp.status_code == 200
        rotated = resp.json()
        assert rotated["id"] == created["id"]
        assert rotated["secret"] != created["secret"]
        assert "rotated_at" in rotated
        assert not await _accepted(created["secret"])
        assert await _accepted(rotated["secret"])
        assert (await _list(api))[0]["rotated_at"] == rotated["rotated_at"]


class TestRevoke:
    async def test_refuses_the_key_at_once_and_drops_it_from_the_list(self, api):
        created = await _create(api)
        assert await _accepted(created["secret"])

        resp = await api.delete(f"/api/v1/keys/{created['id']}")

        assert resp.status_code == 204
        assert not await _accepted(created["secret"])
        assert await _list(api) == []
        assert (await api.delete(f"/api/v1/keys/{created['id']}")).status_code == 404
        assert (
            await api.post(f"/api/v1/keys/{created['id']}/rotate")
        ).status_code == 404


class TestRoles:
    @pytest.mark.parametrize("role", ["member", "viewer"])
    async def test_lists_but_never_writes(self, wired_app, api, role):
        created = await _create(api)

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id=BEN, role=role):
            listed = await _list(api)
            writes = [
                await api.post(
                    "/api/v1/keys", json={"app": "shop", "environment": "staging"}
                ),
                await api.patch(f"/api/v1/keys/{created['id']}", json={"app": "x"}),
                await api.post(f"/api/v1/keys/{created['id']}/rotate"),
                await api.delete(f"/api/v1/keys/{created['id']}"),
            ]

        assert [k["id"] for k in listed] == [created["id"]]
        assert "secret" not in listed[0]
        assert [w.status_code for w in writes] == [403] * 4
        assert await _accepted(created["secret"])

    async def test_a_key_is_refused(self, wired_app, api, monkeypatch):
        created = await _create(api)
        app = wired_app.app
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        monkeypatch.setattr(proxysvc.config.settings, "runenv", "prod")
        headers = {"X-API-Key": created["secret"]}
        try:
            calls = [
                await api.get("/api/v1/keys", headers=headers),
                await api.post(
                    "/api/v1/keys",
                    json={"app": "shop", "environment": "staging"},
                    headers=headers,
                ),
                await api.patch(
                    f"/api/v1/keys/{created['id']}", json={"app": "x"}, headers=headers
                ),
                await api.post(f"/api/v1/keys/{created['id']}/rotate", headers=headers),
                await api.delete(f"/api/v1/keys/{created['id']}", headers=headers),
            ]
        finally:
            app.dependency_overrides.update(saved)

        assert [c.status_code for c in calls] == [403] * 5
        assert await _accepted(created["secret"])

    async def test_a_connections_token_is_refused(self, wired_app, api, monkeypatch):
        created = await _create(api)
        issued = await wired_app.svc.connections.open(
            user_id=ADA,
            tenant_id=TENANT,
            client_identity="Claude Code:ada",
            client_id="client-claude",
            client_name="Claude Code",
            client_uri=None,
            resource=wired_app.svc._settings.mcp_resource,
        )
        app = wired_app.app
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        monkeypatch.setattr(proxysvc.config.settings, "runenv", "prod")
        headers = {"Authorization": f"Bearer {issued.access_token}"}
        try:
            calls = [
                await api.get("/api/v1/keys", headers=headers),
                await api.post(
                    "/api/v1/keys",
                    json={"app": "shop", "environment": "staging"},
                    headers=headers,
                ),
                await api.post(f"/api/v1/keys/{created['id']}/rotate", headers=headers),
                await api.delete(f"/api/v1/keys/{created['id']}", headers=headers),
            ]
        finally:
            app.dependency_overrides.update(saved)

        assert [c.status_code for c in calls] == [401] * 4
        assert await _accepted(created["secret"])


class TestNotAChange:
    async def test_managing_a_key_records_nothing(self, api):
        created = await _create(api)
        await api.patch(f"/api/v1/keys/{created['id']}", json={"app": "web"})
        await api.post(f"/api/v1/keys/{created['id']}/rotate")
        await api.delete(f"/api/v1/keys/{created['id']}")

        assert await _changes() == 0


class TestWorkspaces:
    async def test_another_workspaces_key_is_not_found(self, wired_app, api):
        created = await _create(api)

        with as_tenant(
            wired_app.app, tenant_id=OTHER_TENANT, user_id="user-zoe", role="admin"
        ):
            listed = await _list(api)
            writes = [
                await api.patch(f"/api/v1/keys/{created['id']}", json={"app": "x"}),
                await api.post(f"/api/v1/keys/{created['id']}/rotate"),
                await api.delete(f"/api/v1/keys/{created['id']}"),
            ]

        assert listed == []
        assert [w.status_code for w in writes] == [404] * 3
        assert await _accepted(created["secret"])
