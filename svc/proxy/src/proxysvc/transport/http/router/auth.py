import logging
from typing import List
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import status
from fastapi import Depends
from pydantic import BaseModel
from pydantic import EmailStr

from proxysvc.core.error import InvalidIdentityError
from proxysvc.core.error import InviteLimitError
from proxysvc.core.error import SignupClosedError
from proxysvc.mod.auth import operator
from proxysvc.config import settings
from proxysvc.transport.http.auth import constant
from proxysvc.transport.http.auth.dependencies import get_current_user_id
from proxysvc.transport.http.auth.dependencies import get_current_user
from proxysvc.transport.http.auth.dependencies import get_current_active_user
from proxysvc.transport.http.auth.dependencies import require_admin_user
from proxysvc.transport.http.auth.dependencies import require_feature
from proxysvc.transport.http.exception import InvalidIdentityException
from proxysvc.transport.http.exception import InviteLimitException
from proxysvc.transport.http.exception import SignupClosedException
from proxysvc.transport.http.exception import UserAlreadyExistsException
from proxysvc.transport.http.exception import UnauthorizedException
from proxysvc.transport.http.exception import EmailNotVerifiedException
from proxysvc.transport.http.exception import RateLimitedException
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.transport.http.exception import InvalidTokenException
from proxysvc.transport.http.exception import BadRequestException
from proxysvc.transport.http.exception import APIKeyLimitException
from proxysvc.transport.http.exception import NotFoundException
from proxysvc.transport.http.exception import UserNotFoundException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

RoleType = Literal["admin", "member", "viewer"]


async def _throttle_email(scope: str, email: str, limit: int) -> None:
    """per-email rate limit for unauthenticated auth endpoints.

    complements the per-ip limit in the auth middleware so a single account
    cannot be targeted across many ips (e.g. reset-email bombing). bypassed in
    dev, consistent with the middleware's auth bypass.
    """
    if settings.runenv == "dev":
        return
    allowed, retry_after = await operator.auth_operator.check_auth_endpoint_rate_limit(
        f"{scope}:email", email.lower(), limit
    )
    if not allowed:
        raise RateLimitedException(
            "too many requests for this account - please try again shortly",
            headers={"Retry-After": str(retry_after)},
        )


class UserRegisterRequest(BaseModel):
    """public registration payload — no plan_tier or role by design.

    this endpoint is unauthenticated, so any tier or role it accepted would be
    self-assigned. tiers come from the billing webhook, roles from invites.
    """

    email: EmailStr
    password: str
    name: str | None = None
    workspace_name: str | None = None
    workspace_slug: str | None = None


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class PlanLimitsResponse(BaseModel):
    """the caller's tenant's limits. -1 = unlimited."""

    included_selections_per_month: int
    max_api_keys: int
    max_seats: int
    max_active_experiments: int


class TenantUsageResponse(BaseModel):
    """workspace-wide counts, unlike the caller-scoped GET /auth/api-keys."""

    api_keys: int
    seats: int
    active_experiments: int
    selections_this_period: Optional[int] = None
    period_start: Optional[float] = None
    period_end: Optional[float] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    # null outside the cloud edition, where no tier is sold
    plan_tier: Optional[str] = None
    role: str
    created_at: float
    is_active: bool
    email_verified: bool = False
    # the console derives its gates from these rather than from the tier:
    # granted in features, locked (upgradeable) in locked_features, absent in
    # neither
    edition: str
    features: List[str] = []
    locked_features: List[str] = []
    limits: Optional[PlanLimitsResponse] = None
    # only on register/login/profile: it costs four counts and a redis read,
    # which on a member list would multiply by the number of members
    usage: Optional[TenantUsageResponse] = None


def _user_response(user, *, usage: TenantUsageResponse | None = None) -> UserResponse:
    entitlements = operator.auth_operator.entitlements
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        plan_tier=user.plan_tier if entitlements.edition == "cloud" else None,
        role=user.role,
        created_at=user.created_at,
        is_active=user.is_active,
        email_verified=user.email_verified,
        edition=entitlements.edition,
        features=sorted(entitlements.features(user.plan_tier)),
        locked_features=sorted(entitlements.locked_features(user.plan_tier)),
        limits=PlanLimitsResponse(**entitlements.limits(user.plan_tier)),
        usage=usage,
    )


