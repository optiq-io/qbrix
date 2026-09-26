from __future__ import annotations

import grpc

from qbrixlog import get_logger

from proxysvc.core.error import BaseAPIError
from proxysvc.core.error import BadPolicyParamsError
from proxysvc.core.error import ContextDimImmutableError
from proxysvc.core.error import ContextPropertiesError
from proxysvc.core.error import ContextSchemaImmutableError
from proxysvc.core.error import ContextVectorError
from proxysvc.core.error import ExperimentLimitError
from proxysvc.core.error import GateExistsError
from proxysvc.core.error import InvalidIdentityError
from proxysvc.core.error import LearnerExperimentDeleteError
from proxysvc.core.error import PoolHasExperimentsError
from proxysvc.core.error import SignupClosedError
from proxysvc.core.error import TokenError
from proxysvc.core.error import TokenExpiredError
from proxysvc.core.error import TokenInvalidError
from proxysvc.core.error import UsageLimitError
from proxysvc.transport.grpc.exception.base import AlreadyExistsException
from proxysvc.transport.grpc.exception.base import BaseGRPCException
from proxysvc.transport.grpc.exception.base import ExperimentLimitException
from proxysvc.transport.grpc.exception.base import UsageLimitException
from proxysvc.transport.grpc.exception.base import InternalException
from proxysvc.transport.grpc.exception.base import ContextDimImmutableException
from proxysvc.transport.grpc.exception.base import ContextSchemaImmutableException
from proxysvc.transport.grpc.exception.base import InvalidContextPropertiesException
from proxysvc.transport.grpc.exception.base import InvalidContextVectorException
from proxysvc.transport.grpc.exception.base import InvalidIdentityException
from proxysvc.transport.grpc.exception.base import InvalidPolicyParamsException
from proxysvc.transport.grpc.exception.base import LearnerExperimentDeleteException
from proxysvc.transport.grpc.exception.base import PoolHasExperimentsException
from proxysvc.transport.grpc.exception.base import SignupClosedException
from proxysvc.transport.grpc.exception.base import TokenExpiredException
from proxysvc.transport.grpc.exception.base import TokenInvalidException

logger = get_logger(__name__)

# maps domain errors (BaseAPIError subclasses) to their grpc counterpart.
# fallback for unmapped errors is InternalException.
_DOMAIN_TO_GRPC: dict[type[BaseAPIError], type[BaseGRPCException]] = {
    PoolHasExperimentsError: PoolHasExperimentsException,
    BadPolicyParamsError: InvalidPolicyParamsException,
    ContextVectorError: InvalidContextVectorException,
    ContextSchemaImmutableError: ContextSchemaImmutableException,
    ContextDimImmutableError: ContextDimImmutableException,
    ContextPropertiesError: InvalidContextPropertiesException,
    ExperimentLimitError: ExperimentLimitException,
    GateExistsError: AlreadyExistsException,
    UsageLimitError: UsageLimitException,
    SignupClosedError: SignupClosedException,
    InvalidIdentityError: InvalidIdentityException,
    LearnerExperimentDeleteError: LearnerExperimentDeleteException,
    TokenExpiredError: TokenExpiredException,
    TokenInvalidError: TokenInvalidException,
    TokenError: TokenInvalidException,
}


class ExceptionInterceptor(grpc.aio.ServerInterceptor):
    """grpc server interceptor that converts typed exceptions to grpc status codes.

    catch order:
    1. BaseGRPCException — abort directly with its status_code and detail.
    2. BaseAPIError — map via _DOMAIN_TO_GRPC, then abort. fallback is INTERNAL.
    3. anything else — log and abort with INTERNAL (detail not leaked).
    """

    async def intercept_service(self, continuation, handler_call_details):
        handler = await continuation(handler_call_details)
        if handler is None:
            return handler
        return _wrap_handler(handler)


def _wrap_handler(handler):
    """wrap a grpc handler to catch and convert exceptions."""
    if handler.unary_unary:
        return grpc.unary_unary_rpc_method_handler(
            _wrap_unary_unary(handler.unary_unary),  # type: ignore[arg-type]
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.unary_stream:
        return grpc.unary_stream_rpc_method_handler(
            _wrap_unary_stream(handler.unary_stream),  # type: ignore[arg-type]
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.stream_unary:
        return grpc.stream_unary_rpc_method_handler(
            _wrap_stream_unary(handler.stream_unary),  # type: ignore[arg-type]
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    if handler.stream_stream:
        return grpc.stream_stream_rpc_method_handler(
            _wrap_stream_stream(handler.stream_stream),  # type: ignore[arg-type]
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
    return handler


def _wrap_unary_unary(behavior):
    """wrap a unary-unary handler with exception conversion."""

    async def wrapper(request, context):
        try:
            return await behavior(request, context)
        except BaseGRPCException as exc:
            await context.abort(exc.status_code, exc.detail)
        except BaseAPIError as exc:
            grpc_exc = _map_domain_error(exc)
            await context.abort(grpc_exc.status_code, grpc_exc.detail)
        except Exception:  # noqa
            logger.exception("unhandled exception in grpc handler")
            await context.abort(InternalException.status_code, InternalException.detail)

    return wrapper


def _wrap_unary_stream(behavior):
    """wrap a unary-stream handler with exception conversion."""

    async def wrapper(request, context):
        try:
            async for response in behavior(request, context):
                yield response
        except BaseGRPCException as exc:
            await context.abort(exc.status_code, exc.detail)
        except BaseAPIError as exc:
            grpc_exc = _map_domain_error(exc)
            await context.abort(grpc_exc.status_code, grpc_exc.detail)
        except Exception:  # noqa
            logger.exception("unhandled exception in grpc streaming handler")
            await context.abort(InternalException.status_code, InternalException.detail)

    return wrapper


def _wrap_stream_unary(behavior):
    """wrap a stream-unary handler with exception conversion."""

    async def wrapper(request_iterator, context):
        try:
            return await behavior(request_iterator, context)
        except BaseGRPCException as exc:
            await context.abort(exc.status_code, exc.detail)
        except BaseAPIError as exc:
            grpc_exc = _map_domain_error(exc)
            await context.abort(grpc_exc.status_code, grpc_exc.detail)
        except Exception:  # noqa
            logger.exception("unhandled exception in grpc stream-unary handler")
            await context.abort(InternalException.status_code, InternalException.detail)

    return wrapper


def _wrap_stream_stream(behavior):
    """wrap a stream-stream handler with exception conversion."""

    async def wrapper(request_iterator, context):
        try:
            async for response in behavior(request_iterator, context):
                yield response
        except BaseGRPCException as exc:
            await context.abort(exc.status_code, exc.detail)
        except BaseAPIError as exc:
            grpc_exc = _map_domain_error(exc)
            await context.abort(grpc_exc.status_code, grpc_exc.detail)
        except Exception:  # noqa
            logger.exception("unhandled exception in grpc stream-stream handler")
            await context.abort(InternalException.status_code, InternalException.detail)

    return wrapper


def _map_domain_error(exc: BaseAPIError) -> BaseGRPCException:
    """map a domain error to its grpc exception counterpart."""
    grpc_cls = _DOMAIN_TO_GRPC.get(type(exc))
    if grpc_cls is not None:
        return grpc_cls(str(exc))
    logger.error("unmapped domain error: %s: %s", type(exc).__name__, exc)
    return InternalException()
