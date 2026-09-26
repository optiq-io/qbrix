"""unit tests for grpc auth interceptor."""

from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest

from proxysvc.config import ProxySettings
from proxysvc.transport.grpc.auth.context import (
    GRPCAuthContext,
    get_grpc_auth_context,
    set_grpc_auth_context,
)
from proxysvc.transport.grpc.auth.interceptor import (
    AuthInterceptor,
    PUBLIC_METHODS,
    _wrap_handler,
    _error_handler,
)


def _make_handler_call_details(method, metadata=None):
    """create a mock HandlerCallDetails."""
    details = MagicMock()
    details.method = method
    details.invocation_metadata = [(k, v) for k, v in (metadata or {}).items()]
    return details


def _make_handler():
    """create a mock unary-unary rpc method handler."""
    handler = MagicMock()
    handler.unary_unary = AsyncMock(return_value="response")
    handler.unary_stream = None
    handler.stream_unary = None
    handler.stream_stream = None
    handler.request_deserializer = MagicMock()
    handler.response_serializer = MagicMock()
    return handler


def _make_user(tenant_id="t-1", user_id="u-1", role="member", is_active=True):
    """create a mock user object."""
    user = MagicMock()
    user.tenant_id = tenant_id
    user.id = user_id
    user.role = role
    user.is_active = is_active
    return user


def _make_api_key(user_id="u-1", scopes=None, rate_limit=1000):
    """create a mock api key object."""
    api_key = MagicMock()
    api_key.user_id = user_id
    api_key.scopes = scopes or [
        "pool:read",
        "pool:write",
        "experiment:read",
        "experiment:write",
    ]
    api_key.rate_limit_per_minute = rate_limit
    return api_key


class TestAuthInterceptorPublicMethods:
    """test that public methods skip authentication."""

    @pytest.mark.asyncio
    async def test_health_skips_auth(self):
        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details("/qbrix.proxy.ProxyService/Health")

        result = await interceptor.intercept_service(continuation, details)
        # should return the original handler unchanged
        assert result is handler

    @pytest.mark.asyncio
    async def test_register_user_skips_auth(self):
        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details("/qbrix.auth.AuthService/RegisterUser")

        result = await interceptor.intercept_service(continuation, details)
        assert result is handler

    @pytest.mark.asyncio
    async def test_authenticate_user_skips_auth(self):
        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details("/qbrix.auth.AuthService/AuthenticateUser")

        result = await interceptor.intercept_service(continuation, details)
        assert result is handler

    @pytest.mark.asyncio
    async def test_public_methods_list(self):
        assert "/qbrix.proxy.ProxyService/Health" in PUBLIC_METHODS
        assert "/qbrix.auth.AuthService/RegisterUser" in PUBLIC_METHODS
        assert "/qbrix.auth.AuthService/AuthenticateUser" in PUBLIC_METHODS


class TestAuthInterceptorDevMode:
    """test dev mode bypass."""

    @pytest.mark.asyncio
    async def test_dev_mode_sets_dev_context(self):
        settings = ProxySettings(runenv="dev")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details("/qbrix.proxy.ProxyService/CreatePool")

        result = await interceptor.intercept_service(continuation, details)

        # result should be a wrapped handler, not the original
        assert result is not handler

        # invoke the wrapped handler to verify context is set
        mock_request = MagicMock()
        mock_context = MagicMock()

        # cleanup before test
        set_grpc_auth_context(None)
        await result.unary_unary(mock_request, mock_context)

        ctx = get_grpc_auth_context()
        assert ctx is not None
        assert ctx.tenant_id == "dev-tenant"
        assert ctx.user_id == "dev-user"
        assert ctx.role == "admin"
        assert len(ctx.scopes) > 0
        # cleanup
        set_grpc_auth_context(None)

    @pytest.mark.asyncio
    async def test_dev_mode_no_metadata_needed(self):
        """dev mode should work even without any auth metadata."""
        settings = ProxySettings(runenv="dev")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={},  # empty metadata
        )

        result = await interceptor.intercept_service(continuation, details)
        assert result is not handler  # wrapped, not rejected


