"""integration tests for what a key reaches with qbrix next on.

invariants verified:
  a key is its workspace and reaches select, outcome and track, nothing
  else: every other route in the app, key management and loops included,
  refuses it with 403, an admin's key too. a key from another workspace
  can't select or credit in this one. a key outlives the person who
  created it. a draft's first call names the key by its app and
  environment.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi.routing import iter_route_contexts

import proxysvc.config
from qbrixstore.postgres import session as _session_module
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User

from proxysvc.core.actor import Actor
from proxysvc.mod.auth import operator
from proxysvc.mod.auth.repository import UserRepository
from proxysvc.mod.auth.scope import KEY_REFUSED
from proxysvc.mod.auth.scope import KEY_ROUTES
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.middleware import AuthMiddleware

TENANT = "tenant-a"
OTHER = "tenant-b"
ACTOR = Actor.member("user-ada")


async def _member(tenant_id: str, user_id: str) -> None:
    async with _session_module.get_session() as session:
        session.add(Tenant(id=tenant_id, name=tenant_id, slug=tenant_id))
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"{user_id}@example.com",
                password_hash="x",
                role="admin",
            )
        )


async def _key(user_id: str, scopes: list[str] | None = None) -> str:
    _, plain = await operator.auth_operator.create_api_key(
        user_id, name="shop", scopes=scopes
    )
    return plain


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled, monkeypatch):
    """next mounted, auth enforced, and a draft loop in tenant-a."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    await _member(TENANT, "user-ada")
    await _member(OTHER, "user-bo")
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=2 * 24 * 60 * 60,
        actor=ACTOR,
    )
    await wired_app.svc.create_loop(
        TENANT,
        name="Checkout headline",
        metric="purchase",
        options=[{"name": "Control"}, {"name": "Urgency"}],
        actor=ACTOR,
    )
    monkeypatch.setattr(proxysvc.config.settings, "runenv", "test")
    yield client
    app.router.routes[:] = routes


def _every_route(app) -> list[tuple[str, str]]:
    public = AuthMiddleware(MagicMock())._is_public_path
    return sorted(
        (method, route.path)
        for route in iter_route_contexts(app.routes)
        if route.path and route.methods
        for method in route.methods
        if not public(route.path)
    )


def _filled(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


class TestOffTheRequestPath:
    @pytest.mark.parametrize("scopes", [None, ["system:admin"]])
    async def test_every_other_route_refuses_a_key(self, wired_app, api, scopes):
        key = await _key("user-ada", scopes)
        routes = _every_route(wired_app.app)

        assert set(KEY_ROUTES) <= set(routes)
        assert ("POST", "/api/auth/api-keys") in routes
        assert ("GET", "/api/v1/loops") in routes

        reached = []
        for method, path in routes:
            if (method, path) in KEY_ROUTES:
                continue
            response = await api.request(
                method, _filled(path), headers={"X-API-Key": key}
            )
            if (
                response.status_code != 403
                or response.json().get("detail") != KEY_REFUSED
            ):
                reached.append((method, path, response.status_code))

        assert reached == []

    async def test_a_bearer_key_is_refused_too(self, api):
        key = await _key("user-ada")

        response = await api.get(
            "/api/v1/loops", headers={"Authorization": f"Bearer {key}"}
        )

        assert response.status_code == 403
        assert response.json()["detail"] == KEY_REFUSED


class TestOnTheRequestPath:
    async def test_select_outcome_and_track_take_a_key(self, api):
        headers = {"X-API-Key": await _key("user-ada")}

        select = await api.post(
            "/api/v1/select",
            json={"loop": "checkout-headline", "context": {"unit": "u-1"}},
            headers=headers,
        )
        outcome = await api.post(
            "/api/v1/outcome",
            json={"request_id": "not-a-token", "value": 1},
            headers=headers,
        )
        track = await api.post(
            "/api/v1/track",
            json={"metric": "purchase", "value": 1, "unit": "u-1"},
            headers=headers,
        )

        assert select.status_code == 200
        assert outcome.status_code not in (401, 403)
        assert track.status_code == 202

    async def test_a_drafts_first_call_names_the_keys_app_and_environment(
        self, wired_app, api
    ):
        await api.post(
            "/api/v1/select",
            json={"loop": "checkout-headline", "context": {"unit": "u-1"}},
            headers={"X-API-Key": await _key("user-ada")},
        )
        await wired_app.events.drain()

        assert wired_app.milestone_spy.events[0].payload == {
            "source": "shop · production"
        }

    async def test_another_workspaces_key_reaches_only_its_own(self, wired_app, api):
        headers = {"X-API-Key": await _key("user-bo")}

        select = await api.post(
            "/api/v1/select",
            json={"loop": "checkout-headline", "context": {"unit": "u-1"}},
            headers=headers,
        )
        track = await api.post(
            "/api/v1/track",
            json={"metric": "purchase", "value": 1, "unit": "u-1"},
            headers=headers,
        )
        await wired_app.events.drain()

        assert select.status_code == 404
        assert track.status_code == 404
        assert wired_app.metric_spy.events == []

    async def test_a_key_outlives_the_person_who_created_it(self, api):
        key = await _key("user-ada")
        async with _session_module.get_session() as session:
            await UserRepository(session).delete("user-ada")
        operator.auth_operator._service._api_key_cache.clear()

        response = await api.post(
            "/api/v1/select",
            json={"loop": "checkout-headline", "context": {"unit": "u-1"}},
            headers={"X-API-Key": key},
        )

        assert response.status_code == 200