async def _tenant_usage(tenant_id: str) -> TenantUsageResponse | None:
    """usage for a session response — a readout, so a failure here must not
    cost the caller their login."""
    try:
        return TenantUsageResponse(
            **await operator.auth_operator.get_tenant_usage(tenant_id)
        )
    except Exception as e:
        logger.warning(f"could not resolve tenant usage for {tenant_id}: {e}")
        return None


class LoginResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class APIKeyCreateRequest(BaseModel):
    name: str = "Default API Key"


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key: str
    rate_limit_per_minute: int
    scopes: List[str]
    created_at: float
    is_active: bool


class APIKeyListResponse(BaseModel):
    id: str
    name: str
    rate_limit_per_minute: int
    scopes: List[str]
    created_at: float
    last_used_at: Optional[float] = None
    is_active: bool


class UsageResponse(BaseModel):
    current_minute_usage: int
    rate_limit_per_minute: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class UpdateAPIKeyRequest(BaseModel):
    name: str


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None


class UpdateUserStatusRequest(BaseModel):
    is_active: bool


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    created_at: float
    member_count: int


class UserStatsResponse(BaseModel):
    admin: int
    member: int
    viewer: int


class AuthConfigResponse(BaseModel):
    """what the console needs before anyone is signed in.

    deliberately the whole of it: this is the only unauthenticated view of the
    deployment, so every field here is public by definition.
    """

    signup_open: bool
    edition: str
    email_enabled: bool


@router.get(
    "/config", status_code=status.HTTP_200_OK, response_model=AuthConfigResponse
)
async def auth_config():
    return AuthConfigResponse(
        signup_open=await operator.auth_operator.signup_open(),
        edition=operator.auth_operator.entitlements.edition,
        email_enabled=operator.auth_operator.email_enabled,
    )


@router.post(
    "/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse
)
async def register_user(body: UserRegisterRequest):
    try:
        user = await operator.auth_operator.create_user(
            email=body.email,  # noqa
            password=body.password,
            name=body.name,
            workspace_name=body.workspace_name,
            workspace_slug=body.workspace_slug,
        )

        logger.info(f"user registered successfully: {user.email}")
        return _user_response(user, usage=await _tenant_usage(user.tenant_id))
    except SignupClosedError as e:
        raise SignupClosedException(str(e))
    except InvalidIdentityError as e:
        raise InvalidIdentityException(str(e))
    except ValueError as e:
        raise UserAlreadyExistsException(str(e))
    except UserAlreadyExistsException:
        raise
    except Exception as e:
        logger.error(f"registration error: {str(e)}")
        raise InternalServerException("registration failed")


@router.post("/login", status_code=status.HTTP_200_OK, response_model=LoginResponse)
async def login_user(body: UserLoginRequest):
    await _throttle_email("login", body.email, constant.LOGIN_EMAIL_PER_MIN)

    user = await operator.auth_operator.authenticate_user(
        body.email, body.password
    )  # noqa

    if not user:
        raise UnauthorizedException("invalid email or password")

    if not user.email_verified:
        raise EmailNotVerifiedException()

    access_token = operator.token_operator.create_access_token(user)
    refresh_token = operator.token_operator.create_refresh_token(user)

    logger.info(f"user logged in successfully: {user.email}")
    return LoginResponse(
        user=_user_response(user, usage=await _tenant_usage(user.tenant_id)),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh", status_code=status.HTTP_200_OK, response_model=RefreshTokenResponse
)
async def refresh_access_token(body: RefreshTokenRequest):
    access_token = await operator.token_operator.refresh_access_token(
        body.refresh_token
    )
    if not access_token:
        raise InvalidTokenException("invalid or expired refresh token")
    return RefreshTokenResponse(access_token=access_token)


@router.post(
    "/api-keys", status_code=status.HTTP_201_CREATED, response_model=APIKeyResponse
)
async def create_api_key(
    body: APIKeyCreateRequest, user_id: str = Depends(get_current_user_id)
):
    try:
        api_key, plain_key = await operator.auth_operator.create_api_key(
            user_id, body.name
        )

        logger.info(f"api key created for user {user_id}: {api_key.id}")
        return APIKeyResponse(
            id=api_key.id,
            name=api_key.name,
            key=plain_key,
            rate_limit_per_minute=api_key.rate_limit_per_minute,
            scopes=api_key.scopes,
            created_at=api_key.created_at,
            is_active=api_key.is_active,
        )
    except ValueError as e:
        error_msg = str(e)
        if "limit" in error_msg.lower():
            raise APIKeyLimitException(error_msg)
        raise BadRequestException(error_msg)
    except (APIKeyLimitException, BadRequestException):
        raise
    except Exception as e:
        logger.error(f"api key creation error: {str(e)}")
        raise InternalServerException("api key creation failed")


