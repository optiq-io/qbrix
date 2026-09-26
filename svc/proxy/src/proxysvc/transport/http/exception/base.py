from __future__ import annotations

from typing import Any
from typing import ClassVar


class BaseAPIException(Exception):
    """
    base exception for all api errors.

    subclasses should define:
        status_code: int - http status code
        detail: str - default error message
        code: str - stable upper-snake identifier for frontend mapping

    instances can override detail with a custom message.
    """

    status_code: int = 500
    detail: str = "internal server error"
    code: ClassVar[str] = "INTERNAL_ERROR"

    def __init__(
        self,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.detail = detail or self.__class__.detail
        self.context = context or {}
        self.headers = headers or {}
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, Any]:
        """convert exception to response dict."""
        response: dict[str, Any] = {"code": self.code, "detail": self.detail}
        if self.context:
            response["context"] = self.context
        return response


# 4xx client errors


class BadRequestException(BaseAPIException):
    """400 bad request - invalid input or malformed request."""

    status_code = 400
    detail = "bad request"
    code = "BAD_REQUEST"


class UnauthorizedException(BaseAPIException):
    """401 unauthorized - authentication required or invalid credentials."""

    status_code = 401
    detail = "unauthorized"
    code = "UNAUTHORIZED"


class ForbiddenException(BaseAPIException):
    """403 forbidden - authenticated but insufficient permissions."""

    status_code = 403
    detail = "forbidden"
    code = "FORBIDDEN"


class NotFoundException(BaseAPIException):
    """404 not found - resource does not exist."""

    status_code = 404
    detail = "resource not found"
    code = "NOT_FOUND"


class ConflictException(BaseAPIException):
    """409 conflict - resource already exists or state conflict."""

    status_code = 409
    detail = "resource conflict"
    code = "CONFLICT"


class UnprocessableEntityException(BaseAPIException):
    """422 unprocessable entity - well-formed input that fails a domain rule."""

    status_code = 422
    detail = "unprocessable entity"
    code = "UNPROCESSABLE_ENTITY"


class RateLimitedException(BaseAPIException):
    """429 too many requests - rate limit exceeded."""

    status_code = 429
    detail = "rate limit exceeded"
    code = "RATE_LIMITED"


class UsageLimitException(BaseAPIException):
    """429 too many requests - included selection quota exceeded for the period."""

    status_code = 429
    detail = "usage limit exceeded"
    code = "USAGE_LIMIT_EXCEEDED"


# 5xx server errors


class InternalServerException(BaseAPIException):
    """500 internal server error - unexpected server-side failure."""

    status_code = 500
    detail = "internal server error"
    code = "INTERNAL_ERROR"


class ServiceUnavailableException(BaseAPIException):
    """503 service unavailable - downstream service failure."""

    status_code = 503
    detail = "service unavailable"
    code = "SERVICE_UNAVAILABLE"


# domain-specific exceptions


class PoolNotFoundException(NotFoundException):
    """pool resource not found."""

    detail = "pool not found"
    code = "POOL_NOT_FOUND"


class ExperimentNotFoundException(NotFoundException):
    """experiment resource not found."""

    detail = "experiment not found"
    code = "EXPERIMENT_NOT_FOUND"


class UserNotFoundException(NotFoundException):
    """user resource not found."""

    detail = "user not found"
    code = "USER_NOT_FOUND"


class GateNotFoundException(NotFoundException):
    """feature gate not found."""

    detail = "feature gate not found"
    code = "GATE_NOT_FOUND"


class InvalidTokenException(UnauthorizedException):
    """invalid or expired token."""

    detail = "invalid or expired token"
    code = "INVALID_TOKEN"


class InvalidAPIKeyException(UnauthorizedException):
    """invalid or inactive api key."""

    detail = "invalid or inactive api key"
    code = "INVALID_API_KEY"


class InsufficientScopesException(ForbiddenException):
    """insufficient scopes for this operation."""

    detail = "insufficient permissions for this operation"
    code = "INSUFFICIENT_SCOPES"


class PlanTierRequiredException(ForbiddenException):
    """plan tier insufficient for this feature."""

    detail = "this feature requires a pro or enterprise plan"
    code = "PLAN_TIER_REQUIRED"


