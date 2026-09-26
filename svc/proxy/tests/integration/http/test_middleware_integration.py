"""http integration tests for auth middleware.

invariants verified:
  scenario 1: protected endpoint with no auth header → 401 in BaseAPIException.to_dict() shape
  scenario 2: public paths work without auth even in non-dev mode

public_paths in AuthMiddleware (exact set):
  /health
  /api/health
  /info
  /docs
  /redoc
  /openapi.json
  /api/auth/register
  /api/auth/login
  /api/auth/refresh
  /api/v1/ee/billing/webhook
  prefix /docs* and /redoc*
  prefix /api/auth/invites/*

BaseAPIException.to_dict() shape:
  always: {"detail": <str>}
  when context is non-empty: {"detail": <str>, "context": <dict>}
  note: status_code is NOT included in the dict — it is the http response status code only.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient

import proxysvc.config as _config_module
import proxysvc.mod.auth.operator as _op_module


@pytest_asyncio.fixture
async def non_dev_client(wired_app, monkeypatch) -> AsyncClient:
    """async httpx client in non-dev mode, so the middleware runs the real auth path."""
    monkeypatch.setattr(_config_module.settings, "runenv", "test")

    transport = ASGITransport(app=wired_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestProtectedEndpointWithoutAuth:
    async def test_no_auth_header_returns_401_with_base_exception_shape(
        self, non_dev_client
    ):
        """
        invariant: middleware raises UnauthorizedException when no auth credentials
        are present on a protected endpoint; the middleware catches it and returns
        a JSONResponse with the BaseAPIException.to_dict() shape.

        the response dict must have exactly the "detail" key (no "status_code" key)
        because BaseAPIException.to_dict() only includes "context" when non-empty.
        """
        response = await non_dev_client.get("/api/v1/pools")

        assert response.status_code == 401

        body = response.json()

        # shape: {"detail": <str>} — status_code is NOT in the dict
        assert "detail" in body
        assert isinstance(body["detail"], str)
        assert len(body["detail"]) > 0

        # status_code must not appear — BaseAPIException.to_dict() never includes it
        assert "status_code" not in body

        # context key is absent when no context was provided
        assert "context" not in body

    async def test_no_auth_header_detail_is_authentication_required(
        self, non_dev_client
    ):
        """
        invariant: the specific UnauthorizedException detail for a missing auth header
        is the string set in middleware._ensure_request_auth().
        """
        response = await non_dev_client.get("/api/v1/pools")

        body = response.json()
        assert "authentication required" in body["detail"].lower()

    async def test_protected_endpoint_with_invalid_bearer_returns_401(
        self, non_dev_client
    ):
        """
        invariant: a Bearer token that fails validation → 401, not 500.
        the middleware must catch the auth exception and return the dict shape.
        """
        response = await non_dev_client.get(
            "/api/v1/pools",
            headers={"Authorization": "Bearer not-a-real-token"},
        )

        assert response.status_code == 401
        body = response.json()
        assert "detail" in body
        assert "status_code" not in body


class TestPublicPathsWithoutAuth:
    async def test_health_endpoint_returns_200_in_non_dev_mode(self, non_dev_client):
        """
        invariant: /health is in public_paths — it must never require auth.
        a regression here would lock out kubernetes liveness probes.
        """
        response = await non_dev_client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    async def test_api_health_endpoint_returns_200_in_non_dev_mode(
        self, non_dev_client
    ):
        """
        invariant: /api/health is in public_paths — alternate health path must
        not require auth either.
        """
        response = await non_dev_client.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    async def test_register_endpoint_reachable_without_auth_in_non_dev_mode(
        self, non_dev_client, app_with_db
    ):
        """
        invariant: /api/auth/register is in public_paths — new user sign-up must
        work without any prior credentials.  a regression here silently locks out
        all new users.
        """
        body = {
            "email": "new-user@example.com",
            "password": "secure-password-123",
            "name": "New User",
        }

        response = await non_dev_client.post("/api/auth/register", json=body)

        # middleware must not 401 — route decides the final status
        assert response.status_code != 401

        # register returns 201 on success (status.HTTP_201_CREATED in auth router)
        assert response.status_code == 201

        data = response.json()
        assert data["email"] == "new-user@example.com"

    async def test_login_endpoint_reachable_without_auth_in_non_dev_mode(
        self, non_dev_client, app_with_db
    ):
        """
        invariant: /api/auth/login is in public_paths — login must not be gated
        behind auth (that would be a circular dependency).

        we assert the middleware does not return 401; the route itself returns 401
        for bad credentials which is correct behaviour, not a middleware regression.
        """
        # first register so the user exists in the db
        reg = await non_dev_client.post(
            "/api/auth/register",
            json={
                "email": "login-test@example.com",
                "password": "password-for-login-test",
            },
        )

        # non-dev registration leaves the user unverified; consume the verification
        # token (issued to redis) so login can succeed and prove the public path.
        redis = _op_module.auth_operator._service._redis.client
        user_id = reg.json()["id"]
        for key in await redis.keys("qbrix:email_verify:*"):
            if await redis.get(key) == user_id:
                await _op_module.auth_operator.verify_email(
                    key.removeprefix("qbrix:email_verify:")
                )
                break

        response = await non_dev_client.post(
            "/api/auth/login",
            json={
                "email": "login-test@example.com",
                "password": "password-for-login-test",
            },
        )

        # middleware must not intercept — route should process the request
        # 200 means successful login
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_invite_path_prefix_reachable_without_auth(
        self, non_dev_client, app_with_db
    ):
        """
        invariant: paths starting with /api/auth/invites/ are public — invite
        acceptance must not require a logged-in session.

        a non-existent token returns 404 from the route, not 401 from middleware.
        """
        response = await non_dev_client.get("/api/auth/invites/some-token-value")

        # middleware passes through; route returns 404 for unknown token
        assert response.status_code != 401
        assert response.status_code == 404