@router.get(
    "/api-keys", status_code=status.HTTP_200_OK, response_model=List[APIKeyListResponse]
)
async def list_api_keys(user_id: str = Depends(get_current_user_id)):
    try:
        api_keys = await operator.auth_operator.get_user_api_keys(user_id)

        return [
            APIKeyListResponse(
                id=key.id,
                name=key.name,
                rate_limit_per_minute=key.rate_limit_per_minute,
                scopes=key.scopes,
                created_at=key.created_at,
                last_used_at=key.last_used_at,
                is_active=key.is_active,
            )
            for key in api_keys
        ]
    except Exception as e:
        logger.error(f"api key listing error: {str(e)}")
        raise InternalServerException("failed to retrieve api keys")


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_200_OK)
async def deactivate_api_key(
    api_key_id: str, user_id: str = Depends(get_current_user_id)
):
    api_key = await operator.auth_operator.get_api_key(api_key_id)
    if not api_key or api_key.user_id != user_id:
        raise NotFoundException("api key not found or access denied")

    success = await operator.auth_operator.deactivate_api_key(api_key_id, user_id)
    if not success:
        raise NotFoundException("failed to deactivate api key")

    logger.info(f"api key deactivated: {api_key_id} by user {user_id}")
    return {"message": "api key deactivated successfully"}


@router.get(
    "/api-keys/{api_key_id}/usage",
    status_code=status.HTTP_200_OK,
    response_model=UsageResponse,
)
async def get_api_key_usage(
    api_key_id: str, user_id: str = Depends(get_current_user_id)
):
    api_key = await operator.auth_operator.get_api_key(api_key_id)
    if not api_key or api_key.user_id != user_id:
        raise NotFoundException("api key not found or access denied")

    try:
        usage_stats = await operator.auth_operator.get_api_key_usage(api_key)
        return UsageResponse(**usage_stats)
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"usage stats error: {str(e)}")
        raise InternalServerException("failed to retrieve usage statistics")


@router.get("/profile", status_code=status.HTTP_200_OK, response_model=UserResponse)
async def get_user_profile(user=Depends(get_current_user)):
    return _user_response(user, usage=await _tenant_usage(user.tenant_id))


class AssignRoleRequest(BaseModel):
    role: RoleType


@router.put(
    "/users/{user_id}/role",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_feature("rbac"))],
)
async def assign_role_to_user(
    user_id: str,
    body: AssignRoleRequest,
    admin_user=Depends(require_admin_user),  # noqa
):
    success = await operator.auth_operator.assign_role_to_user(user_id, body.role)
    if not success:
        raise UserNotFoundException(f"user not found: {user_id}")

    logger.info(f"role {body.role} assigned to user {user_id}")
    return {"message": f"role {body.role} assigned successfully"}


@router.get("/roles", status_code=status.HTTP_200_OK)
async def list_roles(_user=Depends(get_current_active_user)):
    return {
        "roles": [
            {
                "name": "admin",
                "description": "full system access",
                "scopes": operator.auth_operator.get_scopes_for_role("admin"),
            },
            {
                "name": "member",
                "description": "standard user access",
                "scopes": operator.auth_operator.get_scopes_for_role("member"),
            },
            {
                "name": "viewer",
                "description": "read-only access",
                "scopes": operator.auth_operator.get_scopes_for_role("viewer"),
            },
        ]
    }


class UserListResponse(BaseModel):
    users: List[UserResponse]
    limit: int
    offset: int


@router.get(
    "/users",
    status_code=status.HTTP_200_OK,
    response_model=UserListResponse,
)
async def list_users(
    limit: int = 100,
    offset: int = 0,
    search: Optional[str] = None,
    role: Optional[str] = None,
    status_filter: Optional[str] = None,
    admin_user=Depends(require_admin_user),
):
    """list all users with pagination and filters. admin only."""
    try:
        users = await operator.auth_operator.list_users(
            tenant_id=admin_user.tenant_id,
            search=search,
            role=role,
            status=status_filter,
            limit=limit,
            offset=offset,
        )

        return UserListResponse(
            users=[_user_response(user) for user in users],
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"user listing error: {str(e)}")
        raise InternalServerException("failed to retrieve users")


