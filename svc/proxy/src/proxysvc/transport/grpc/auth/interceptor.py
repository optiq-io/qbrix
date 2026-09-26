from __future__ import annotations

import grpc

from qbrixlog import get_logger

from proxysvc.config import ProxySettings
from proxysvc.mod.auth.scope import ROLE_SCOPES
from proxysvc.mod.auth.scope import RPC_SCOPES
from proxysvc.transport.grpc.auth.context import GRPCAuthContext, set_grpc_auth_context
from proxysvc.mod.auth import operator
from proxysvc.mod.auth.constant import DEV_USER_ID, DEV_TENANT_ID, DEV_USER_ROLE
from proxysvc.mod.auth.model import Role

logger = get_logger(__name__)

# rpc methods that skip authentication
PUBLIC_METHODS = frozenset(
    {
        "/qbrix.proxy.ProxyService/Health",
        "/qbrix.proxy.ProxyService/ListPolicies",
        "/qbrix.auth.AuthService/RegisterUser",
        "/qbrix.auth.AuthService/AuthenticateUser",
    }
)

# only operational (hot-path) rpc methods are rate-limited
RATE_LIMITED_METHODS = frozenset(
    {
        "/qbrix.proxy.ProxyService/Select",
        "/qbrix.proxy.ProxyService/Feedback",
    }
)


class AuthInterceptor(grpc.aio.ServerInterceptor):
    """grpc server interceptor for authentication and authorization.

    mirrors the http AuthMiddleware logic:
    1. extracts credentials from grpc metadata (x-api-key or authorization header)
    2. validates via the auth and token operators
    3. checks scopes against RPC_SCOPES
    4. sets GRPCAuthContext for handler access via contextvars
    """

    def __init__(self, settings: ProxySettings):
        self._settings = settings

    async def intercept_service(self, continuation, handler_call_details):
        method = handler_call_details.method
        metadata = dict(handler_call_details.invocation_metadata or [])

        handler = await continuation(handler_call_details)
        if handler is None:
            return handler

        # public endpoints skip auth
        if method in PUBLIC_METHODS:
            return handler

        # in dev mode, use the dev credentials
        if self._settings.runenv == "dev":
            logger.debug("development mode: bypassing grpc auth for %s", method)
            return _wrap_handler(
                handler,
                GRPCAuthContext(
                    tenant_id=DEV_TENANT_ID,
                    user_id=DEV_USER_ID,
                    role=DEV_USER_ROLE,
                    scopes=ROLE_SCOPES.get(Role.ADMIN.value, []),
                ),
            )

        # authenticate — only rate-limit operational rpc methods
        try:
            apply_rate_limit = method in RATE_LIMITED_METHODS
            auth_ctx = await self._authenticate(metadata, apply_rate_limit)
        except _AuthError as e:
            return _error_handler(handler, grpc.StatusCode.UNAUTHENTICATED, str(e))

        required_scope = RPC_SCOPES.get(
            method
        )  # authorize: check required scope for this rpc method
        if required_scope:
            if (
                required_scope not in auth_ctx.scopes
                and "system:admin" not in auth_ctx.scopes
            ):
                return _error_handler(
                    handler,
                    grpc.StatusCode.PERMISSION_DENIED,
                    f"missing required scope: {required_scope}",
                )

        return _wrap_handler(handler, auth_ctx)

    async def _authenticate(
        self, metadata: dict, apply_rate_limit: bool = True
    ) -> GRPCAuthContext:
        """extract and validate credentials from grpc metadata."""
        api_key_value = metadata.get("x-api-key")

        if api_key_value:
            return await self._authenticate_api_key(api_key_value, apply_rate_limit)

        auth_header = metadata.get("authorization")
        if not auth_header:
            raise _AuthError(
                "authentication required - provide x-api-key or authorization metadata"
            )

        if not auth_header.startswith("Bearer "):
            raise _AuthError("invalid authorization format - use 'Bearer <token>'")

        token = auth_header[7:]

        # api key passed via bearer header
        if token.startswith("optiq_"):
            return await self._authenticate_api_key(token, apply_rate_limit)

        # jwt token
        return await self._authenticate_jwt(token, apply_rate_limit)

    @staticmethod
    async def _authenticate_api_key(
        plain_key: str, apply_rate_limit: bool = True
    ) -> GRPCAuthContext:
        """validate api key and resolve user context."""
        api_key = await operator.auth_operator.validate_api_key(plain_key)
        if not api_key:
            raise _AuthError("invalid api key")

        user = await operator.auth_operator.get_user(api_key.user_id)
        if not user or not user.is_active:
            raise _AuthError("user account is inactive")

        if (
            apply_rate_limit
            and not await operator.auth_operator.check_api_key_rate_limit(api_key)
        ):
            raise _AuthError(
                f"rate limit exceeded: {api_key.rate_limit_per_minute} requests per minute"
            )

        return GRPCAuthContext(
            tenant_id=user.tenant_id,
            user_id=user.id,
            role=user.role,
            scopes=api_key.scopes,
        )

    @staticmethod
    async def _authenticate_jwt(
        token: str, apply_rate_limit: bool = True
    ) -> GRPCAuthContext:
        """validate jwt token and resolve user context."""
        user_id = operator.token_operator.get_user_id_from_token(token)
        if not user_id:
            raise _AuthError("invalid or expired authentication token")

        user = await operator.auth_operator.get_user(user_id)
        if not user or not user.is_active:
            raise _AuthError("user account is inactive or not found")

        if apply_rate_limit and not await operator.auth_operator.check_user_rate_limit(
            user
        ):
            raise _AuthError("rate limit exceeded")

        scopes = ROLE_SCOPES.get(user.role, [])
        return GRPCAuthContext(
            tenant_id=user.tenant_id,
            user_id=user.id,
            role=user.role,
            scopes=scopes,
        )


