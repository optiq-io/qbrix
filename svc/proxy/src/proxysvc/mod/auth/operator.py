from __future__ import annotations

import logging
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from jose import JWTError
from jose import jwt

from proxysvc.mod.auth.service import AuthService
from proxysvc.config import settings
from proxysvc.mod.auth.model import Role
from proxysvc.core.email import EmailService
from proxysvc.core.email import create_email_sender
from proxysvc.core.entitlements import Entitlements

logger = logging.getLogger(__name__)

# module-level instances, initialized via init_operators()
auth_operator: AuthOperator | None = None
token_operator: TokenOperator | None = None


class AuthOperator:
    """thin wrapper around AuthService for HTTP layer compatibility."""

    def __init__(self, auth_service: AuthService):
        self._service = auth_service

    @property
    def entitlements(self) -> Entitlements:
        return self._service.entitlements

    @property
    def email_enabled(self) -> bool:
        return self._service.email_enabled

    async def signup_open(self) -> bool:
        return await self._service.signup_open()

    async def create_user(
        self,
        email: str,
        password: str,
        tenant_id: str | None = None,
        name: str | None = None,
        role: str = Role.MEMBER.value,
        workspace_name: str | None = None,
        workspace_slug: str | None = None,
    ):
        """create a new user."""
        user_dict = await self._service.register_user(
            email=email,
            password=password,
            tenant_id=tenant_id,
            name=name,
            role=role,
            workspace_name=workspace_name,
            workspace_slug=workspace_slug,
        )
        return _UserWrapper(user_dict)

    async def get_user(self, user_id: str):
        """get user by id."""
        user_dict = await self._service.get_user(user_id)
        if user_dict is None:
            return None
        return _UserWrapper(user_dict)

    async def get_user_by_email(self, email: str):
        """get user by email."""
        user_dict = await self._service.get_user_by_email(email)
        if user_dict is None:
            return None
        return _UserWrapper(user_dict)

    async def authenticate_user(self, email: str, password: str):
        """authenticate user with email and password."""
        user_dict = await self._service.authenticate_user(email, password)
        if user_dict is None:
            return None
        return _UserWrapper(user_dict)

    async def create_api_key(
        self,
        user_id: str,
        name: str = "Default API Key",
        scopes: list[str] | None = None,
    ) -> tuple:
        """create api key for user. returns (api_key_wrapper, plain_key)."""
        api_key_dict, plain_key = await self._service.create_api_key(
            user_id=user_id,
            name=name,
            scopes=scopes,
        )
        return _APIKeyWrapper(api_key_dict), plain_key

    async def get_api_key(self, api_key_id: str):
        """get api key by id."""
        api_key_dict = await self._service.get_api_key(api_key_id)
        if api_key_dict is None:
            return None
        return _APIKeyWrapper(api_key_dict)

    async def validate_api_key(self, plain_key: str):
        """validate api key and return wrapper if valid."""
        api_key_dict = await self._service.validate_api_key(plain_key)
        if api_key_dict is None:
            return None
        return _APIKeyWrapper(api_key_dict)

    async def get_user_api_keys(self, user_id: str) -> list:
        """get all api keys for user."""
        api_keys = await self._service.list_user_api_keys(user_id)
        return [_APIKeyWrapper(k) for k in api_keys]

    async def deactivate_api_key(self, api_key_id: str, user_id: str) -> bool:
        """deactivate api key."""
        return await self._service.deactivate_api_key(api_key_id, user_id)

    async def check_api_key_rate_limit(self, api_key) -> bool:
        """check rate limit for api key."""
        allowed, _, _ = await self._service.check_api_key_rate_limit(api_key.id)
        return allowed

    async def check_user_rate_limit(self, user) -> bool:
        """check rate limit for user."""
        allowed, _, _ = await self._service.check_user_rate_limit(user.id)
        return allowed

    async def check_auth_endpoint_rate_limit(
        self, scope: str, identifier: str, limit: int
    ) -> tuple[bool, int]:
        """rate limit an unauthenticated auth endpoint by ip or email."""
        return await self._service.check_auth_endpoint_rate_limit(
            scope, identifier, limit
        )

    async def get_api_key_usage(self, api_key) -> dict:
        """get api key usage stats."""
        return await self._service.get_api_key_usage(api_key.id)

    async def assign_role_to_user(self, user_id: str, role: str) -> bool:
        """assign role to user."""
        result = await self._service.assign_role(user_id, role)
        return result is not None

    async def list_users(
        self,
        tenant_id: str | None = None,
        search: str | None = None,
        role: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        """list users with optional filters."""
        users = await self._service.list_users(
            tenant_id=tenant_id,
            search=search,
            role=role,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [_UserWrapper(u) for u in users]

    async def update_profile(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
    ):
        """update user profile."""
        user_dict = await self._service.update_profile(user_id, name=name, email=email)
        if user_dict is None:
            return None
        return _UserWrapper(user_dict)

    async def change_password(
        self, user_id: str, current_password: str, new_password: str
    ) -> bool:
        """change user password."""
        return await self._service.change_password(
            user_id, current_password, new_password
        )

    async def delete_account(self, user_id: str, password: str) -> bool:
        """delete user account."""
        return await self._service.delete_account(user_id, password)

    async def update_user_status(self, user_id: str, is_active: bool):
        """update user active status."""
        user_dict = await self._service.update_user_status(user_id, is_active)
        if user_dict is None:
            return None
        return _UserWrapper(user_dict)

    async def get_user_stats(self, tenant_id: str) -> dict[str, int]:
        """get user stats by role."""
        return await self._service.get_user_stats(tenant_id)

    async def get_tenant_usage(self, tenant_id: str) -> dict[str, float]:
        """tenant-wide counts behind the plan limits."""
        return await self._service.get_tenant_usage(tenant_id)

    async def get_workspace(self, tenant_id: str) -> dict | None:
        """get workspace details."""
        return await self._service.get_workspace(tenant_id)

    async def update_workspace(
        self,
        tenant_id: str,
        name: str | None = None,
        slug: str | None = None,
    ) -> dict | None:
        """update workspace details."""
        return await self._service.update_workspace(tenant_id, name=name, slug=slug)

    async def list_workspace_members(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list:
        """list workspace members."""
        users = await self._service.list_workspace_members(tenant_id, limit, offset)
        return [_UserWrapper(u) for u in users]

    async def create_invite(
        self,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
    ) -> dict:
        """create an invite."""
        return await self._service.create_invite(
            tenant_id=tenant_id,
            email=email,
            role=role,
            invited_by=invited_by,
        )

    async def get_invite_by_token(self, token: str) -> dict | None:
        """validate and get invite by token."""
        return await self._service.get_invite_by_token(token)

    async def accept_invite(
        self,
        token: str,
        password: str,
        name: str | None = None,
    ):
        """accept an invite and create user."""
        user_dict = await self._service.accept_invite(token, password, name)
        return _UserWrapper(user_dict)

    async def revoke_invite(self, invite_id: str, tenant_id: str) -> bool:
        """revoke a pending invite."""
        return await self._service.revoke_invite(invite_id, tenant_id)

    async def list_invites(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """list invites for a tenant."""
        return await self._service.list_invites(
            tenant_id=tenant_id, status=status, limit=limit, offset=offset
        )

    async def update_api_key_name(self, api_key_id: str, user_id: str, name: str):
        """update api key name."""
        api_key_dict = await self._service.update_api_key(api_key_id, user_id, name)
        if api_key_dict is None:
            return None
        return _APIKeyWrapper(api_key_dict)

    async def rotate_api_key(self, api_key_id: str, user_id: str) -> tuple | None:
        """rotate api key. returns (api_key_wrapper, plain_key)."""
        result = await self._service.rotate_api_key(api_key_id, user_id)
        if result is None:
            return None
        api_key_dict, plain_key = result
        return _APIKeyWrapper(api_key_dict), plain_key

    async def forgot_password(self, email: str, reset_base_url: str) -> None:
        """initiate password reset flow."""
        await self._service.forgot_password(email, reset_base_url)

    async def reset_password(self, token: str, new_password: str) -> bool:
        """complete password reset with token."""
        return await self._service.reset_password(token, new_password)

    async def verify_email(self, token: str) -> bool:
        """confirm a user's email with a verification token."""
        return await self._service.verify_email(token)

    async def resend_verification(self, email: str) -> None:
        """re-issue an email verification token (enumeration-safe)."""
        await self._service.resend_verification(email)

    async def user_has_permission(self, user_id: str, required_scope: str) -> bool:
        """check if user has required scope."""
        return await self._service.check_user_permission(user_id, required_scope)

    @staticmethod
    async def api_key_has_scope(api_key, required_scope: str) -> bool:
        """check if api key has required scope."""
        return required_scope in api_key.scopes or "system:admin" in api_key.scopes

    @staticmethod
    def get_scopes_for_role(role: str) -> list[str]:
        """get scopes for a given role."""
        return AuthService.get_scopes_for_role(role)


class TokenOperator:
    """stateless JWT token handling."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
    ):
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._access_token_expire_minutes = access_token_expire_minutes
        self._refresh_token_expire_days = refresh_token_expire_days

    def create_access_token(self, user) -> str:
        """create access token for user."""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=self._access_token_expire_minutes)
        payload = {
            "sub": user.id,
            "tenant_id": user.tenant_id,
            "email": user.email,
            "role": user.role,
            "plan_tier": user.plan_tier,
            "exp": expire,
            "iat": now,
            "type": "access",
        }
        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        logger.info(f"created access token for user {user.id}")
        return token

    def create_refresh_token(self, user) -> str:
        """create refresh token for user."""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=self._refresh_token_expire_days)
        payload = {
            "sub": user.id,
            "exp": expire,
            "iat": now,
            "type": "refresh",
        }
        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        logger.info(f"created refresh token for user {user.id}")
        return token

    def verify_token(self, token: str) -> dict[str, Any] | None:
        """verify and decode token."""
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                options={"verify_exp": False},
            )
            exp = payload.get("exp")
            if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(
                timezone.utc
            ):
                logger.warning("token has expired")
                return None
            return payload
        except JWTError as e:
            logger.warning(f"jwt validation error: {e}")
            return None
        except Exception as e:
            logger.error(f"unexpected error during token validation: {e}")
            return None

    def get_user_id_from_token(self, token: str) -> str | None:
        """extract user id from access token."""
        payload = self.verify_token(token)
        if payload and payload.get("type") == "access":
            return payload.get("sub")
        return None

    async def refresh_access_token(self, refresh_token: str) -> str | None:
        """refresh access token using refresh token."""
        payload = self.verify_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        user = await auth_operator.get_user(user_id)
        if not user or not user.is_active:
            logger.warning(
                f"user {user_id} is inactive or not found, cannot refresh token"
            )
            return None

        new_access_token = self.create_access_token(user)
        logger.info(f"access token refreshed for user {user_id}")
        return new_access_token


class _UserWrapper:
    """wrapper to provide attribute access to user dict for backward compatibility."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def tenant_id(self) -> str:
        return self._data["tenant_id"]

    @property
    def email(self) -> str:
        return self._data["email"]

    @property
    def name(self) -> str | None:
        return self._data.get("name")

    @property
    def plan_tier(self) -> str:
        return self._data["plan_tier"]

    @property
    def role(self) -> str:
        return self._data["role"]

    @property
    def is_active(self) -> bool:
        return self._data.get("is_active", True)

    @property
    def email_verified(self) -> bool:
        return self._data.get("email_verified", False)

    @property
    def created_at(self) -> float:
        return self._data.get("created_at", 0.0)

    @property
    def updated_at(self) -> float:
        return self._data.get("updated_at", 0.0)


class _APIKeyWrapper:
    """wrapper to provide attribute access to api key dict for backward compatibility."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def user_id(self) -> str:
        return self._data["user_id"]

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def rate_limit_per_minute(self) -> int:
        return self._data["rate_limit_per_minute"]

    @property
    def scopes(self) -> list[str]:
        return self._data.get("scopes", [])

    @property
    def is_active(self) -> bool:
        return self._data.get("is_active", True)

    @property
    def created_at(self) -> float:
        return self._data.get("created_at", 0.0)

    @property
    def last_used_at(self) -> float | None:
        return self._data.get("last_used_at")


def init_operators(auth_service: AuthService) -> None:
    """initialize module-level operators with auth service instance."""
    global auth_operator, token_operator

    auth_operator = AuthOperator(auth_service)
    token_operator = TokenOperator(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
        refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
    )
    logger.info("initialized auth and token operators")


def create_auth_service(redis, entitlements: Entitlements) -> AuthService:
    """create AuthService with EmailService wired in from settings."""
    email_service = EmailService(create_email_sender(settings))
    return AuthService(redis=redis, email=email_service, entitlements=entitlements)