@router.patch("/profile", status_code=status.HTTP_200_OK, response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    user=Depends(get_current_active_user),
):
    """update current user profile."""
    try:
        updated_user = await operator.auth_operator.update_profile(
            user_id=user.id,
            name=body.name,
            email=body.email,
        )
        if not updated_user:
            raise UserNotFoundException()

        logger.info(f"profile updated for user {user.id}")
        return _user_response(updated_user)
    except InvalidIdentityError as e:
        raise InvalidIdentityException(str(e))
    except ValueError as e:
        raise BadRequestException(str(e))
    except (UserNotFoundException, BadRequestException):
        raise
    except Exception as e:
        logger.error(f"profile update error: {str(e)}")
        raise InternalServerException("failed to update profile")


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    body: ChangePasswordRequest,
    user=Depends(get_current_active_user),
):
    """change current user password."""
    try:
        success = await operator.auth_operator.change_password(
            user_id=user.id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
        if not success:
            raise UnauthorizedException("invalid current password")

        logger.info(f"password changed for user {user.id}")
        return {"message": "password updated"}
    except ValueError as e:
        raise UnauthorizedException(str(e))
    except UnauthorizedException:
        raise
    except Exception as e:
        logger.error(f"password change error: {str(e)}")
        raise InternalServerException("failed to change password")


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(body: ForgotPasswordRequest):
    """initiate password reset — always returns 200 to prevent email enumeration."""
    await _throttle_email("forgot", body.email, constant.FORGOT_EMAIL_PER_MIN)
    try:
        await operator.auth_operator.forgot_password(
            body.email, settings.console_origin
        )
    except Exception as e:
        logger.error(f"forgot password error: {str(e)}")
    return {
        "message": "if an account with that email exists, a reset link has been sent"
    }


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(body: ResetPasswordRequest):
    """complete password reset using a valid token."""
    try:
        success = await operator.auth_operator.reset_password(
            body.token, body.new_password
        )
        if not success:
            raise BadRequestException("invalid or expired reset token")
        return {"message": "password updated"}
    except BadRequestException:
        raise
    except Exception as e:
        logger.error(f"reset password error: {str(e)}")
        raise InternalServerException("failed to reset password")


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(body: VerifyEmailRequest):
    """confirm an email address using a verification token."""
    try:
        success = await operator.auth_operator.verify_email(body.token)
        if not success:
            raise BadRequestException("invalid or expired verification token")
        return {"message": "email verified"}
    except BadRequestException:
        raise
    except Exception as e:
        logger.error(f"email verification error: {str(e)}")
        raise InternalServerException("failed to verify email")


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
async def resend_verification(body: ResendVerificationRequest):
    """re-issue a verification email — always returns 200 to prevent enumeration."""
    await _throttle_email(
        "resend_verification", body.email, constant.RESEND_VERIFICATION_EMAIL_PER_MIN
    )
    try:
        await operator.auth_operator.resend_verification(body.email)
    except Exception as e:
        logger.error(f"resend verification error: {str(e)}")
    return {
        "message": "if an account with that email exists and is unverified, "
        "a verification link has been sent"
    }


@router.delete("/account", status_code=status.HTTP_200_OK)
async def delete_account(
    body: DeleteAccountRequest,
    user=Depends(get_current_active_user),
):
    """delete current user account."""
    try:
        success = await operator.auth_operator.delete_account(
            user_id=user.id,
            password=body.password,
        )
        if not success:
            raise UnauthorizedException("invalid password")

        logger.info(f"account deleted for user {user.id}")
        return {"message": "account deleted"}
    except ValueError as e:
        raise UnauthorizedException(str(e))
    except UnauthorizedException:
        raise
    except Exception as e:
        logger.error(f"account deletion error: {str(e)}")
        raise InternalServerException("failed to delete account")


@router.patch(
    "/api-keys/{api_key_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIKeyListResponse,
)
async def update_api_key(
    api_key_id: str,
    body: UpdateAPIKeyRequest,
    user_id: str = Depends(get_current_user_id),
):
    """update api key name."""
    try:
        api_key = await operator.auth_operator.update_api_key_name(
            api_key_id=api_key_id,
            user_id=user_id,
            name=body.name,
        )
        if not api_key:
            raise NotFoundException("api key not found or access denied")

        logger.info(f"api key {api_key_id} updated by user {user_id}")
        return APIKeyListResponse(
            id=api_key.id,
            name=api_key.name,
            rate_limit_per_minute=api_key.rate_limit_per_minute,
            scopes=api_key.scopes,
            created_at=api_key.created_at,
            last_used_at=api_key.last_used_at,
            is_active=api_key.is_active,
        )
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"api key update error: {str(e)}")
        raise InternalServerException("failed to update api key")


