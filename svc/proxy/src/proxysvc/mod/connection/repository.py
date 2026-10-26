from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from qbrixstore.postgres.models import Connection
from qbrixstore.postgres.models import ConnectionToken

from proxysvc.mod.connection.token import REFRESH


class ConnectionRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def active_for(self, user_id: str, client_identity: str) -> Connection | None:
        stmt = select(Connection).where(
            Connection.user_id == user_id,
            Connection.client_identity == client_identity,
            Connection.revoked_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        client_identity: str,
        client_id: str,
        client_name: str,
        client_uri: str | None,
    ) -> Connection:
        connection = Connection(
            tenant_id=tenant_id,
            user_id=user_id,
            client_identity=client_identity,
            client_id=client_id,
            client_name=client_name,
            client_uri=client_uri,
        )
        self._session.add(connection)
        await self._session.flush()
        return connection

    async def get(self, tenant_id: str, connection_id: str) -> Connection | None:
        stmt = (
            select(Connection)
            .options(joinedload(Connection.user))
            .where(
                Connection.id == connection_id,
                Connection.tenant_id == tenant_id,
                Connection.revoked_at.is_(None),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self, tenant_id: str, user_id: str | None = None
    ) -> list[Connection]:
        stmt = (
            select(Connection)
            .options(joinedload(Connection.user))
            .where(Connection.tenant_id == tenant_id, Connection.revoked_at.is_(None))
            .order_by(Connection.created_at.desc(), Connection.id)
        )
        if user_id is not None:
            stmt = stmt.where(Connection.user_id == user_id)
        return list((await self._session.execute(stmt)).scalars())

    async def token(self, token_hash: str) -> ConnectionToken | None:
        """a token with its connection and the connection's person, in one query."""
        stmt = (
            select(ConnectionToken)
            .options(joinedload(ConnectionToken.connection).joinedload(Connection.user))
            .where(ConnectionToken.token_hash == token_hash)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add_token(
        self,
        connection_id: str,
        kind: str,
        token_hash: str,
        resource: str,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            ConnectionToken(
                connection_id=connection_id,
                kind=kind,
                token_hash=token_hash,
                resource=resource,
                expires_at=expires_at,
            )
        )
        await self._session.flush()

    async def drop_tokens(self, connection_id: str, kind: str | None = None) -> None:
        stmt = delete(ConnectionToken).where(
            ConnectionToken.connection_id == connection_id
        )
        if kind is not None:
            stmt = stmt.where(ConnectionToken.kind == kind)
        await self._session.execute(stmt)

    async def prune_used_refresh(self, connection_id: str, now: datetime) -> None:
        """drop exchanged refresh tokens that have expired: presenting one
        again can no longer revoke anything worth protecting."""
        await self._session.execute(
            delete(ConnectionToken)
            .where(
                ConnectionToken.connection_id == connection_id,
                ConnectionToken.kind == REFRESH,
                ConnectionToken.used_at.is_not(None),
                ConnectionToken.expires_at < now,
            )
            .execution_options(synchronize_session=False)
        )

    async def revoke(self, connection: Connection, now: datetime) -> None:
        connection.revoked_at = now
        await self.drop_tokens(connection.id)
        await self._session.flush()
