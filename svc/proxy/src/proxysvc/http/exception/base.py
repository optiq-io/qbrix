from __future__ import annotations

from typing import Any


class BaseAPIException(Exception):
    """
    base exception for all api errors.

    subclasses should define:
        status_code: int - http status code
        detail: str - default error message

    instances can override detail with a custom message.
    """

    status_code: int = 500
    detail: str = "internal server error"

    def __init__(self, detail: str | None = None, context: dict[str, Any] | None = None):
        self.detail = detail or self.__class__.detail
        self.context = context or {}
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, Any]:
        """convert exception to response dict."""
        response = {"detail": self.detail}
        if self.context:
            response["context"] = self.context
        return response


# 4xx client errors


class BadRequestException(BaseAPIException):
    """400 bad request - invalid input or malformed request."""

    status_code = 400
    detail = "bad request"


class UnauthorizedException(BaseAPIException):
    """401 unauthorized - authentication required or invalid credentials."""

    status_code = 401
    detail = "unauthorized"


class ForbiddenException(BaseAPIException):
    """403 forbidden - authenticated but insufficient permissions."""

    status_code = 403
    detail = "forbidden"


class NotFoundException(BaseAPIException):
    """404 not found - resource does not exist."""

    status_code = 404
    detail = "resource not found"


class ConflictException(BaseAPIException):
    """409 conflict - resource already exists or state conflict."""

    status_code = 409
    detail = "resource conflict"


class RateLimitedException(BaseAPIException):
    """429 too many requests - rate limit exceeded."""

    status_code = 429
    detail = "rate limit exceeded"


# 5xx server errors


class InternalServerException(BaseAPIException):
    """500 internal server error - unexpected server-side failure."""

    status_code = 500
    detail = "internal server error"


class ServiceUnavailableException(BaseAPIException):
    """503 service unavailable - downstream service failure."""

    status_code = 503
    detail = "service unavailable"


# domain-specific exceptions


class PoolNotFoundException(NotFoundException):
    """pool resource not found."""

    detail = "pool not found"


class ExperimentNotFoundException(NotFoundException):
    """experiment resource not found."""

    detail = "experiment not found"


class UserNotFoundException(NotFoundException):
    """user resource not found."""

    detail = "user not found"


class GateNotFoundException(NotFoundException):
    """feature gate not found."""

    detail = "feature gate not found"


class InvalidTokenException(UnauthorizedException):
    """invalid or expired token."""

    detail = "invalid or expired token"


class InvalidAPIKeyException(UnauthorizedException):
    """invalid or inactive api key."""

    detail = "invalid or inactive api key"


class InsufficientScopesException(ForbiddenException):
    """insufficient scopes for this operation."""

    detail = "insufficient permissions for this operation"


class UserAlreadyExistsException(ConflictException):
    """user with this email already exists."""

    detail = "user with this email already exists"


class APIKeyLimitException(ConflictException):
    """api key limit reached for plan."""

    detail = "api key limit reached for your plan"


class PoolCreationException(InternalServerException):
    """failed to create pool."""

    detail = "pool creation failed"


class ExperimentCreationException(InternalServerException):
    """failed to create experiment."""

    detail = "experiment creation failed"


class SelectionException(InternalServerException):
    """arm selection failed."""

    detail = "selection failed"


class FeedbackException(BadRequestException):
    """feedback submission failed."""

    detail = "feedback submission failed"
