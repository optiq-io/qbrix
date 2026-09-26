"""unit tests for AuthMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxysvc.transport.http.auth.middleware import AuthMiddleware
from proxysvc.transport.http.auth import constant

from svc.proxy.tests.conftest import RecordingSender


def _make_request(
    method: str = "GET",
    path: str = "/api/v1/pools",
    headers: dict | None = None,
    client_host: str = "127.0.0.1",
):
    """create a mock FastAPI Request."""
    request = MagicMock()
    request.method = method
    request.url = MagicMock()
    request.url.path = path
    request.headers = headers or {}
    request.client = MagicMock()
    request.client.host = client_host
    request.state = MagicMock()
    return request


def _make_user_wrapper(**overrides):
    defaults = {
        "id": "u-1",
        "tenant_id": "t-1",
        "email": "user@test.com",
        "role": "member",
        "is_active": True,
    }
    defaults.update(overrides)
    user = MagicMock()
    for k, v in defaults.items():
        type(user).__dict__  # force MagicMock to not auto-create
        setattr(user, k, v)
    return user


def _make_api_key_wrapper(**overrides):
    defaults = {
        "id": "key-1",
        "user_id": "u-1",
        "rate_limit_per_minute": 100,
        "scopes": ["pool:read", "pool:write"],
        "is_active": True,
    }
    defaults.update(overrides)
    key = MagicMock()
    for k, v in defaults.items():
        setattr(key, k, v)
    return key


class TestMiddlewarePublicPaths:

    def test_health_is_public(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_public_path("/health") is True

    def test_login_is_public(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_public_path("/api/auth/login") is True

    def test_docs_prefix_is_public(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_public_path("/docs/some/path") is True

    def test_api_path_is_not_public(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_public_path("/api/v1/pools") is False

    def test_verify_and_resend_are_public(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_public_path("/api/auth/verify-email") is True
        assert middleware._is_public_path("/api/auth/resend-verification") is True


class TestMiddlewareDevMode:

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    async def test_dev_mode_sets_dev_credentials(self, mock_settings):
        mock_settings.runenv = "dev"
        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(path="/api/v1/pools")
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert request.state.user_id == "dev-user"
        assert request.state.tenant_id == "dev-tenant"
        assert response.status_code == 200


class TestMiddlewareAPIKeyAuth:

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_valid_api_key_proceeds(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        user = _make_user_wrapper()

        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=True)
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.api_key_has_scope = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"X-API-Key": "optiq_testkey"})
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        assert request.state.user_id == "u-1"
        assert request.state.tenant_id == "t-1"

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_invalid_api_key_returns_401(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"
        # api key validation returns None (invalid key)
        mock_auth_op.validate_api_key = AsyncMock(return_value=None)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"X-API-Key": "optiq_badkey"})
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        # should get a 401 JSONResponse since no valid auth found
        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_rate_limited_returns_429(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=False)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(
            method="POST",
            path="/api/v1/agent/select",
            headers={"X-API-Key": "optiq_testkey"},
        )
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 429

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_non_agent_path_skips_rate_limit(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        """management endpoints like /api/v1/pools should not be rate-limited."""
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        user = _make_user_wrapper()
        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=False)
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.api_key_has_scope = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"X-API-Key": "optiq_testkey"})
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        mock_auth_op.check_api_key_rate_limit.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_inactive_user_returns_401(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        user = _make_user_wrapper(is_active=False)

        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=True)
        mock_auth_op.get_user = AsyncMock(return_value=user)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"X-API-Key": "optiq_testkey"})
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401


class TestMiddlewareBearerAPIKey:
    """test the code path where an optiq_ api key is passed as a Bearer token."""

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_bearer_optiq_key_valid(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        user = _make_user_wrapper()

        # no X-API-Key header → validate_api_key only called once (Bearer path)
        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=True)
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.api_key_has_scope = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"Authorization": "Bearer optiq_my_api_key"})
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        assert request.state.user_id == "u-1"

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_bearer_optiq_key_rate_limited(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=False)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(
            method="POST",
            path="/api/v1/agent/select",
            headers={"Authorization": "Bearer optiq_my_api_key"},
        )
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 429

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_no_auth_header_returns_401(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        """no X-API-Key and no Authorization header at all."""
        mock_settings.runenv = "prod"

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={})
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401


class TestMiddlewareJWTAuth:

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_valid_jwt_proceeds(self, mock_token_op, mock_auth_op, mock_settings):
        mock_settings.runenv = "prod"

        user = _make_user_wrapper()
        mock_token_op.get_user_id_from_token = MagicMock(return_value="u-1")
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.check_user_rate_limit = AsyncMock(return_value=True)
        mock_auth_op.user_has_permission = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"Authorization": "Bearer some.jwt.token"})
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_invalid_jwt_returns_401(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        mock_token_op.get_user_id_from_token = MagicMock(return_value=None)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"Authorization": "Bearer bad.token"})
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_jwt_inactive_user_returns_401(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        user = _make_user_wrapper(is_active=False)
        mock_token_op.get_user_id_from_token = MagicMock(return_value="u-1")
        mock_auth_op.get_user = AsyncMock(return_value=user)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(headers={"Authorization": "Bearer some.jwt.token"})
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401


class TestMiddlewareScopeCheck:

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_insufficient_scope_returns_403(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        user = _make_user_wrapper()
        mock_token_op.get_user_id_from_token = MagicMock(return_value="u-1")
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.check_user_rate_limit = AsyncMock(return_value=True)
        # user does NOT have permission
        mock_auth_op.user_has_permission = AsyncMock(return_value=False)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        # hit a path that requires a scope
        request = _make_request(
            method="POST",
            path="/api/v1/pools",
            headers={"Authorization": "Bearer valid.jwt.token"},
        )
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_no_scope_required_proceeds(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"

        user = _make_user_wrapper()
        mock_token_op.get_user_id_from_token = MagicMock(return_value="u-1")
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.check_user_rate_limit = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        # hit a path with no scope mapping
        request = _make_request(
            method="GET",
            path="/api/v1/some-unmapped-path",
            headers={"Authorization": "Bearer valid.jwt.token"},
        )
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200


class TestMiddlewareOptions:

    @pytest.mark.asyncio
    async def test_options_bypasses_auth(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(method="OPTIONS", path="/api/v1/pools")
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200


class TestMiddlewareRateLimitExemptPaths:

    def test_agent_paths_are_rate_limited(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_rate_limited("/api/v1/agent/select") is True
        assert middleware._is_rate_limited("/api/v1/agent/feedback") is True

    def test_non_agent_paths_are_not_rate_limited(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_rate_limited("/api/v1/pools") is False
        assert middleware._is_rate_limited("/api/v1/experiments") is False
        assert middleware._is_rate_limited("/api/v1/runtime/redis/health") is False
        assert middleware._is_rate_limited("/api/auth/api-keys") is False

    def test_runtime_path_is_not_public(self):
        """runtime paths are authenticated — not in public_paths."""
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_public_path("/api/v1/runtime/redis/health") is False

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_management_path_skips_rate_limit_for_api_key(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        """a rate-limited api key should still reach non-agent endpoints."""
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        user = _make_user_wrapper()

        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        # rate limit would reject but should not be called
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=False)
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.api_key_has_scope = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(
            path="/api/v1/runtime/redis/health",
            headers={"X-API-Key": "optiq_testkey"},
        )
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        mock_auth_op.check_api_key_rate_limit.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_management_path_skips_rate_limit_for_jwt(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        """a rate-limited jwt user should still reach non-agent endpoints."""
        mock_settings.runenv = "prod"

        user = _make_user_wrapper()
        mock_token_op.get_user_id_from_token = MagicMock(return_value="u-1")
        mock_auth_op.get_user = AsyncMock(return_value=user)
        # rate limit would reject but should not be called
        mock_auth_op.check_user_rate_limit = AsyncMock(return_value=False)
        mock_auth_op.user_has_permission = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(
            path="/api/v1/runtime/motor/health",
            headers={"Authorization": "Bearer some.jwt.token"},
        )
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        mock_auth_op.check_user_rate_limit.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_agent_path_still_rate_limited(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        """verify rate limiting is enforced on operational agent paths."""
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=False)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(
            method="POST",
            path="/api/v1/agent/feedback",
            headers={"X-API-Key": "optiq_testkey"},
        )
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 429
        mock_auth_op.check_api_key_rate_limit.assert_called_once()


class TestMiddlewareAuthEndpointRateLimit:
    """ip-based throttling for unauthenticated auth endpoints."""

    def test_forgot_and_reset_are_public(self):
        app = MagicMock()
        middleware = AuthMiddleware(app)
        assert middleware._is_public_path("/api/auth/forgot-password") is True
        assert middleware._is_public_path("/api/auth/reset-password") is True

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_login_over_ip_limit_returns_429_with_retry_after(
        self, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"
        mock_auth_op.check_auth_endpoint_rate_limit = AsyncMock(
            return_value=(False, 30)
        )

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(method="POST", path="/api/auth/login")
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "30"
        call_next.assert_not_called()
        mock_auth_op.check_auth_endpoint_rate_limit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_login_under_ip_limit_proceeds(self, mock_auth_op, mock_settings):
        mock_settings.runenv = "prod"
        mock_auth_op.check_auth_endpoint_rate_limit = AsyncMock(return_value=(True, 59))

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(method="POST", path="/api/auth/login")
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        # login is public — after the limiter passes it proceeds to the route
        assert response.status_code == 200
        mock_auth_op.check_auth_endpoint_rate_limit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_dev_mode_bypasses_auth_endpoint_limiter(
        self, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "dev"
        mock_auth_op.check_auth_endpoint_rate_limit = AsyncMock(
            return_value=(False, 30)
        )

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(method="POST", path="/api/auth/login")
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        mock_auth_op.check_auth_endpoint_rate_limit.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_non_auth_path_skips_auth_endpoint_limiter(
        self, mock_token_op, mock_auth_op, mock_settings
    ):
        mock_settings.runenv = "prod"
        mock_auth_op.check_auth_endpoint_rate_limit = AsyncMock(
            return_value=(False, 30)
        )

        api_key = _make_api_key_wrapper()
        user = _make_user_wrapper()
        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=True)
        mock_auth_op.get_user = AsyncMock(return_value=user)
        mock_auth_op.api_key_has_scope = AsyncMock(return_value=True)

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(
            path="/api/v1/pools", headers={"X-API-Key": "optiq_testkey"}
        )
        expected_response = MagicMock()
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        mock_auth_op.check_auth_endpoint_rate_limit.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.auth.middleware.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_principal_limiter_429_carries_retry_after(
        self, mock_auth_op, mock_settings
    ):
        """the existing per-principal limiter now also returns Retry-After."""
        mock_settings.runenv = "prod"

        api_key = _make_api_key_wrapper()
        mock_auth_op.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_op.check_api_key_rate_limit = AsyncMock(return_value=False)
        # not an auth endpoint, so the auth-endpoint limiter is not consulted
        mock_auth_op.check_auth_endpoint_rate_limit = AsyncMock(return_value=(True, 0))

        app = MagicMock()
        middleware = AuthMiddleware(app)

        request = _make_request(
            method="POST",
            path="/api/v1/agent/select",
            headers={"X-API-Key": "optiq_testkey"},
        )
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 429
        assert "Retry-After" in response.headers


class TestMiddlewareAuthEndpointLimiterEndToEnd:
    """drive the full limiter stack: middleware → operator → service → redis."""

    @pytest.fixture
    async def middleware(self, monkeypatch):
        from fakeredis.aioredis import FakeRedis
        from qbrixstore.redis.client import RedisClient
        from proxysvc.mod.auth import AuthService
        from proxysvc.mod.auth import AuthOperator
        from proxysvc.config import ProxySettings
        from proxysvc.core.email import EmailService
        from proxysvc import edition
        import proxysvc.mod.auth.operator as op_module
        import proxysvc.transport.http.auth.middleware as mw_module

        fake = FakeRedis(decode_responses=True)
        redis_client = RedisClient()
        redis_client._client = fake
        operator = AuthOperator(
            AuthService(
                redis_client,
                EmailService(RecordingSender()),
                edition.entitlements(ProxySettings(), redis_client),
            )
        )

        monkeypatch.setattr(op_module, "auth_operator", operator)
        monkeypatch.setattr(mw_module.settings, "runenv", "prod")

        yield AuthMiddleware(MagicMock())
        await fake.aclose()

    @staticmethod
    async def _login(middleware, headers: dict | None = None) -> int:
        async def call_next(_request):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        request = _make_request(
            method="POST",
            path="/api/auth/login",
            headers=headers,
            client_host="172.18.0.2",
        )
        resp = await middleware.dispatch(request, call_next)
        if resp.status_code == 429:
            assert int(resp.headers["Retry-After"]) >= 1
        return resp.status_code

    @pytest.mark.asyncio
    async def test_login_ip_limit_enforced_through_real_redis(self, middleware):
        limit = constant.LOGIN_IP_PER_MIN
        for _ in range(limit):
            assert await self._login(middleware) == 200
        assert await self._login(middleware) == 429

    @pytest.mark.asyncio
    async def test_clients_behind_one_gateway_get_their_own_buckets(self, middleware):
        limit = constant.LOGIN_IP_PER_MIN
        for _ in range(limit):
            assert (
                await self._login(middleware, {"x-forwarded-for": "203.0.113.7"}) == 200
            )
        assert await self._login(middleware, {"x-forwarded-for": "203.0.113.7"}) == 429
        assert await self._login(middleware, {"x-forwarded-for": "198.51.100.9"}) == 200

    @pytest.mark.asyncio
    async def test_rotating_a_spoofed_cloudfront_header_does_not_evade(
        self, middleware
    ):
        limit = constant.LOGIN_IP_PER_MIN
        statuses = [
            await self._login(
                middleware,
                {
                    "cloudfront-viewer-address": f"6.6.6.{i}:443",
                    "x-forwarded-for": "203.0.113.7",
                },
            )
            for i in range(limit + 1)
        ]
        assert statuses[-1] == 429
