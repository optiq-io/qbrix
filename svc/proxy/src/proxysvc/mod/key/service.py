from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Protocol

from qbrixstore.postgres.models import APIKey
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.session import get_session

from proxysvc.core.actor import Actor
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.error import KeyLimitError
from proxysvc.core.error import KeyNotFoundError
from proxysvc.mod.auth.repository import APIKeyRepository
from proxysvc.mod.auth.scope import ABUSE_RATE_LIMIT_PER_MINUTE
from proxysvc.mod.auth.service import mint_api_key
from proxysvc.mod.key.rule import label
from proxysvc.mod.people import People

logger = logging.getLogger(__name__)


class KeyAnnouncer(Protocol):
    async def publish(self, key_hash: str, /) -> None: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _entry(key: APIKey, people: People) -> dict:
    return {
        "id": key.id,
        "app": key.app,
        "environment": key.environment,
        "created_by": (
            {"id": key.created_by_id, "name": people.name(key.created_by_id)}
            if key.created_by_id
            else None
        ),
        "created_at": _iso(key.created_at),
        "rotated_at": _iso(key.rotated_at),
    }


class KeyService:
    """the workspace's keys, which apps use on the request path.

    a setting admins manage, not a change: nothing here records a change, and
    a secret leaves qbrix only in the response that made it. a revoke or a
    rotate announces the hash it no longer accepts, so every replica drops
    its cached validation at once.
    """

    def __init__(
        self,
        *,
        entitlements: Entitlements,
        announcer: KeyAnnouncer,
        clock: Callable[[], datetime] = _now,
    ):
        self._entitlements = entitlements
        self._announcer = announcer
        self._clock = clock

    async def list(self, tenant_id: str) -> list[dict]:
        async with get_session() as session:
            keys = await APIKeyRepository(session).list_by_tenant(tenant_id)
            people = await People.load(
                session, tenant_id, (k.created_by_id or "" for k in keys)
            )
        return [_entry(k, people) for k in keys]

    async def create(
        self, tenant_id: str, *, app: str, environment: str, actor: Actor
    ) -> dict:
        app = label(app, "app")
        environment = label(environment, "environment")
        plain_key, key_hash = mint_api_key()
        async with get_session() as session:
            repo = APIKeyRepository(session)
            tenant = await session.get(Tenant, tenant_id)
            cap = self._entitlements.limits(tenant.plan_tier)["max_api_keys"]
            if cap != -1 and await repo.count_by_tenant(tenant_id) >= cap:
                raise KeyLimitError(
                    f"the {tenant.plan_tier} plan allows {cap} active keys "
                    f"per workspace"
                )
            key = await repo.create(
                tenant_id=tenant_id,
                key_hash=key_hash,
                app=app,
                environment=environment,
                created_by_id=actor.user_id,
                rate_limit_per_minute=ABUSE_RATE_LIMIT_PER_MINUTE,
            )
            people = await People.load(session, tenant_id, [actor.user_id])
            found = _entry(key, people)
        logger.info(f"created key {found['id']} in tenant {tenant_id}")
        return {**found, "secret": plain_key}

    async def rename(
        self,
        tenant_id: str,
        key_id: str,
        *,
        app: str | None = None,
        environment: str | None = None,
    ) -> dict:
        async with get_session() as session:
            key = await self._get(session, tenant_id, key_id)
            if app is not None:
                key.app = label(app, "app")
            if environment is not None:
                key.environment = label(environment, "environment")
            await session.flush()
            people = await People.load(session, tenant_id, [key.created_by_id or ""])
            return _entry(key, people)

    async def rotate(self, tenant_id: str, key_id: str) -> dict:
        """a new secret for the same key; the old one is refused at once."""
        plain_key, key_hash = mint_api_key()
        async with get_session() as session:
            key = await self._get(session, tenant_id, key_id)
            expired = key.key_hash
            key.key_hash = key_hash
            key.rotated_at = self._clock()
            await session.flush()
            people = await People.load(session, tenant_id, [key.created_by_id or ""])
            found = _entry(key, people)
        await self._announcer.publish(expired)
        logger.info(f"rotated key {key_id} in tenant {tenant_id}")
        return {**found, "secret": plain_key}

    async def revoke(self, tenant_id: str, key_id: str) -> None:
        async with get_session() as session:
            key = await self._get(session, tenant_id, key_id)
            key.is_active = False
            revoked = key.key_hash
        await self._announcer.publish(revoked)
        logger.info(f"revoked key {key_id} in tenant {tenant_id}")

    @staticmethod
    async def _get(session, tenant_id: str, key_id: str) -> APIKey:
        key = await APIKeyRepository(session).get_active_in_tenant(tenant_id, key_id)
        if key is None:
            raise KeyNotFoundError(f"key {key_id} not found")
        return key