class _AuthError(Exception):
    """internal exception for auth failures within the interceptor."""

    pass


def _wrap_handler(handler, auth_ctx: GRPCAuthContext):
    """wrap a grpc handler to inject auth context before execution."""
    if handler.unary_unary:
        return grpc.unary_unary_rpc_method_handler(
            _wrap_unary_unary(handler.unary_unary, auth_ctx),  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.unary_stream:
        return grpc.unary_stream_rpc_method_handler(
            _wrap_unary_stream(handler.unary_stream, auth_ctx),  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.stream_unary:
        return grpc.stream_unary_rpc_method_handler(
            _wrap_stream_unary(handler.stream_unary, auth_ctx),  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.stream_stream:
        return grpc.stream_stream_rpc_method_handler(
            _wrap_stream_stream(handler.stream_stream, auth_ctx),  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    return handler


def _wrap_unary_unary(behavior, auth_ctx: GRPCAuthContext):
    """wrap a unary-unary handler to set auth context."""

    async def wrapper(request, context):
        set_grpc_auth_context(auth_ctx)
        return await behavior(request, context)

    return wrapper


def _wrap_unary_stream(behavior, auth_ctx: GRPCAuthContext):
    """wrap a unary-stream handler to set auth context."""

    async def wrapper(request, context):
        set_grpc_auth_context(auth_ctx)
        async for response in behavior(request, context):
            yield response

    return wrapper


def _wrap_stream_unary(behavior, auth_ctx: GRPCAuthContext):
    """wrap a stream-unary handler to set auth context."""

    async def wrapper(request_iterator, context):
        set_grpc_auth_context(auth_ctx)
        return await behavior(request_iterator, context)

    return wrapper


def _wrap_stream_stream(behavior, auth_ctx: GRPCAuthContext):
    """wrap a stream-stream handler to set auth context."""

    async def wrapper(request_iterator, context):
        set_grpc_auth_context(auth_ctx)
        async for response in behavior(request_iterator, context):
            yield response

    return wrapper


def _error_handler(handler, code, details):
    """return a handler that immediately returns an error."""

    async def error_behavior(request, context):  # noqa
        await context.abort(code, details)

    if handler.unary_unary:
        return grpc.unary_unary_rpc_method_handler(
            error_behavior,  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.unary_stream:
        return grpc.unary_stream_rpc_method_handler(
            error_behavior,  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.stream_unary:
        return grpc.stream_unary_rpc_method_handler(
            error_behavior,  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.stream_stream:
        return grpc.stream_stream_rpc_method_handler(
            error_behavior,  # noqa
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    return handler
