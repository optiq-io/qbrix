from __future__ import annotations

import grpc


class BaseGRPCException(Exception):
    """
    base exception for all grpc errors.

    subclasses should define:
        status_code: grpc.StatusCode - grpc status code
        detail: str - default error message

    instances can override detail with a custom message.
    """

    status_code: grpc.StatusCode = grpc.StatusCode.INTERNAL
    detail: str = "internal error"

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


# generic category exceptions


class InvalidArgumentException(BaseGRPCException):
    """invalid_argument - client supplied invalid data."""

    status_code = grpc.StatusCode.INVALID_ARGUMENT
    detail = "invalid argument"


class UnauthenticatedException(BaseGRPCException):
    """unauthenticated - authentication required or credentials invalid."""

    status_code = grpc.StatusCode.UNAUTHENTICATED
    detail = "unauthenticated"


class PermissionDeniedException(BaseGRPCException):
    """permission_denied - authenticated but insufficient permissions."""

    status_code = grpc.StatusCode.PERMISSION_DENIED
    detail = "permission denied"


class NotFoundException(BaseGRPCException):
    """not_found - resource does not exist."""

    status_code = grpc.StatusCode.NOT_FOUND
    detail = "not found"


class AlreadyExistsException(BaseGRPCException):
    """already_exists - resource already exists."""

    status_code = grpc.StatusCode.ALREADY_EXISTS
    detail = "already exists"


class FailedPreconditionException(BaseGRPCException):
    """failed_precondition - system not in required state for operation."""

    status_code = grpc.StatusCode.FAILED_PRECONDITION
    detail = "failed precondition"


class ResourceExhaustedException(BaseGRPCException):
    """resource_exhausted - quota or rate limit exceeded."""

    status_code = grpc.StatusCode.RESOURCE_EXHAUSTED
    detail = "resource exhausted"


class DeadlineExceededException(BaseGRPCException):
    """deadline_exceeded - operation expired before completion."""

    status_code = grpc.StatusCode.DEADLINE_EXCEEDED
    detail = "deadline exceeded"


class InternalException(BaseGRPCException):
    """internal - unexpected server-side failure."""

    status_code = grpc.StatusCode.INTERNAL
    detail = "internal error"


class UnavailableException(BaseGRPCException):
    """unavailable - service temporarily unavailable."""

    status_code = grpc.StatusCode.UNAVAILABLE
    detail = "service unavailable"


# domain-specific exceptions


class PoolNotFoundException(NotFoundException):
    """pool resource not found."""

    detail = "pool not found"


class ExperimentNotFoundException(NotFoundException):
    """experiment resource not found."""

    detail = "experiment not found"


class GateConfigNotFoundException(NotFoundException):
    """feature gate config not found."""

    detail = "gate config not found"


class PoolHasExperimentsException(FailedPreconditionException):
    """pool cannot be deleted while experiments are linked to it."""

    detail = "cannot delete pool: it has linked experiments"


class SignupClosedException(PermissionDeniedException):
    """public registration is closed by the deployment's signup mode."""

    detail = "public registration is closed - ask an administrator for an invite"


class InvalidIdentityException(InvalidArgumentException):
    """a user or workspace name or slug failed validation."""

    detail = "invalid name or slug"


class ExperimentLimitException(ResourceExhaustedException):
    """active experiment limit reached for the current plan."""

    detail = "experiment limit reached"


class UsageLimitException(ResourceExhaustedException):
    """included selection quota exceeded for the current billing period."""

    detail = "usage limit exceeded"


class InvalidContextVectorException(InvalidArgumentException):
    """context vector width does not match the experiment's dim."""

    detail = "context vector does not match the experiment's dim"


class ContextSchemaImmutableException(FailedPreconditionException):
    """a patch would add, drop or alter the experiment's context schema."""

    detail = "context_schema is fixed when the experiment is created"


class ContextDimImmutableException(FailedPreconditionException):
    """a patch would add, drop or alter the experiment's context width."""

    detail = "dim is fixed when the experiment is created"


class InvalidContextPropertiesException(InvalidArgumentException):
    """context properties cannot be encoded by the experiment's schema."""

    detail = "context properties cannot be encoded by the experiment"


class InvalidPolicyParamsException(InvalidArgumentException):
    """policy_params do not satisfy the policy schema."""

    detail = "invalid policy_params"


class LearnerExperimentDeleteException(PermissionDeniedException):
    """cannot delete a learner experiment managed by a meta-bandit."""

    detail = "cannot delete a learner experiment"


class TokenExpiredException(DeadlineExceededException):
    """selection token has expired."""

    detail = "token expired"


class TokenInvalidException(InvalidArgumentException):
    """selection token is invalid or malformed."""

    detail = "invalid token"


class MissingRequestIdException(InvalidArgumentException):
    """request_id is required but was not provided."""

    detail = "request_id is required"
