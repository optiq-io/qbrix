import logging
from datetime import datetime
from datetime import timezone
from typing import Optional

import bcrypt
from qbrixstore.postgres.session import get_session
from qbrixstore.postgres.models import Tenant, User as UserModel

from proxysvc.mod.auth import operator
from proxysvc.mod.auth.model import User
from proxysvc.config import settings
from proxysvc.mod.auth.constant import (
    DEV_USER_ID,
    DEV_TENANT_ID,
    DEV_TENANT_NAME,
    DEV_TENANT_SLUG,
    DEV_USER_EMAIL,
    DEV_USER_PASSWORD,
    DEV_USER_NAME,
    DEV_USER_ROLE,
    DEV_USER_PLAN,
)

logger = logging.getLogger(__name__)


async def _ensure_dev_tenant() -> str:
    """ensure dev tenant exists and return its id."""
    async with get_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(Tenant).where(Tenant.id == DEV_TENANT_ID))
        tenant = result.scalar_one_or_none()

        if tenant:
            logger.info(f"dev tenant already exists: {DEV_TENANT_ID}")
            return tenant.id

        tenant = Tenant(
            id=DEV_TENANT_ID,
            name=DEV_TENANT_NAME,
            slug=DEV_TENANT_SLUG,
            plan_tier=DEV_USER_PLAN.value,
        )
        session.add(tenant)
        await session.flush()
        logger.info(f"created dev tenant: {DEV_TENANT_ID}")
        return tenant.id


async def seed_dev_user() -> Optional[tuple[User, str]]:
    """
    Seeds a development user with admin privileges and an API key.
    Only runs when RUNENV=dev.

    Returns:
        tuple[User, str]: The created user and API key (plain text), or None if user already exists
    """
    if settings.runenv != "dev":
        logger.warning("seed_dev_user called but RUNENV is not 'dev', skipping seed")
        return None

    try:
        # ensure dev tenant exists first
        tenant_id = await _ensure_dev_tenant()

        existing_user = await operator.auth_operator.get_user_by_email(DEV_USER_EMAIL)
        if existing_user:
            logger.info(
                f"dev user already exists: {DEV_USER_EMAIL} (id: {existing_user.id})"
            )

            api_keys = await operator.auth_operator.get_user_api_keys(existing_user.id)
            if api_keys:
                logger.info(f"dev user has {len(api_keys)} API key(s)")
                return None

            # user exists but has no API keys, create one
            logger.info("dev user has no API keys, creating one...")
            api_key, plain_key = await operator.auth_operator.create_api_key(
                user_id=existing_user.id, name="Dev API Key"
            )
            logger.info(f"created dev api key: {plain_key}")
            logger.info(f"  key id: {api_key.id}")
            logger.info(f"  rate limit: {api_key.rate_limit_per_minute}/min")
            logger.info(f"  scopes: {', '.join(api_key.scopes)}")
            return existing_user, plain_key

        # create dev user with explicit id so it matches DEV_USER_ID
        logger.info(f"creating dev user: {DEV_USER_EMAIL}")
        password_hash = bcrypt.hashpw(
            DEV_USER_PASSWORD.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        async with get_session() as session:
            db_user = UserModel(
                id=DEV_USER_ID,
                email=DEV_USER_EMAIL,
                password_hash=password_hash,
                tenant_id=tenant_id,
                name=DEV_USER_NAME,
                role=DEV_USER_ROLE.value,
                email_verified=True,
                email_verified_at=datetime.now(timezone.utc),
            )
            session.add(db_user)
            await session.flush()

        user = await operator.auth_operator.get_user(DEV_USER_ID)
        logger.info(f"dev user created successfully:")
        logger.info(f"  email: {user.email}")
        logger.info(f"  role: {user.role}")
        logger.info(f"  plan: {user.plan_tier}")
        logger.info(f"  id: {user.id}")

        # create API key for dev user
        api_key, plain_key = await operator.auth_operator.create_api_key(
            user_id=user.id, name="Dev API Key"
        )
        logger.info(f"dev api key created: {plain_key}")
        logger.info(f"  key id: {api_key.id}")
        logger.info(f"  rate limit: {api_key.rate_limit_per_minute}/min")
        logger.info(f"  scopes: {', '.join(api_key.scopes)}")

        logger.info("=" * 80)  # noqa
        logger.info("DEV MODE: use these credentials to test authentication:")
        logger.info(f"  Email: {DEV_USER_EMAIL}")
        logger.info(f"  Password: {DEV_USER_PASSWORD}")
        logger.info(f"  API Key: {plain_key}")
        logger.info("=" * 80)

        return user, plain_key

    except Exception:
        logger.error("failed to seed dev user", exc_info=True)
        raise
