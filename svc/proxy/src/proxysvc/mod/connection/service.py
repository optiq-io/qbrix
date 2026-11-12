from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timezone

from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Connection
from qbrixstore.postgres.models import ConnectionToken
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core import autonomy
from proxysvc.core.actor import Actor
from proxysvc.core.error import ConnectionLevelsForbiddenError
from proxysvc.core.error import ConnectionNotFoundError
from proxysvc.core.error import ConnectionRateLimitedError
from proxysvc.core.error import ConnectionTokenInvalidError
from proxysvc.core.error import OAuthError
from proxysvc.mod.auth.limit import count_this_minute
from proxysvc.mod.auth.model import Role
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.connection.repository import ConnectionRepository
from proxysvc.mod.connection.serialize import connection_to_dict
from proxysvc.mod.connection.serialize import levels_snapshot
from proxysvc.mod.connection.serialize import overrides_of
from proxysvc.mod.connection.token import ACCESS
from proxysvc.mod.connection.token import ACCESS_PREFIX
from proxysvc.mod.connection.token import ACCESS_TTL
from proxysvc.mod.connection.token import REFRESH
from proxysvc.mod.connection.token import REFRESH_PREFIX
from proxysvc.mod.connection.token import REFRESH_TTL
from proxysvc.mod.connection.token import UNUSED_LIMIT
from proxysvc.mod.connection.token import hash_token
from proxysvc.mod.connection.token import mint

logger = logging.getLogger(__name__)

TOUCH_INTERVAL_SEC = 60


def _utc(value: datetime) -> datetime:
    """sqlite hands timestamps back naive; postgres keeps the zone."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _invalid_grant(description: str) -> OAuthError:
    return OAuthError("invalid_grant", description)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": self.refresh_token,
            "scope": "qbrix",
        }


@dataclass(frozen=True, slots=True)
class ConnectionPrincipal:
    """who a connection's token acts for, with the person's role and the
    connection's levels as they are now."""

    actor: Actor
    tenant_id: str
    role: str
    levels: Mapping[str, str]

    def level(self, kind: str) -> autonomy.Level:
        return autonomy.level_of(kind, self.levels)

    def acting(self, kind: str, *also: str) -> Actor:
        """the connection's actor for one change, at its level for the kind,
        or the strictest of the kinds a change is also."""
        level = max((self.level(k) for k in (kind, *also)), key=autonomy.LEVELS.index)
        return replace(self.actor, level=level)


