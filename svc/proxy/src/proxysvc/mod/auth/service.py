from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime
from datetime import timezone

import bcrypt
from cachebox import TTLCache
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Invite
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient

from proxysvc.config import settings
from proxysvc.core.email import EmailService
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.error import InviteLimitError
from proxysvc.core.error import SignupClosedError
from proxysvc.mod.auth.repository import TenantRepository
from proxysvc.mod.auth.repository import UserRepository
from proxysvc.mod.auth.repository import APIKeyRepository
from proxysvc.mod.auth.repository import InviteRepository
from proxysvc.mod.auth.identity import MAX_SLUG_LENGTH
from proxysvc.mod.auth.identity import clean_name
from proxysvc.mod.auth.identity import clean_slug
from proxysvc.mod.auth.identity import slug_from
from proxysvc.mod.auth.scope import ROLE_SCOPES
from proxysvc.mod.auth.scope import ABUSE_RATE_LIMIT_PER_MINUTE
from proxysvc.mod.auth.scope import INVITES_PER_TENANT_PER_DAY
from proxysvc.mod.experiment.repository import ExperimentRepository

logger = logging.getLogger(__name__)

_DAY_SEC = 86400


class AuthService:
    """core authentication service with business logic for user and api key management."""

    def __init__(
        self,
        redis: RedisClient,
        email: EmailService,
        entitlements: Entitlements,
    ):
        self._redis = redis
        self._email = email
        self._entitlements = entitlements
        self._api_key_prefix = "optiq_"
        self._api_key_cache: TTLCache = TTLCache(maxsize=500, ttl=60)
        self._user_cache: TTLCache = TTLCache(maxsize=500, ttl=60)
        # in first-user mode the answer only ever goes from open to closed, so
        # once it closes it never needs looking up again
        self._signup_closed = False

    @property
    def entitlements(self) -> Entitlements:
        return self._entitlements

    @property
    def email_enabled(self) -> bool:
        return self._email.enabled

    async def signup_open(self) -> bool:
        """whether public registration would be accepted right now."""
        mode = settings.signup_mode
        if mode == "open":
            return True
        if mode == "invite-only":
            return False

        if self._signup_closed:
            return False
        async with get_session() as session:
            exists = await UserRepository(session).any_exists()
        if exists:
            self._signup_closed = True
        return not exists

    # user management

    async def register_user(
        self,
        email: str,
        password: str,
        tenant_id: str | None = None,
        name: str | None = None,
        role: str = "member",
        workspace_name: str | None = None,
        workspace_slug: str | None = None,
    ) -> dict:
        """register a new user with email and password.

        if tenant_id is not provided, creates a new tenant for the user.
        uses workspace_name/workspace_slug if provided, otherwise falls back
        to auto-generating from the email prefix.

        role is only ever passed by invite acceptance; the public register
        transports never forward it, so self-signup lands on member. the tier
        is the tenant's, never the user's.

        the signup mode is enforced here rather than per transport, so http and
        grpc cannot diverge. a caller that already has a tenant_id arrived
        through an invite and is never gated.
        """
        if tenant_id is None and not await self.signup_open():
            raise SignupClosedError(
                "public registration is closed - ask an administrator for an invite"
            )
        name = clean_name(name, "name")
        workspace_name = clean_name(workspace_name, "workspace name")
        if workspace_slug:
            workspace_slug = clean_slug(workspace_slug)

        # in dev, auto-verify so local flows aren't blocked at login, consistent
        # with the dev rate-limit/auth bypass elsewhere. without an email
        # provider there is no way to deliver a verification link, so requiring
        # one would only lock every new account out.
        auto_verify = settings.runenv == "dev" or not self._email.enabled
        try:
            async with get_session() as session:
                user_repo = UserRepository(session)

                existing = await user_repo.get_by_email(email)
                if existing:
                    raise ValueError(f"user with email {email} already exists")

                if tenant_id is None:
                    tenant_repo = TenantRepository(session)
                    base_slug = workspace_slug or slug_from(email.split("@")[0])
                    slug = base_slug
                    counter = 1
                    while await tenant_repo.get_by_slug(slug):
                        suffix = f"-{counter}"
                        slug = f"{base_slug[: MAX_SLUG_LENGTH - len(suffix)]}{suffix}"
                        counter += 1
                    tenant_name = workspace_name or f"{email}'s Workspace"
                    tenant = await tenant_repo.create(
                        name=tenant_name,
                        slug=slug,
                    )
                    tenant_id = tenant.id
                    role = "admin"  # founding user is always admin
                    logger.info(f"created tenant {tenant_id} with slug {slug}")

                password_hash = bcrypt.hashpw(
                    password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")

                user = await user_repo.create(
                    email=email,
                    password_hash=password_hash,
                    tenant_id=tenant_id,
                    name=name,
                    role=role,
                    email_verified=auto_verify,
                )
                logger.info(f"created user {user.id} with email {email}")
                user_dict = self._user_to_dict(user)
        except IntegrityError:
            raise ValueError(f"user with email {email} already exists")

        # issue verification after the user is committed, so the token never
        # outlives a rolled-back registration.
        if not auto_verify:
            await self._issue_email_verification(user_dict["id"], email)
        return user_dict

    async def authenticate_user(self, email: str, password: str) -> dict | None:
        """authenticate user with email and password."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get_by_email(email)

            if not user or not user.is_active:
                return None

            if bcrypt.checkpw(
                password.encode("utf-8"), user.password_hash.encode("utf-8")
            ):
                return self._user_to_dict(user)
            return None

    async def get_user(self, user_id: str) -> dict | None:
        """get user by id."""
        cached = self._user_cache.get(user_id)
        if cached is not None:
            return cached

        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)
            if user is None:
                return None
            user_dict = self._user_to_dict(user)
            self._user_cache[user_id] = user_dict
            return user_dict

    def invalidate_tenant(self, tenant_id: str) -> None:
        """evict every cached principal belonging to a tenant.

        the tier lives on the tenant but reaches callers through each member's
        cached principal (see _user_to_dict), so a tenant-level change has to
        sweep a user-keyed cache rather than pop one entry.
        """
        stale = [
            user_id
            for user_id, user in self._user_cache.items()
            if user.get("tenant_id") == tenant_id
        ]
        for user_id in stale:
            self._user_cache.pop(user_id, None)

    async def get_user_by_email(self, email: str) -> dict | None:
        """get user by email."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get_by_email(email)
            if user is None:
                return None
            return self._user_to_dict(user)

    async def update_user(
        self,
        user_id: str,
        is_active: bool | None = None,
    ) -> dict | None:
        """update user fields."""
        async with get_session() as session:
            repo = UserRepository(session)
            kwargs = {}
            if is_active is not None:
                kwargs["is_active"] = is_active
            user = await repo.update(user_id, **kwargs)
            if user is None:
                return None
            return self._user_to_dict(user)

    @staticmethod
    async def deactivate_user(user_id: str) -> bool:
        """deactivate user account."""
        async with get_session() as session:
            repo = UserRepository(session)
            result = await repo.deactivate(user_id)
            if result:
                logger.info(f"deactivated user {user_id}")
            return result

    async def assign_role(self, user_id: str, role: str) -> dict | None:
        """assign role to user."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.update(user_id, role=role)
            if user is None:
                return None
            logger.info(f"assigned role {role} to user {user_id}")
            return self._user_to_dict(user)

    async def list_users(
        self,
        tenant_id: str | None = None,
        search: str | None = None,
        role: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """list users with optional filters."""
        async with get_session() as session:
            repo = UserRepository(session)
            if tenant_id and (search or role or status):
                users = await repo.search(
                    tenant_id=tenant_id,
                    query=search,
                    role=role,
                    status=status,
                    limit=limit,
                    offset=offset,
                )
            elif tenant_id:
                users = await repo.list_by_tenant(
                    tenant_id=tenant_id, limit=limit, offset=offset
                )
            else:
                users = await repo.list(limit=limit, offset=offset)
            return [self._user_to_dict(user) for user in users]

    async def update_profile(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
    ) -> dict | None:
        """update user profile fields."""
        name = clean_name(name, "name")
        try:
            async with get_session() as session:
                repo = UserRepository(session)

                if email:
                    existing = await repo.get_by_email(email)
                    if existing and existing.id != user_id:
                        raise ValueError(f"email {email} is already in use")

                kwargs = {}
                if name is not None:
                    kwargs["name"] = name
                if email is not None:
                    kwargs["email"] = email

                user = await repo.update(user_id, **kwargs)
                if user is None:
                    return None
                logger.info(f"updated profile for user {user_id}")
                return self._user_to_dict(user)
        except IntegrityError:
            raise ValueError(f"email {email} is already in use")

    @staticmethod
    async def change_password(
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> bool:
        """change user password after validating current password."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)

            if not user:
                return False

            if not bcrypt.checkpw(
                current_password.encode("utf-8"), user.password_hash.encode("utf-8")
            ):
                raise ValueError("current password is incorrect")

            new_hash = bcrypt.hashpw(
                new_password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            await repo.update(user_id, password_hash=new_hash)
            logger.info(f"password changed for user {user_id}")
            return True

    @staticmethod
    async def delete_account(user_id: str, password: str) -> bool:
        """delete user account after validating password."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)

            if not user:
                return False

            if not bcrypt.checkpw(
                password.encode("utf-8"), user.password_hash.encode("utf-8")
            ):
                raise ValueError("password is incorrect")

            result = await repo.delete(user_id)
            if result:
                logger.info(f"deleted account for user {user_id}")
            return result

    async def forgot_password(self, email: str, reset_base_url: str) -> None:
        """generate a password reset token and send reset email."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get_by_email(email)

        if not user:
            # don't reveal whether the email exists
            return

        token = secrets.token_hex(32)
        redis_key = f"qbrix:password_reset:{token}"
        await self._redis.client.set(redis_key, user.id, ex=900)

        reset_url = f"{reset_base_url}/reset-password?token={token}"
        await self._email.send_password_reset(email, reset_url)
        logger.info(f"password reset requested for user {user.id}")

    async def reset_password(self, token: str, new_password: str) -> bool:
        """validate reset token and update user password."""
        redis_key = f"qbrix:password_reset:{token}"
        user_id = await self._redis.client.get(redis_key)

        if not user_id:
            return False

        if isinstance(user_id, bytes):
            user_id = user_id.decode("utf-8")

        new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode(
            "utf-8"
        )

        async with get_session() as session:
            repo = UserRepository(session)
            await repo.update(user_id, password_hash=new_hash)

        await self._redis.client.delete(redis_key)
        logger.info(f"password reset completed for user {user_id}")
        return True

    # email verification

    async def _issue_email_verification(self, user_id: str, email: str) -> None:
        """generate a single-use email verification token and send the link."""
        token = secrets.token_urlsafe(32)
        redis_key = f"qbrix:email_verify:{token}"
        await self._redis.client.set(
            redis_key, user_id, ex=settings.email_verification_ttl_seconds
        )

        verify_url = f"{settings.console_origin}/verify-email?token={token}"
        await self._email.send_email_verification(email, verify_url)
        logger.info(f"email verification requested for user {user_id}")

    async def verify_email(self, token: str) -> bool:
        """validate a verification token and mark the user's email verified."""
        redis_key = f"qbrix:email_verify:{token}"
        user_id = await self._redis.client.get(redis_key)

        if not user_id:
            return False

        if isinstance(user_id, bytes):
            user_id = user_id.decode("utf-8")

        async with get_session() as session:
            repo = UserRepository(session)
            updated = await repo.update(
                user_id,
                email_verified=True,
                email_verified_at=datetime.now(timezone.utc),
            )

        if updated is None:
            return False

        await self._redis.client.delete(redis_key)
        self._user_cache.pop(user_id, None)
        logger.info(f"email verified for user {user_id}")
        return True

    async def resend_verification(self, email: str) -> None:
        """re-issue a verification token. enumeration-safe: no-op when the email
        is unknown or already verified."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get_by_email(email)

        if not user or user.email_verified:
            return

        await self._issue_email_verification(user.id, email)
        logger.info(f"verification email re-sent for user {user.id}")

    async def update_user_status(self, user_id: str, is_active: bool) -> dict | None:
        """update user active status."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.update(user_id, is_active=is_active)
            if user is None:
                return None
            status_str = "activated" if is_active else "deactivated"
            logger.info(f"{status_str} user {user_id}")
            return self._user_to_dict(user)

    @staticmethod
    async def get_user_stats(tenant_id: str) -> dict[str, int]:
        """get user counts by role for a tenant."""
        async with get_session() as session:
            repo = UserRepository(session)
            return await repo.count_by_role(tenant_id)

    async def get_tenant_usage(self, tenant_id: str) -> dict[str, float]:
        """tenant-wide counts behind the plan limits, from the same queries
        enforcement calls so a published readout and a 409 cannot disagree."""
        async with get_session() as session:
            api_keys = await APIKeyRepository(session).count_by_tenant(tenant_id)
            members = await UserRepository(session).count_by_tenant(tenant_id)
            pending = await InviteRepository(session).count_pending_by_tenant(tenant_id)
            experiments = await ExperimentRepository(session, tenant_id).count_active()

        return {
            "api_keys": api_keys,
            # create_invite checks members + pending against max_seats
            "seats": members + pending,
            "active_experiments": experiments,
            **await self._entitlements.usage(tenant_id),
        }

    # workspace management
    @staticmethod
    async def get_workspace(tenant_id: str) -> dict | None:
        """get workspace details with member count."""
        async with get_session() as session:
            tenant_repo = TenantRepository(session)
            tenant = await tenant_repo.get(tenant_id)

            if not tenant:
                return None

            user_repo = UserRepository(session)
            member_count = await user_repo.count_by_tenant(tenant_id)

            return {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "created_at": (
                    tenant.created_at.timestamp() if tenant.created_at else None
                ),
                "member_count": member_count,
            }

    @staticmethod
    async def update_workspace(
        tenant_id: str,
        name: str | None = None,
        slug: str | None = None,
    ) -> dict | None:
        """update workspace details."""
        name = clean_name(name, "workspace name")
        if slug is not None:
            slug = clean_slug(slug)
        try:
            async with get_session() as session:
                tenant_repo = TenantRepository(session)

                if slug:
                    existing = await tenant_repo.get_by_slug(slug)
                    if existing and existing.id != tenant_id:
                        raise ValueError(f"slug {slug} is already in use")

                kwargs = {}
                if name is not None:
                    kwargs["name"] = name
                if slug is not None:
                    kwargs["slug"] = slug

                tenant = await tenant_repo.update(tenant_id, **kwargs)
                if tenant is None:
                    return None

                logger.info(f"updated workspace {tenant_id}")
                return {
                    "id": tenant.id,
                    "name": tenant.name,
                    "slug": tenant.slug,
                    "created_at": (
                        tenant.created_at.timestamp() if tenant.created_at else None
                    ),
                }
        except IntegrityError:
            raise ValueError(f"slug {slug} is already in use")

    async def list_workspace_members(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """list all members of a workspace."""
        async with get_session() as session:
            repo = UserRepository(session)
            users = await repo.list_by_tenant(tenant_id, limit=limit, offset=offset)
            return [self._user_to_dict(user) for user in users]

    # invite management

    async def create_invite(
        self,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
    ) -> dict:
        """create an invite for a user to join a tenant."""
        from datetime import timedelta

        async with get_session() as session:
            user_repo = UserRepository(session)
            invite_repo = InviteRepository(session)

            # check if email is already a member of this tenant
            existing_user = await user_repo.get_by_email(email)
            if existing_user and existing_user.tenant_id == tenant_id:
                raise ValueError(f"user with email {email} is already a member")

            # check for duplicate pending invite
            existing_invite = await invite_repo.get_pending_by_email_and_tenant(
                email, tenant_id
            )
            if existing_invite:
                raise ValueError(f"pending invite already exists for {email}")

            # check seat limit
            member_count = await user_repo.count_by_tenant(tenant_id)
            pending_count = await invite_repo.count_pending_by_tenant(tenant_id)

            inviter = await user_repo.get(invited_by)
            if not inviter:
                raise ValueError("inviter not found")

            tenant = await TenantRepository(session).get(tenant_id)
            tenant_tier = tenant.plan_tier if tenant else "free"
            max_seats = self._entitlements.limits(tenant_tier)["max_seats"]
            if max_seats != -1 and (member_count + pending_count) >= max_seats:
                raise ValueError(
                    f"seat limit reached for {tenant_tier} plan ({max_seats} seats)"
                )

            # revoking frees the seat, so only a send count bounds revoke/re-invite
            allowed, retry_after = await self.check_auth_endpoint_rate_limit(
                "invite:tenant",
                tenant_id,
                INVITES_PER_TENANT_PER_DAY,
                window_sec=_DAY_SEC,
            )
            if not allowed:
                raise InviteLimitError(
                    f"this workspace has sent its {INVITES_PER_TENANT_PER_DAY} "
                    "invites for today - try again tomorrow",
                    retry_after=retry_after,
                )

            token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=72)

            invite = await invite_repo.create(
                tenant_id=tenant_id,
                email=email,
                role=role,
                token=token,
                invited_by=invited_by,
                expires_at=expires_at,
            )
            logger.info(f"created invite {invite.id} for {email} to tenant {tenant_id}")

            workspace_name = tenant.name if tenant else ""
            inviter_name = inviter.name or inviter.email
            result = self._invite_to_dict(invite)

        invite_url = f"{settings.console_origin}/invite?token={token}"
        result["invite_url"] = invite_url

        try:
            await self._email.send_workspace_invite(
                to=email,
                invite_url=invite_url,
                inviter_name=inviter_name,
                workspace_name=workspace_name,
                expires_at=expires_at,
            )
        except Exception as exc:
            logger.error(f"failed to send invite email to {email}: {exc}")

        return result

    @staticmethod
    async def get_invite_by_token(token: str) -> dict | None:
        """validate and return invite details by token."""
        async with get_session() as session:
            invite_repo = InviteRepository(session)
            invite = await invite_repo.get_by_token(token)

            if not invite:
                return None

            if invite.status != "pending":
                return None

            if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(
                timezone.utc
            ):
                return None

            return {
                "email": invite.email,
                "role": invite.role,
                "workspace_name": invite.tenant.name if invite.tenant else "",
                "expires_at": invite.expires_at.timestamp(),
            }

    async def accept_invite(
        self,
        token: str,
        password: str,
        name: str | None = None,
    ) -> dict:
        """accept an invite and create a user account."""
        name = clean_name(name, "name")
        try:
            async with get_session() as session:
                invite_repo = InviteRepository(session)
                user_repo = UserRepository(session)

                invite = await invite_repo.get_by_token(token)
                if not invite or invite.status != "pending":
                    raise ValueError("invalid or already used invite")

                if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(
                    timezone.utc
                ):
                    raise ValueError("invite has expired")

                # check user doesn't already exist
                existing = await user_repo.get_by_email(invite.email)
                if existing:
                    raise ValueError(f"user with email {invite.email} already exists")

                password_hash = bcrypt.hashpw(
                    password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")

                user = await user_repo.create(
                    email=invite.email,
                    password_hash=password_hash,
                    tenant_id=invite.tenant_id,
                    name=name,
                    role=invite.role,
                    email_verified=True,  # invite receipt proves ownership
                )

                await invite_repo.update_status(invite.id, "accepted")
                logger.info(
                    f"invite {invite.id} accepted, created user {user.id} "
                    f"in tenant {invite.tenant_id}"
                )
                return self._user_to_dict(user)
        except IntegrityError:
            raise ValueError(f"failed to accept invite")

    @staticmethod
    async def revoke_invite(invite_id: str, tenant_id: str) -> bool:
        """revoke a pending invite."""
        async with get_session() as session:
            invite_repo = InviteRepository(session)
            # verify the invite belongs to the tenant
            stmt = select(Invite).where(
                Invite.id == invite_id,
                Invite.tenant_id == tenant_id,
                Invite.status == "pending",
            )
            result = await session.execute(stmt)
            invite = result.scalar_one_or_none()
            if not invite:
                return False

            await invite_repo.update_status(invite_id, "revoked")
            logger.info(f"revoked invite {invite_id}")
            return True

    async def list_invites(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """list invites for a tenant."""
        async with get_session() as session:
            invite_repo = InviteRepository(session)
            invites = await invite_repo.list_by_tenant(
                tenant_id, status=status, limit=limit, offset=offset
            )
            return [self._invite_to_dict(inv) for inv in invites]

    @staticmethod
    def _invite_to_dict(invite) -> dict:
        return {
            "id": invite.id,
            "email": invite.email,
            "role": invite.role,
            "status": invite.status,
            "token": invite.token,
            "invited_by": invite.invited_by,
            "expires_at": invite.expires_at.timestamp() if invite.expires_at else None,
            "created_at": invite.created_at.timestamp() if invite.created_at else None,
        }

    # api key management

    async def create_api_key(
        self,
        user_id: str,
        name: str = "Default API Key",
        scopes: list[str] | None = None,
    ) -> tuple[dict, str]:
        """create new api key for user. returns (api_key_dict, plain_key)."""
        async with get_session() as session:
            user_repo = UserRepository(session)
            user = await user_repo.get(user_id)

            if not user:
                raise ValueError(f"user {user_id} not found")

            api_key_repo = APIKeyRepository(session)
            active_keys = await api_key_repo.count_by_tenant(user.tenant_id)

            tenant_tier = user.tenant.plan_tier
            max_keys = self._entitlements.limits(tenant_tier)["max_api_keys"]
            if max_keys != -1 and active_keys >= max_keys:
                raise ValueError(
                    f"api key limit reached for {tenant_tier} plan "
                    f"({max_keys} active keys per workspace)"
                )

            plain_key = self._api_key_prefix + secrets.token_urlsafe(32)
            key_hash = hashlib.sha256(plain_key.encode()).hexdigest()

            if scopes is None:
                scopes = ROLE_SCOPES.get(user.role, [])

            rate_limit = ABUSE_RATE_LIMIT_PER_MINUTE

            api_key = await api_key_repo.create(
                user_id=user_id,
                key_hash=key_hash,
                name=name,
                rate_limit_per_minute=rate_limit,
                scopes=scopes,
            )

            logger.info(f"created api key {api_key.id} for user {user_id}")
            return self._api_key_to_dict(api_key), plain_key

    async def get_api_key(self, api_key_id: str) -> dict | None:
        """get api key by id."""
        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get(api_key_id)
            if api_key is None:
                return None
            return self._api_key_to_dict(api_key)

    async def validate_api_key(self, plain_key: str) -> dict | None:
        """validate api key and return api key dict if valid."""
        if not plain_key.startswith(self._api_key_prefix):
            return None

        key_hash = hashlib.sha256(plain_key.encode()).hexdigest()

        cached = self._api_key_cache.get(key_hash)
        if cached is not None:
            return cached

        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get_by_hash(key_hash)

            if api_key and api_key.is_active:
                result = self._api_key_to_dict(api_key)
                self._api_key_cache[key_hash] = result
                return result

        return None

    async def list_user_api_keys(self, user_id: str) -> list[dict]:
        """list all api keys for user."""
        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_keys = await repo.list_by_user(user_id)
            return [self._api_key_to_dict(k) for k in api_keys]

    async def update_api_key(
        self, api_key_id: str, user_id: str, name: str
    ) -> dict | None:
        """update api key name if it belongs to user."""
        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get(api_key_id)

            if not api_key or api_key.user_id != user_id:
                return None

            api_key = await repo.update(api_key_id, name=name)
            if api_key:
                logger.info(f"updated api key {api_key_id} name to {name}")
            return self._api_key_to_dict(api_key) if api_key else None

    async def rotate_api_key(
        self, api_key_id: str, user_id: str
    ) -> tuple[dict, str] | None:
        """rotate api key by generating new key. returns (api_key_dict, plain_key)."""
        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get(api_key_id)

            if not api_key or api_key.user_id != user_id:
                return None

            expired_key_hash = api_key.key_hash

            plain_key = self._api_key_prefix + secrets.token_urlsafe(32)
            key_hash = hashlib.sha256(plain_key.encode()).hexdigest()

            api_key = await repo.update(api_key_id, key_hash=key_hash)
            if api_key:
                # evict the expired hash so subsequent validate_api_key calls hit the db
                self._api_key_cache.pop(expired_key_hash, None)
                logger.info(f"rotated api key {api_key_id}")
                return self._api_key_to_dict(api_key), plain_key
            return None

    async def deactivate_api_key(self, api_key_id: str, user_id: str) -> bool:
        """deactivate api key if it belongs to user."""
        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get(api_key_id)

            if not api_key or api_key.user_id != user_id:
                return False

            old_key_hash = api_key.key_hash

            result = await repo.deactivate(api_key_id)
            if result:
                # evict the cached entry so the deactivated key is rejected immediately
                self._api_key_cache.pop(old_key_hash, None)
                logger.info(f"deactivated api key {api_key_id}")
            return result

    async def get_api_key_usage(self, api_key_id: str) -> dict:
        """get current usage stats for api key."""
        current_minute = int(time.time() // 60)
        rate_key = f"rate_limit:{api_key_id}:{current_minute}"

        current_count = await self._redis.client.get(rate_key)
        current_count = int(current_count) if current_count else 0

        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get(api_key_id)
            rate_limit = (
                api_key.rate_limit_per_minute
                if api_key
                else ABUSE_RATE_LIMIT_PER_MINUTE
            )

        return {
            "current_minute_usage": current_count,
            "rate_limit_per_minute": rate_limit,
        }

    # rate limiting

    async def check_auth_endpoint_rate_limit(
        self,
        scope: str,
        identifier: str,
        limit: int,
        window_sec: int = 60,
    ) -> tuple[bool, int]:
        """fixed-window rate limit for unauthenticated auth endpoints.

        keyed by (scope, identifier) — identifier is a client ip or an email,
        depending on the bucket. returns (allowed, retry_after_seconds).

        state lives in redis so the limit holds across horizontally-scaled
        proxy replicas. uses an atomic incr so concurrent requests cannot race
        past the threshold.
        """
        if limit <= 0:
            return True, 0

        now = int(time.time())
        window = now // window_sec
        rate_key = f"authrl:{scope}:{identifier}:{window}"

        pipe = self._redis.client.pipeline()
        # noinspection PyAsyncCall
        pipe.incr(rate_key)
        # noinspection PyAsyncCall
        pipe.expire(rate_key, window_sec * 2)
        response = await pipe.execute()

        current_count = int(response[0]) if response[0] else 0
        retry_after = window_sec - (now % window_sec)

        if current_count > limit:
            return False, retry_after

        return True, retry_after

    async def check_api_key_rate_limit(self, api_key_id: str) -> tuple[bool, int, int]:
        """
        check rate limit for api key.
        returns (allowed, remaining, limit).
        """
        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get(api_key_id)

            if not api_key:
                return False, 0, 0

            user_allowed, _, _ = await self._check_user_rate_limit(
                session, api_key.user_id
            )
            if not user_allowed:
                return False, 0, api_key.rate_limit_per_minute

            # unlimited api key — skip rate limiting entirely
            if api_key.rate_limit_per_minute == -1:
                return True, -1, -1

            current_minute = int(time.time() // 60)
            rate_key = f"rate_limit:{api_key_id}:{current_minute}"

            pipe = self._redis.client.pipeline()
            # noinspection PyAsyncCall
            pipe.get(rate_key)
            # noinspection PyAsyncCall
            pipe.incr(rate_key)
            # noinspection PyAsyncCall
            pipe.expire(rate_key, 120)

            response = await pipe.execute()

            current_count = int(response[0]) if response[0] else 0
            if current_count >= api_key.rate_limit_per_minute:
                return False, 0, api_key.rate_limit_per_minute

            remaining = api_key.rate_limit_per_minute - current_count - 1
            return True, remaining, api_key.rate_limit_per_minute

    async def check_user_rate_limit(self, user_id: str) -> tuple[bool, int, int]:
        """
        check rate limit for user.
        returns (allowed, remaining, limit).
        """
        async with get_session() as session:
            return await self._check_user_rate_limit(session, user_id)

    async def _check_user_rate_limit(
        self, session: AsyncSession, user_id: str
    ) -> tuple[bool, int, int]:
        """internal rate limit check that reuses an existing session."""
        repo = UserRepository(session)
        user = await repo.get(user_id)

        if not user:
            return False, 0, 0

        rate_limit = ABUSE_RATE_LIMIT_PER_MINUTE

        if rate_limit == -1:
            return True, -1, -1

        current_minute = int(time.time() // 60)
        rate_key = f"rate_limit:user:{user_id}:{current_minute}"

        pipe = self._redis.client.pipeline()
        # noinspection PyAsyncCall
        pipe.get(rate_key)
        # noinspection PyAsyncCall
        pipe.incr(rate_key)
        # noinspection PyAsyncCall
        pipe.expire(rate_key, 120)

        response = await pipe.execute()

        current_count = int(response[0]) if response[0] else 0
        if current_count >= rate_limit:
            return False, 0, rate_limit

        remaining = rate_limit - current_count - 1
        return True, remaining, rate_limit

    # permissions
    @staticmethod
    async def check_user_permission(user_id: str, required_scope: str) -> bool:
        """check if user has required scope based on role."""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)

            if not user:
                return False

            user_scopes = ROLE_SCOPES.get(user.role, [])
            return required_scope in user_scopes or "system:admin" in user_scopes

    @staticmethod
    async def check_api_key_scope(api_key_id: str, required_scope: str) -> bool:
        """check if api key has required scope."""
        async with get_session() as session:
            repo = APIKeyRepository(session)
            api_key = await repo.get(api_key_id)

            if not api_key:
                return False

            return required_scope in api_key.scopes or "system:admin" in api_key.scopes

    @staticmethod
    def get_scopes_for_role(role: str) -> list[str]:
        """get scopes for a given role."""
        return ROLE_SCOPES.get(role, [])

    # conversion helpers

    @staticmethod
    def _user_to_dict(user) -> dict:
        return {
            "id": user.id,
            "tenant_id": user.tenant_id,
            "email": user.email,
            "name": user.name if hasattr(user, "name") else None,
            "plan_tier": user.tenant.plan_tier,
            "role": user.role,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "created_at": user.created_at.timestamp() if user.created_at else None,
            "updated_at": user.updated_at.timestamp() if user.updated_at else None,
        }

    @staticmethod
    def _api_key_to_dict(api_key) -> dict:
        return {
            "id": api_key.id,
            "user_id": api_key.user_id,
            "name": api_key.name,
            "rate_limit_per_minute": api_key.rate_limit_per_minute,
            "scopes": api_key.scopes,
            "is_active": api_key.is_active,
            "created_at": (
                api_key.created_at.timestamp() if api_key.created_at else None
            ),
            "last_used_at": (
                api_key.last_used_at.timestamp() if api_key.last_used_at else None
            ),
        }
