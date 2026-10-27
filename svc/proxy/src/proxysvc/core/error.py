from __future__ import annotations


class BaseAPIError(Exception):
    """raised when a base error occurs."""

    pass


class BadPolicyParamsError(BaseAPIError):
    """raised when policy_params do not satisfy the policy's schema."""


class PoolHasExperimentsError(BaseAPIError):
    """raised when attempting to delete a pool that has linked experiments."""

    pass


class ExperimentLimitError(BaseAPIError):
    """raised when the experiment creation limit in plan is reached."""

    pass


class ExperimentNotFoundError(BaseAPIError):
    """raised when selecting for an experiment that does not exist."""

    pass


class GateExistsError(BaseAPIError):
    """raised when creating a gate for an experiment that already has one."""

    pass


class UsageLimitError(BaseAPIError):
    """raised when a tenant exceeds its included selection quota for the period."""

    pass


class ContextVectorError(BaseAPIError):
    """raised when a context vector does not match the experiment's dim."""

    pass


class ContextPropertiesError(BaseAPIError):
    """raised when context properties cannot be encoded by the experiment."""

    pass


class ContextSchemaImmutableError(BaseAPIError):
    """raised when a patch would change an experiment's context schema."""

    pass


class ContextDimImmutableError(BaseAPIError):
    """raised when a patch would change an experiment's context width."""

    pass


class LearnerExperimentDeleteError(BaseAPIError):
    """raised when the user tries to delete a learner experiment."""

    pass


class ExperimentRunningError(BaseAPIError):
    """raised when an operation requires the experiment to be paused first."""

    pass


class ChangeNotUndoableError(BaseAPIError):
    """raised when undoing a kind of change that cannot be undone."""


class ChangeConflictError(BaseAPIError):
    """raised when an undo would not restore what the change recorded: it was
    already undone, a later change exists, or its target is gone."""


class MetricInvalidError(BaseAPIError):
    """raised when a metric's name, type, range, window or semantic is refused."""


class MetricNameTakenError(BaseAPIError):
    """raised when the workspace already has a metric with that name."""


class LoopInvalidError(BaseAPIError):
    """raised when a loop's name, key, metric, engine, options or fallback is refused."""


class LoopKeyTakenError(BaseAPIError):
    """raised when the workspace already has a loop with that key."""


class LoopStateError(BaseAPIError):
    """raised when a change needs the loop in a state it isn't in."""


class LoopNotFoundError(BaseAPIError):
    """raised when select names a loop the workspace doesn't have."""


class CycleNotFoundError(BaseAPIError):
    """raised when a read names a cycle number the loop never had."""


class DecisionContextError(BaseAPIError):
    """raised when a select's context has no unit, or properties that aren't an object."""


class InvalidOutcomeError(BaseAPIError):
    """raised when an outcome's value, id or time breaks a rule of its decision."""


class InvalidCursorError(BaseAPIError):
    """raised when a page cursor isn't one a previous page returned."""


class SignupClosedError(BaseAPIError):
    """raised when public registration is closed by the deployment's signup mode."""

    pass


class InvalidIdentityError(BaseAPIError):
    """raised when a user or workspace name or slug fails validation."""

    pass


class InviteLimitError(BaseAPIError):
    """raised when a tenant has sent its daily allowance of invites."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class TokenError(BaseAPIError):
    """raised when token validation fails."""

    pass


class TokenExpiredError(TokenError):
    """raised when token has expired. its signature verified, so it names the
    tenant and the experiment the caller selected from."""

    def __init__(self, message: str, tenant_id: str, experiment_id: str):
        super().__init__(message)
        self.tenant_id = tenant_id
        self.experiment_id = experiment_id


class TokenInvalidError(TokenError):
    """raised when token signature is invalid."""

    pass


class OAuthError(BaseAPIError):
    """raised when an oauth request fails. error is the rfc 6749 code the
    client reads, description the sentence a person reads."""

    def __init__(self, error: str, description: str):
        super().__init__(description)
        self.error = error
        self.description = description


class OAuthRedirectError(OAuthError):
    """raised when an authorization request fails after its redirect_uri is
    trusted, so the error goes back to the client rather than to the person."""

    def __init__(self, error: str, description: str, redirect_uri: str, state: str):
        super().__init__(error, description)
        self.redirect_uri = redirect_uri
        self.state = state


class OAuthRequestNotFoundError(BaseAPIError):
    """raised when an authorization request is unknown, expired or decided."""


class ConnectionNotFoundError(BaseAPIError):
    """raised when a connection doesn't exist or isn't the caller's to see."""


class ConnectionTokenInvalidError(BaseAPIError):
    """raised when a connection's token is unknown, expired, revoked or meant
    for another resource."""


class ConnectionRateLimitedError(BaseAPIError):
    """raised when a connection has used its calls or changes for this minute."""

    def __init__(self, message: str, *, limit: int, retry_after: int):
        super().__init__(message)
        self.limit = limit
        self.retry_after = retry_after