class EmailNotVerifiedException(ForbiddenException):
    """email address has not been verified yet."""

    detail = "email not verified - check your inbox or request a new verification link"
    code = "EMAIL_NOT_VERIFIED"


class SignupClosedException(ForbiddenException):
    """public registration is closed by the deployment's signup mode."""

    detail = "public registration is closed - ask an administrator for an invite"
    code = "SIGNUP_CLOSED"


class InvalidIdentityException(UnprocessableEntityException):
    """a user or workspace name or slug failed validation."""

    detail = "invalid name or slug"
    code = "INVALID_IDENTITY"


class InviteLimitException(RateLimitedException):
    """the workspace has sent its daily allowance of invites."""

    detail = "daily invite limit reached"
    code = "INVITE_LIMIT_EXCEEDED"


class UserAlreadyExistsException(ConflictException):
    """user with this email already exists."""

    detail = "user with this email already exists"
    code = "USER_ALREADY_EXISTS"


class APIKeyLimitException(ConflictException):
    """api key limit reached for plan."""

    detail = "api key limit reached for your plan"
    code = "API_KEY_LIMIT_REACHED"


class ExperimentLimitException(ConflictException):
    """active experiment limit reached for plan."""

    detail = "active experiment limit reached for your plan"
    code = "EXPERIMENT_LIMIT_REACHED"


class GateAlreadyExistsException(ConflictException):
    """experiment already has a feature gate; it must be updated, not created."""

    detail = "this experiment already has a feature gate"
    code = "GATE_ALREADY_EXISTS"


class UnknownPriceException(BadRequestException):
    """checkout requested a price id matching no configured plan tier."""

    detail = "that plan is not available for checkout"
    code = "UNKNOWN_PRICE_ID"


class PoolHasExperimentsException(ConflictException):
    """pool cannot be deleted while experiments are linked to it."""

    detail = (
        "cannot delete pool: it has linked experiments. remove or reassign them first."
    )
    code = "POOL_HAS_EXPERIMENTS"


class PoolCreationException(InternalServerException):
    """failed to create pool."""

    detail = "pool creation failed"
    code = "POOL_CREATION_FAILED"


class ExperimentCreationException(InternalServerException):
    """failed to create experiment."""

    detail = "experiment creation failed"
    code = "EXPERIMENT_CREATION_FAILED"


class SelectionException(InternalServerException):
    """arm selection failed."""

    detail = "selection failed"
    code = "SELECTION_FAILED"


class FeedbackException(BadRequestException):
    """feedback submission failed."""

    detail = "feedback submission failed"
    code = "FEEDBACK_FAILED"


class InvalidContextVectorException(BadRequestException):
    """context vector width does not match the experiment's dim."""

    detail = "context vector does not match the experiment's dim"
    code = "INVALID_CONTEXT_VECTOR"


class InvalidContextPropertiesException(BadRequestException):
    """context properties cannot be encoded by the experiment's schema."""

    detail = "context properties cannot be encoded by the experiment"
    code = "INVALID_CONTEXT_PROPERTIES"


class InvalidPolicyParamsException(BadRequestException):
    """policy_params do not satisfy the policy schema."""

    detail = "invalid policy_params"
    code = "INVALID_POLICY_PARAMS"


class LearnerExperimentDeleteException(ForbiddenException):
    """learner experiment deletion failed."""

    detail = "learner experiment deletion failed"
    code = "LEARNER_EXPERIMENT_DELETE_FORBIDDEN"


class ContextSchemaImmutableException(ConflictException):
    """a patch would add, drop or alter the experiment's context schema."""

    detail = "context_schema is fixed when the experiment is created"
    code = "CONTEXT_SCHEMA_IMMUTABLE"


class ContextDimImmutableException(ConflictException):
    """a patch would add, drop or alter the experiment's context width."""

    detail = "dim is fixed when the experiment is created"
    code = "CONTEXT_DIM_IMMUTABLE"


class ExperimentRunningException(ConflictException):
    """operation requires the experiment to be paused first."""

    detail = "pause the experiment before resetting its parameters"
    code = "EXPERIMENT_RUNNING"