class TestAuthInterceptorAPIKey:
    """test api key authentication flow."""

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_valid_api_key_via_metadata(self, mock_auth_operator):
        user = _make_user(tenant_id="t-123", user_id="u-456", role="member")
        api_key = _make_api_key(user_id="u-456", scopes=["pool:write"])

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_api_key_rate_limit = AsyncMock(return_value=True)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={"x-api-key": "optiq_testkey123"},
        )

        result = await interceptor.intercept_service(continuation, details)

        # invoke to verify context
        set_grpc_auth_context(None)
        mock_request = MagicMock()
        mock_context = MagicMock()
        await result.unary_unary(mock_request, mock_context)

        ctx = get_grpc_auth_context()
        assert ctx.tenant_id == "t-123"
        assert ctx.user_id == "u-456"
        assert ctx.scopes == ["pool:write"]

        mock_auth_operator.validate_api_key.assert_awaited_once_with("optiq_testkey123")
        set_grpc_auth_context(None)

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_valid_api_key_via_bearer(self, mock_auth_operator):
        """api key passed via authorization: Bearer optiq_... should work."""
        user = _make_user(tenant_id="t-123")
        api_key = _make_api_key(scopes=["pool:write"])

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_api_key_rate_limit = AsyncMock(return_value=True)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={"authorization": "Bearer optiq_testkey123"},
        )

        result = await interceptor.intercept_service(continuation, details)

        set_grpc_auth_context(None)
        await result.unary_unary(MagicMock(), MagicMock())

        ctx = get_grpc_auth_context()
        assert ctx.tenant_id == "t-123"
        set_grpc_auth_context(None)

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_invalid_api_key(self, mock_auth_operator):
        mock_auth_operator.validate_api_key = AsyncMock(return_value=None)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={"x-api-key": "optiq_invalid"},
        )

        result = await interceptor.intercept_service(continuation, details)

        # the error handler should abort with UNAUTHENTICATED
        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        args = mock_context.abort.call_args
        assert args[0][0] == grpc.StatusCode.UNAUTHENTICATED

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_inactive_user_via_api_key(self, mock_auth_operator):
        api_key = _make_api_key()
        user = _make_user(is_active=False)

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={"x-api-key": "optiq_testkey"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.UNAUTHENTICATED

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_rate_limited_api_key_on_agent_path(self, mock_auth_operator):
        api_key = _make_api_key(rate_limit=100)
        user = _make_user()

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_api_key_rate_limit = AsyncMock(return_value=False)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/Select",
            metadata={"x-api-key": "optiq_testkey"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.UNAUTHENTICATED
        assert "rate limit" in mock_context.abort.call_args[0][1].lower()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_management_path_skips_rate_limit(self, mock_auth_operator):
        """non-agent rpc methods should not be rate-limited."""
        api_key = _make_api_key(rate_limit=100)
        user = _make_user()

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_api_key_rate_limit = AsyncMock(return_value=False)
        mock_auth_operator.api_key_has_scope = AsyncMock(return_value=True)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={"x-api-key": "optiq_testkey"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_auth_operator.check_api_key_rate_limit.assert_not_called()


class TestAuthInterceptorJWT:
    """test jwt authentication flow."""

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_valid_jwt(self, mock_token_operator, mock_auth_operator):
        user = _make_user(tenant_id="t-jwt", user_id="u-jwt", role="member")

        mock_token_operator.get_user_id_from_token = MagicMock(return_value="u-jwt")
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_user_rate_limit = AsyncMock(return_value=True)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/GetPool",
            metadata={"authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.fake"},
        )

        result = await interceptor.intercept_service(continuation, details)

        set_grpc_auth_context(None)
        await result.unary_unary(MagicMock(), MagicMock())

        ctx = get_grpc_auth_context()
        assert ctx.tenant_id == "t-jwt"
        assert ctx.user_id == "u-jwt"
        assert ctx.role == "member"

        mock_token_operator.get_user_id_from_token.assert_called_once()
        set_grpc_auth_context(None)

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_invalid_jwt(self, mock_token_operator):
        mock_token_operator.get_user_id_from_token = MagicMock(return_value=None)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/GetPool",
            metadata={"authorization": "Bearer invalid.jwt.token"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.UNAUTHENTICATED

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_jwt_inactive_user(self, mock_token_operator, mock_auth_operator):
        user = _make_user(is_active=False)
        mock_token_operator.get_user_id_from_token = MagicMock(return_value="u-1")
        mock_auth_operator.get_user = AsyncMock(return_value=user)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/GetPool",
            metadata={"authorization": "Bearer some.jwt.token"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.UNAUTHENTICATED

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    @patch("proxysvc.mod.auth.operator.token_operator")
    async def test_jwt_rate_limited_on_agent_path(
        self, mock_token_operator, mock_auth_operator
    ):
        user = _make_user()
        mock_token_operator.get_user_id_from_token = MagicMock(return_value="u-1")
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_user_rate_limit = AsyncMock(return_value=False)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/Feedback",
            metadata={"authorization": "Bearer some.jwt.token"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.UNAUTHENTICATED


class TestAuthInterceptorMissingCredentials:
    """test missing or malformed credentials."""

    @pytest.mark.asyncio
    async def test_no_metadata_returns_unauthenticated(self):
        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.UNAUTHENTICATED

    @pytest.mark.asyncio
    async def test_malformed_authorization_header(self):
        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",
            metadata={"authorization": "Basic dXNlcjpwYXNz"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.UNAUTHENTICATED


class TestAuthInterceptorScopeAuthorization:
    """test scope-based authorization."""

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_sufficient_scope_allowed(self, mock_auth_operator):
        user = _make_user()
        api_key = _make_api_key(scopes=["pool:write", "pool:read"])

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_api_key_rate_limit = AsyncMock(return_value=True)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",  # requires pool:write
            metadata={"x-api-key": "optiq_testkey"},
        )

        result = await interceptor.intercept_service(continuation, details)

        # should be a wrapped handler, not error handler
        set_grpc_auth_context(None)
        await result.unary_unary(MagicMock(), MagicMock())
        ctx = get_grpc_auth_context()
        assert ctx is not None
        assert ctx.tenant_id == "t-1"
        set_grpc_auth_context(None)

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_insufficient_scope_denied(self, mock_auth_operator):
        user = _make_user()
        api_key = _make_api_key(scopes=["pool:read"])  # only read, not write

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_api_key_rate_limit = AsyncMock(return_value=True)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/CreatePool",  # requires pool:write
            metadata={"x-api-key": "optiq_testkey"},
        )

        result = await interceptor.intercept_service(continuation, details)

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()
        await result.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once()
        assert mock_context.abort.call_args[0][0] == grpc.StatusCode.PERMISSION_DENIED
        assert "pool:write" in mock_context.abort.call_args[0][1]

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_system_admin_bypasses_scope_check(self, mock_auth_operator):
        user = _make_user(role="admin")
        api_key = _make_api_key(scopes=["system:admin"])

        mock_auth_operator.validate_api_key = AsyncMock(return_value=api_key)
        mock_auth_operator.get_user = AsyncMock(return_value=user)
        mock_auth_operator.check_api_key_rate_limit = AsyncMock(return_value=True)

        settings = ProxySettings(runenv="production")
        interceptor = AuthInterceptor(settings)

        handler = _make_handler()
        continuation = AsyncMock(return_value=handler)
        details = _make_handler_call_details(
            "/qbrix.proxy.ProxyService/DeleteExperiment",  # requires experiment:delete
            metadata={"x-api-key": "optiq_adminkey"},
        )

        result = await interceptor.intercept_service(continuation, details)

        # admin should pass even without explicit experiment:delete scope
        set_grpc_auth_context(None)
        await result.unary_unary(MagicMock(), MagicMock())
        ctx = get_grpc_auth_context()
        assert ctx is not None
        set_grpc_auth_context(None)


class TestWrapHandler:
    """test handler wrapping utility."""

    @pytest.mark.asyncio
    async def test_wrap_sets_context(self):
        handler = _make_handler()
        ctx = GRPCAuthContext(tenant_id="t-1", user_id="u-1", role="admin", scopes=[])

        wrapped = _wrap_handler(handler, ctx)

        set_grpc_auth_context(None)
        await wrapped.unary_unary(MagicMock(), MagicMock())

        assert get_grpc_auth_context() is ctx
        set_grpc_auth_context(None)


class TestErrorHandler:
    """test error handler utility."""

    @pytest.mark.asyncio
    async def test_error_handler_aborts(self):
        handler = _make_handler()
        error = _error_handler(handler, grpc.StatusCode.UNAUTHENTICATED, "bad creds")

        mock_context = MagicMock()
        mock_context.abort = AsyncMock()

        await error.unary_unary(MagicMock(), mock_context)

        mock_context.abort.assert_awaited_once_with(
            grpc.StatusCode.UNAUTHENTICATED, "bad creds"
        )