class ConnectionService:
    """connections and their tokens.

    a token is opaque and stored as its sha-256. checking one reads the token,
    its connection and its person in one query, so revoking a connection or
    changing the person's role holds from the next call on every replica.
    """

    def __init__(self, *, redis: RedisClient, settings: ProxySettings):
        self._redis = redis
        self._settings = settings

    async def open(
        self,
        *,
        user_id: str,
        tenant_id: str,
        client_identity: str,
        client_id: str,
        client_name: str,
        client_uri: str | None,
        resource: str,
    ) -> IssuedTokens:
        """sign a client in for a person: renew its connection, or create one."""
        async with get_session() as session:
            repo = ConnectionRepository(session)
            connection = await repo.active_for(user_id, client_identity)
            if connection is None:
                connection = await repo.create(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    client_identity=client_identity,
                    client_id=client_id,
                    client_name=client_name,
                    client_uri=client_uri,
                )
                logger.info(f"connection {connection.id} opened for user {user_id}")
            else:
                connection.client_id = client_id
                connection.client_name = client_name
                connection.client_uri = client_uri
                await repo.drop_tokens(connection.id)
                logger.info(f"connection {connection.id} renewed for user {user_id}")
            return await self._issue(repo, connection, resource)

    async def refresh(
        self, refresh_token: str, *, client_id: str, resource: str | None
    ) -> IssuedTokens:
        """exchange a refresh token for a new pair. a refresh token presented a
        second time revokes its connection: one of the two holders stole it."""
        now = datetime.now(timezone.utc)
        reused = False
        async with get_session() as session:
            repo = ConnectionRepository(session)
            token = await repo.token(hash_token(refresh_token))
            if token is None or token.kind != REFRESH:
                raise _invalid_grant("the refresh token is unknown")
            connection = token.connection
            if connection.revoked_at is not None:
                raise _invalid_grant("this connection was revoked; sign in again")
            if connection.client_id != client_id:
                raise _invalid_grant("the refresh token was issued to another client")
            if token.used_at is not None:
                await repo.revoke(connection, now)
                reused = True
            else:
                self._check_refreshable(token, connection, now, resource)
                token.used_at = now
                await repo.drop_tokens(connection.id, ACCESS)
                await repo.prune_used_refresh(connection.id, now)
                return await self._issue(repo, connection, token.resource)
        if reused:
            logger.warning(f"refresh token reused: connection {connection.id} revoked")
        raise _invalid_grant("the refresh token was already used; sign in again")

    @staticmethod
    def _check_refreshable(
        token: ConnectionToken,
        connection: Connection,
        now: datetime,
        resource: str | None,
    ) -> None:
        if _utc(token.expires_at) <= now:
            raise _invalid_grant("the refresh token expired; sign in again")
        last_used = connection.last_used_at or connection.created_at
        if _utc(last_used) <= now - UNUSED_LIMIT:
            raise _invalid_grant(
                "this connection went unused for 90 days; sign in again"
            )
        if resource is not None and resource != token.resource:
            raise OAuthError(
                "invalid_target", "the refresh token was issued for another resource"
            )

    @staticmethod
    async def _issue(
        repo: ConnectionRepository, connection: Connection, resource: str
    ) -> IssuedTokens:
        now = datetime.now(timezone.utc)
        access, access_hash = mint(ACCESS_PREFIX)
        refresh, refresh_hash = mint(REFRESH_PREFIX)
        await repo.add_token(
            connection.id, ACCESS, access_hash, resource, now + ACCESS_TTL
        )
        await repo.add_token(
            connection.id, REFRESH, refresh_hash, resource, now + REFRESH_TTL
        )
        return IssuedTokens(access_token=access, refresh_token=refresh)

    async def authenticate(
        self, access_token: str, *, request_id: str = ""
    ) -> ConnectionPrincipal:
        """the person a connection's access token acts for, counted against
        that connection's request limit."""
        if not access_token.startswith(ACCESS_PREFIX):
            raise ConnectionTokenInvalidError("not a connection's access token")
        async with get_session() as session:
            token = await ConnectionRepository(session).token(hash_token(access_token))
            if token is None or token.kind != ACCESS:
                raise ConnectionTokenInvalidError("the access token is unknown")
            connection = token.connection
            user = connection.user
            if connection.revoked_at is not None:
                raise ConnectionTokenInvalidError("this connection was revoked")
            if _utc(token.expires_at) <= datetime.now(timezone.utc):
                raise ConnectionTokenInvalidError("the access token expired")
            if token.resource != self._settings.mcp_resource:
                raise ConnectionTokenInvalidError(
                    "the access token was issued for another resource"
                )
            if not user.is_active:
                raise ConnectionTokenInvalidError("this person's account is inactive")
            principal = ConnectionPrincipal(
                actor=Actor.connection(
                    user.id,
                    connection_id=connection.id,
                    client_name=connection.client_name,
                    request_id=request_id,
                ),
                tenant_id=connection.tenant_id,
                role=user.role,
                levels=overrides_of(connection),
            )
        await self._count(connection.id)
        await self._touch(connection.id)
        return principal

    async def _count(self, connection_id: str) -> None:
        await self._limit(
            f"rate_limit:connection:{connection_id}",
            self._settings.mcp_calls_per_minute,
            "this connection made too many requests this minute",
        )

    async def count_change(self, connection_id: str) -> None:
        """count one change against the connection's cap on changes, which
        binds within its cap on calls; reads never count here."""
        await self._limit(
            f"rate_limit:connection:{connection_id}:changes",
            self._settings.mcp_changes_per_minute,
            "this connection made too many changes this minute",
        )

    async def _limit(self, prefix: str, limit: int, message: str) -> None:
        now = int(time.time())
        count = await count_this_minute(self._redis.client, f"{prefix}:{now // 60}")
        if count is not None and count >= limit:
            raise ConnectionRateLimitedError(
                message, limit=limit, retry_after=60 - now % 60
            )

    async def _touch(self, connection_id: str) -> None:
        first = await self._redis.client.set(
            f"qbrix:connection:touched:{connection_id}",
            1,
            nx=True,
            ex=TOUCH_INTERVAL_SEC,
        )
        if not first:
            return
        async with get_session() as session:
            connection = await session.get(Connection, connection_id)
            if connection is not None:
                connection.last_used_at = datetime.now(timezone.utc)

    async def revoke_token(self, token: str) -> None:
        """revoke the connection a token of either kind belongs to; an unknown
        token is not an error."""
        async with get_session() as session:
            repo = ConnectionRepository(session)
            found = await repo.token(hash_token(token))
            if found is None or found.connection.revoked_at is not None:
                return
            await repo.revoke(found.connection, datetime.now(timezone.utc))
            logger.info(f"connection {found.connection_id} revoked by its client")

    async def list(self, tenant_id: str, *, user_id: str, role: str) -> list[dict]:
        """an admin sees every connection in the workspace; anyone else their own."""
        async with get_session() as session:
            connections = await ConnectionRepository(session).list(
                tenant_id, None if role == Role.ADMIN.value else user_id
            )
            return [connection_to_dict(c) for c in connections]

    async def revoke(
        self, tenant_id: str, connection_id: str, *, user_id: str, role: str
    ) -> None:
        async with get_session() as session:
            repo = ConnectionRepository(session)
            connection = await self._visible(
                repo, tenant_id, connection_id, user_id, role
            )
            await repo.revoke(connection, datetime.now(timezone.utc))
            logger.info(f"connection {connection_id} revoked by user {user_id}")

    async def levels(
        self, tenant_id: str, connection_id: str, *, user_id: str, role: str
    ) -> list[dict]:
        """every kind of change with this connection's level; an admin reads
        anyone's, anyone else their own."""
        async with get_session() as session:
            connection = await self._visible(
                ConnectionRepository(session), tenant_id, connection_id, user_id, role
            )
            return autonomy.levels(overrides_of(connection))

    async def set_levels(
        self,
        tenant_id: str,
        connection_id: str,
        levels: Mapping[str, str] | None,
        *,
        actor: Actor,
        role: str,
        reason: str | None = None,
    ) -> dict:
        """set some of a connection's levels, or with None return them all to
        their defaults, as one connection.levels change. only its person sets
        them; an admin sees them but can't."""
        if levels is not None:
            autonomy.check(levels)
        async with get_session() as session:
            repo = ConnectionRepository(session)
            connection = await self._visible(
                repo, tenant_id, connection_id, actor.user_id, role
            )
            current = overrides_of(connection)
            wanted = {} if levels is None else {**current, **levels}
            change_id = await self._write(
                session, repo, connection, wanted, actor, reason=reason
            )
            return {
                "levels": autonomy.levels(autonomy.normalise(wanted)),
                "change_id": change_id,
            }

    async def restore_levels(
        self,
        tenant_id: str,
        connection_id: str,
        overrides: Mapping[str, str],
        *,
        actor: Actor,
        undoing: Undoing,
    ) -> bool:
        """write back the levels an undone change left; false when the
        connection is gone."""
        async with get_session() as session:
            repo = ConnectionRepository(session)
            connection = await repo.get(tenant_id, connection_id)
            if connection is None:
                return False
            await self._write(
                session, repo, connection, dict(overrides), actor, undoing=undoing
            )
            return True

    @staticmethod
    async def _visible(
        repo: ConnectionRepository,
        tenant_id: str,
        connection_id: str,
        user_id: str,
        role: str,
    ) -> Connection:
        connection = await repo.get(tenant_id, connection_id)
        if connection is None or (
            role != Role.ADMIN.value and connection.user_id != user_id
        ):
            raise ConnectionNotFoundError(f"no connection with id {connection_id}")
        return connection

    @staticmethod
    async def _write(
        session: AsyncSession,
        repo: ConnectionRepository,
        connection: Connection,
        wanted: Mapping[str, str],
        actor: Actor,
        *,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> str | None:
        if actor.kind != "member" or actor.user_id != connection.user_id:
            raise ConnectionLevelsForbiddenError(
                "only a connection's own person can set its levels, in the console"
            )
        before = overrides_of(connection)
        after = autonomy.normalise(wanted)
        if after == before and undoing is None:
            return None
        await repo.set_levels(connection.id, after)
        change = await ChangeRepository(session, connection.tenant_id).record(
            "connection.levels",
            "connection",
            connection.id,
            actor,
            before=levels_snapshot(connection, before),
            after=levels_snapshot(connection, after),
            reason=reason,
            undoing=undoing,
        )
        logger.info(f"levels of connection {connection.id} set by user {actor.user_id}")
        return change.id
