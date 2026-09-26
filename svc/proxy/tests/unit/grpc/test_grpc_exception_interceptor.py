"""unit tests for ExceptionInterceptor."""

from unittest.mock import AsyncMock, MagicMock

import grpc

from proxysvc.core.error import (
    BadPolicyParamsError,
    ContextVectorError,
    ExperimentLimitError,
    LearnerExperimentDeleteError,
    PoolHasExperimentsError,
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
)
from proxysvc.transport.grpc.exception.base import (
    BaseGRPCException,
    ExperimentLimitException,
    InternalException,
    PoolHasExperimentsException,
    PoolNotFoundException,
    TokenExpiredException,
    TokenInvalidException,
    UnauthenticatedException,
)
from proxysvc.transport.grpc.exception.interceptor import (
    ExceptionInterceptor,
    _wrap_handler,
    _wrap_unary_unary,
    _wrap_unary_stream,
)


def _make_handler(behavior=None, arity="unary_unary"):
    """create a mock grpc handler with a single active arity."""
    handler = MagicMock()
    handler.unary_unary = behavior if arity == "unary_unary" else None
    handler.unary_stream = behavior if arity == "unary_stream" else None
    handler.stream_unary = behavior if arity == "stream_unary" else None
    handler.stream_stream = behavior if arity == "stream_stream" else None
    handler.request_deserializer = MagicMock()
    handler.response_serializer = MagicMock()
    return handler


def _make_context():
    ctx = MagicMock()
    ctx.abort = AsyncMock()
    return ctx


class TestExceptionInterceptorIntegration:
    """test that intercept_service wraps the handler."""

    async def test_passes_through_successful_handler(self):
        interceptor = ExceptionInterceptor()
        behavior = AsyncMock(return_value="response")
        handler = _make_handler(behavior=behavior)
        continuation = AsyncMock(return_value=handler)
        details = MagicMock()

        result = await interceptor.intercept_service(continuation, details)
        assert result is not None

    async def test_returns_none_when_continuation_returns_none(self):
        interceptor = ExceptionInterceptor()
        continuation = AsyncMock(return_value=None)
        details = MagicMock()

        result = await interceptor.intercept_service(continuation, details)
        assert result is None


class TestUnaryUnaryExceptionMapping:
    """test all exception categories for unary-unary handlers."""

    async def test_base_grpc_exception_aborts_with_its_status(self):
        exc = PoolNotFoundException("pool not found: p-1")

        async def behavior(request, context):
            raise exc

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        context.abort.assert_awaited_once_with(
            grpc.StatusCode.NOT_FOUND, "pool not found: p-1"
        )

    async def test_unauthenticated_exception_uses_correct_code(self):
        async def behavior(request, context):
            raise UnauthenticatedException()

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        context.abort.assert_awaited_once_with(
            grpc.StatusCode.UNAUTHENTICATED, "unauthenticated"
        )

    async def test_pool_has_experiments_error_maps_to_failed_precondition(self):
        async def behavior(request, context):
            raise PoolHasExperimentsError("pool has experiments")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        # interceptor passes str(exc) as detail (preserves domain error message)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.FAILED_PRECONDITION
        assert detail == "pool has experiments"

    async def test_bad_policy_params_error_maps_to_invalid_argument(self):
        async def behavior(request, context):
            raise BadPolicyParamsError("bad params")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.INVALID_ARGUMENT
        assert detail == "bad params"

    async def test_context_vector_error_maps_to_invalid_argument(self):
        async def behavior(request, context):
            raise ContextVectorError("context.vector has width 3, experiment expects 4")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.INVALID_ARGUMENT
        assert detail == "context.vector has width 3, experiment expects 4"

    async def test_experiment_limit_error_maps_to_resource_exhausted(self):
        async def behavior(request, context):
            raise ExperimentLimitError("limit reached")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.RESOURCE_EXHAUSTED
        assert detail == "limit reached"

    async def test_learner_experiment_delete_error_maps_to_permission_denied(self):
        async def behavior(request, context):
            raise LearnerExperimentDeleteError("cannot delete learner")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.PERMISSION_DENIED
        assert detail == "cannot delete learner"

    async def test_token_expired_error_maps_to_deadline_exceeded(self):
        async def behavior(request, context):
            raise TokenExpiredError("token expired (5000ms > 3600000ms)")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.DEADLINE_EXCEEDED
        assert "expired" in detail

    async def test_token_invalid_error_maps_to_invalid_argument(self):
        async def behavior(request, context):
            raise TokenInvalidError("invalid signature")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.INVALID_ARGUMENT
        assert detail

    async def test_base_token_error_maps_to_invalid_argument(self):
        async def behavior(request, context):
            raise TokenError("generic token error")

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, _ = context.abort.call_args[0]
        assert code == grpc.StatusCode.INVALID_ARGUMENT

    async def test_unhandled_exception_aborts_with_internal_and_generic_detail(self):
        secret_message = "postgres connection string: password=supersecret"

        async def behavior(request, context):
            raise RuntimeError(secret_message)

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        await wrapper(MagicMock(), context)
        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.INTERNAL
        # must not leak the exception message
        assert secret_message not in detail
        assert detail == InternalException.detail

    async def test_successful_handler_returns_response(self):
        expected = MagicMock()

        async def behavior(request, context):
            return expected

        wrapper = _wrap_unary_unary(behavior)
        context = _make_context()

        result = await wrapper(MagicMock(), context)
        assert result is expected
        context.abort.assert_not_awaited()