@router.post(
    "/api-keys/{api_key_id}/rotate",
    status_code=status.HTTP_200_OK,
    response_model=APIKeyResponse,
)
async def rotate_api_key(
    api_key_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """rotate api key by generating new key."""
    try:
        result = await operator.auth_operator.rotate_api_key(
            api_key_id=api_key_id,
            user_id=user_id,
        )
        if not result:
            raise NotFoundException("api key not found or access denied")

        api_key, plain_key = result
        logger.info(f"api key {api_key_id} rotated by user {user_id}")
        return APIKeyResponse(
            id=api_key.id,
            name=api_key.name,
            key=plain_key,
            rate_limit_per_minute=api_key.rate_limit_per_minute,
            scopes=api_key.scopes,
            created_at=api_key.created_at,
            is_active=api_key.is_active,
        )
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"api key rotation error: {str(e)}")
        raise InternalServerException("failed to rotate api key")


@router.get(
    "/workspace",
    status_code=status.HTTP_200_OK,
    response_model=WorkspaceResponse,
)
async def get_workspace(user=Depends(get_current_active_user)):
    """get current workspace details."""
    try:
        workspace = await operator.auth_operator.get_workspace(user.tenant_id)
        if not workspace:
            raise NotFoundException("workspace not found")

        return WorkspaceResponse(**workspace)
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"workspace retrieval error: {str(e)}")
        raise InternalServerException("failed to retrieve workspace")


@router.patch(
    "/workspace",
    status_code=status.HTTP_200_OK,
    response_model=WorkspaceResponse,
)
async def update_workspace(
    body: UpdateWorkspaceRequest,
    user=Depends(require_admin_user),
):
    """update workspace details. admin only."""
    try:
        workspace = await operator.auth_operator.update_workspace(
            tenant_id=user.tenant_id,
            name=body.name,
            slug=body.slug,
        )
        if not workspace:
            raise NotFoundException("workspace not found")

        logger.info(f"workspace {user.tenant_id} updated by user {user.id}")
        return WorkspaceResponse(
            id=workspace["id"],
            name=workspace["name"],
            slug=workspace["slug"],
            created_at=workspace["created_at"],
            member_count=0,
        )
    except InvalidIdentityError as e:
        raise InvalidIdentityException(str(e))
    except ValueError as e:
        raise BadRequestException(str(e))
    except (NotFoundException, BadRequestException):
        raise
    except Exception as e:
        logger.error(f"workspace update error: {str(e)}")
        raise InternalServerException("failed to update workspace")


@router.get(
    "/workspace/members",
    status_code=status.HTTP_200_OK,
    response_model=UserListResponse,
)
async def list_workspace_members(
    limit: int = 100,
    offset: int = 0,
    user=Depends(get_current_active_user),
):
    """list workspace members."""
    try:
        members = await operator.auth_operator.list_workspace_members(
            tenant_id=user.tenant_id,
            limit=limit,
            offset=offset,
        )

        return UserListResponse(
            users=[_user_response(member) for member in members],
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"workspace members listing error: {str(e)}")
        raise InternalServerException("failed to retrieve workspace members")


@router.patch(
    "/users/{user_id}/status",
    status_code=status.HTTP_200_OK,
    response_model=UserResponse,
)
async def update_user_status(
    user_id: str,
    body: UpdateUserStatusRequest,
    admin_user=Depends(require_admin_user),
):
    """update user active status. admin only."""
    if user_id == admin_user.id:
        raise BadRequestException("cannot deactivate your own account")

    try:
        updated_user = await operator.auth_operator.update_user_status(
            user_id=user_id,
            is_active=body.is_active,
        )
        if not updated_user:
            raise UserNotFoundException(f"user not found: {user_id}")

        status_str = "activated" if body.is_active else "deactivated"
        logger.info(f"user {user_id} {status_str} by admin {admin_user.id}")
        return _user_response(updated_user)
    except (UserNotFoundException, BadRequestException):
        raise
    except Exception as e:
        logger.error(f"user status update error: {str(e)}")
        raise InternalServerException("failed to update user status")


