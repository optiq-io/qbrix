import logging
from typing import Optional

from proxysvc.http.auth.operator import auth_operator
from proxysvc.http.auth.model import PlanTier, Role, User
from proxysvc.config import settings

logger = logging.getLogger(__name__)

DEV_USER_EMAIL = "dev.user@optiq.io"
DEV_USER_PASSWORD = "dev"
DEV_USER_ROLE = Role.ADMIN
DEV_USER_PLAN = PlanTier.ENTERPRISE


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
        existing_user = await auth_operator.get_user_by_email(DEV_USER_EMAIL)
        if existing_user:
            logger.info(
                f"dev user already exists: {DEV_USER_EMAIL} (id: {existing_user.id})"
            )

            api_keys = await auth_operator.get_user_api_keys(existing_user.id)
            if api_keys:
                logger.info(f"dev user has {len(api_keys)} API key(s)")
                return None

            # user exists but has no API keys, create one
            logger.info("dev user has no API keys, creating one...")
            api_key, plain_key = await auth_operator.create_api_key(
                user_id=existing_user.id, name="Dev API Key"
            )
            logger.info(f"created dev api key: {plain_key}")
            logger.info(f"  key id: {api_key.id}")
            logger.info(f"  rate limit: {api_key.rate_limit_per_minute}/min")
            logger.info(f"  scopes: {', '.join(api_key.scopes)}")
            return existing_user, plain_key

        # create dev user
        logger.info(f"creating dev user: {DEV_USER_EMAIL}")
        user = await auth_operator.create_user(
            email=DEV_USER_EMAIL,
            password=DEV_USER_PASSWORD,
            plan_tier=DEV_USER_PLAN,
            role=DEV_USER_ROLE,
        )
        logger.info(f"dev user created successfully:")
        logger.info(f"  email: {user.email}")
        logger.info(f"  role: {user.role.value}")
        logger.info(f"  plan: {user.plan_tier.value}")
        logger.info(f"  id: {user.id}")

        # create API key for dev user
        api_key, plain_key = await auth_operator.create_api_key(
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

    except Exception as e:
        logger.error(f"Failed to seed dev user: {e}")
        return None