class TestUnaryStreamExceptionMapping:
    """test exception handling for unary-stream handlers."""

    async def test_base_grpc_exception_aborts_streaming(self):
        async def behavior(request, context):
            yield "first-item"
            raise PoolNotFoundException("pool not found: p-1")

        wrapper = _wrap_unary_stream(behavior)
        context = _make_context()
        results = []

        async for item in wrapper(MagicMock(), context):
            results.append(item)

        assert results == ["first-item"]
        context.abort.assert_awaited_once_with(
            grpc.StatusCode.NOT_FOUND, "pool not found: p-1"
        )

    async def test_unhandled_exception_aborts_with_internal_in_stream(self):
        async def behavior(request, context):
            yield "item"
            raise ValueError("unexpected internal error")

        wrapper = _wrap_unary_stream(behavior)
        context = _make_context()

        async for _ in wrapper(MagicMock(), context):
            pass

        code, detail = context.abort.call_args[0]
        assert code == grpc.StatusCode.INTERNAL
        assert detail == InternalException.detail

    async def test_successful_stream_yields_all_items(self):
        async def behavior(request, context):
            yield "a"
            yield "b"
            yield "c"

        wrapper = _wrap_unary_stream(behavior)
        context = _make_context()
        results = []

        async for item in wrapper(MagicMock(), context):
            results.append(item)

        assert results == ["a", "b", "c"]
        context.abort.assert_not_awaited()


class TestWrapHandlerDispatching:
    """test that _wrap_handler selects the correct arity wrapper."""

    def test_wraps_unary_unary(self):
        behavior = AsyncMock()
        handler = _make_handler(behavior=behavior, arity="unary_unary")
        result = _wrap_handler(handler)
        # grpc creates a new handler object; verify it has the right arity attr
        assert result is not None

    def test_wraps_unary_stream(self):
        behavior = AsyncMock()
        handler = _make_handler(behavior=behavior, arity="unary_stream")
        result = _wrap_handler(handler)
        assert result is not None

    def test_wraps_stream_unary(self):
        behavior = AsyncMock()
        handler = _make_handler(behavior=behavior, arity="stream_unary")
        result = _wrap_handler(handler)
        assert result is not None

    def test_wraps_stream_stream(self):
        behavior = AsyncMock()
        handler = _make_handler(behavior=behavior, arity="stream_stream")
        result = _wrap_handler(handler)
        assert result is not None

    def test_passthrough_when_no_known_arity(self):
        handler = MagicMock()
        handler.unary_unary = None
        handler.unary_stream = None
        handler.stream_unary = None
        handler.stream_stream = None
        result = _wrap_handler(handler)
        assert result is handler


class TestBaseGRPCExceptionHierarchy:
    """verify the exception hierarchy is correct."""

    def test_pool_not_found_is_not_found(self):
        exc = PoolNotFoundException()
        assert isinstance(exc, BaseGRPCException)
        assert exc.status_code == grpc.StatusCode.NOT_FOUND

    def test_pool_has_experiments_is_failed_precondition(self):
        exc = PoolHasExperimentsException()
        assert exc.status_code == grpc.StatusCode.FAILED_PRECONDITION

    def test_experiment_limit_is_resource_exhausted(self):
        exc = ExperimentLimitException()
        assert exc.status_code == grpc.StatusCode.RESOURCE_EXHAUSTED

    def test_token_expired_is_deadline_exceeded(self):
        exc = TokenExpiredException()
        assert exc.status_code == grpc.StatusCode.DEADLINE_EXCEEDED

    def test_token_invalid_is_invalid_argument(self):
        exc = TokenInvalidException()
        assert exc.status_code == grpc.StatusCode.INVALID_ARGUMENT

    def test_custom_detail_overrides_default(self):
        exc = PoolNotFoundException("pool not found: abc-123")
        assert exc.detail == "pool not found: abc-123"
        assert str(exc) == "pool not found: abc-123"

    def test_default_detail_used_when_none_passed(self):
        exc = PoolNotFoundException()
        assert exc.detail == PoolNotFoundException.detail