@router.get(
    "/users/stats",
    status_code=status.HTTP_200_OK,
    response_model=UserStatsResponse,
)
async def get_user_stats(admin_user=Depends(require_admin_user)):
    """get user statistics by role. admin only."""
    try:
        stats = await operator.auth_operator.get_user_stats(admin_user.tenant_id)
        return UserStatsResponse(**stats)
    except Exception as e:
        logger.error(f"user stats error: {str(e)}")
        raise InternalServerException("failed to retrieve user stats")


# invite models


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: RoleType = "member"


class InviteResponse(BaseModel):
    id: str
    email: str
    role: str
    status: str
    token: Optional[str] = None
    invite_url: Optional[str] = None
    invited_by: str
    expires_at: float
    created_at: float


class InviteListResponse(BaseModel):
    invites: List[InviteResponse]
    limit: int
    offset: int


class InviteAcceptRequest(BaseModel):
    name: str
    password: str


class InviteValidationResponse(BaseModel):
    email: str
    role: str
    workspace_name: str
    expires_at: float


# invite endpoints


@router.post(
    "/workspace/invites",
    status_code=status.HTTP_201_CREATED,
    response_model=InviteResponse,
)
async def create_invite(
    body: InviteCreateRequest,
    admin_user=Depends(require_admin_user),
):
    """create an invite to the workspace. admin only."""
    try:
        invite = await operator.auth_operator.create_invite(
            tenant_id=admin_user.tenant_id,
            email=body.email,  # noqa
            role=body.role,
            invited_by=admin_user.id,
        )
        return InviteResponse(
            id=invite["id"],
            email=invite["email"],
            role=invite["role"],
            status=invite["status"],
            token=invite["token"],
            invite_url=invite["invite_url"],
            invited_by=invite["invited_by"],
            expires_at=invite["expires_at"],
            created_at=invite["created_at"],
        )
    except InviteLimitError as e:
        raise InviteLimitException(str(e), headers={"Retry-After": str(e.retry_after)})
    except ValueError as e:
        raise BadRequestException(str(e))
    except BadRequestException:
        raise
    except Exception as e:
        logger.error(f"invite creation error: {str(e)}")
        raise InternalServerException("failed to create invite")


@router.get(
    "/workspace/invites",
    status_code=status.HTTP_200_OK,
    response_model=InviteListResponse,
)
async def list_invites(
    limit: int = 100,
    offset: int = 0,
    invite_status: Optional[str] = None,
    admin_user=Depends(require_admin_user),
):
    """list invites for the workspace. admin only."""
    try:
        invites = await operator.auth_operator.list_invites(
            tenant_id=admin_user.tenant_id,
            status=invite_status,
            limit=limit,
            offset=offset,
        )
        return InviteListResponse(
            invites=[
                InviteResponse(
                    id=inv["id"],
                    email=inv["email"],
                    role=inv["role"],
                    status=inv["status"],
                    invited_by=inv["invited_by"],
                    expires_at=inv["expires_at"],
                    created_at=inv["created_at"],
                )
                for inv in invites
            ],
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"invite listing error: {str(e)}")
        raise InternalServerException("failed to retrieve invites")


@router.delete(
    "/workspace/invites/{invite_id}",
    status_code=status.HTTP_200_OK,
)
async def revoke_invite(
    invite_id: str,
    admin_user=Depends(require_admin_user),
):
    """revoke a pending invite. admin only."""
    success = await operator.auth_operator.revoke_invite(
        invite_id, admin_user.tenant_id
    )
    if not success:
        raise NotFoundException("invite not found or already used")
    return {"message": "invite revoked"}


@router.get(
    "/invites/{token}",
    status_code=status.HTTP_200_OK,
    response_model=InviteValidationResponse,
)
async def validate_invite(token: str):
    """validate an invite token. public endpoint."""
    invite = await operator.auth_operator.get_invite_by_token(token)
    if not invite:
        raise NotFoundException("invite not found, expired, or already used")
    return InviteValidationResponse(**invite)


@router.post(
    "/invites/{token}/accept",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
)
async def accept_invite(token: str, body: InviteAcceptRequest):
    """accept an invite and create a user account. public endpoint."""
    try:
        user = await operator.auth_operator.accept_invite(
            token=token,
            password=body.password,
            name=body.name,
        )
        return _user_response(user)
    except InvalidIdentityError as e:
        raise InvalidIdentityException(str(e))
    except ValueError as e:
        raise BadRequestException(str(e))
    except BadRequestException:
        raise
    except Exception as e:
        logger.error(f"invite accept error: {str(e)}")
        raise InternalServerException("failed to accept invite")
