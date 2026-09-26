import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from qbrixstore.config import PostgresSettings

logger = logging.getLogger(__name__)


_engine = None
_session_factory = None


def init_db(
    settings: PostgresSettings | None = None,
) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory

    if settings is None:
        settings = PostgresSettings()

    _engine = create_async_engine(
        settings.dsn,
        echo=False,
        pool_pre_ping=settings.pool_pre_ping,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_recycle=settings.pool_recycle,
        pool_timeout=settings.pool_timeout,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _session_factory() as session:  # noqa
        try:
            yield session
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:  # noqa
                logger.error("rollback failed after operation error", exc_info=True)
            raise
