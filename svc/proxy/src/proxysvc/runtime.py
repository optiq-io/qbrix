from __future__ import annotations

from qbrixlog import get_logger
from qbrixstore.config import PostgresSettings
from qbrixstore.config import RedisSettings
from qbrixstore.postgres.session import init_db
from qbrixstore.redis.client import RedisClient

from proxysvc import edition
from proxysvc.config import ProxySettings
from proxysvc.core.invalidation import TenantInvalidation
from proxysvc.mod.auth import AuthService
from proxysvc.mod.auth import create_auth_service
from proxysvc.mod.auth import init_operators
from proxysvc.service import ProxyService

logger = get_logger(__name__)


class ProxyRuntime:
    """owns every long-lived component of a proxy process.

    the transports (grpc, http, or both) are built on top of a started runtime
    and are not part of it: which ports a process listens on is a deployment
    choice, whereas everything assembled here is the same in all three modes.

    components are started in dependency order and stopped in reverse, in one
    place, so adding one is a single edit rather than four.
    """

    def __init__(self, settings: ProxySettings):
        self._settings = settings
        self._redis: RedisClient | None = None
        self._proxy_service: ProxyService | None = None
        self._auth_service: AuthService | None = None
        self._invalidation: TenantInvalidation | None = None

    @property
    def proxy_service(self) -> ProxyService:
        if self._proxy_service is None:
            raise RuntimeError("runtime not started")
        return self._proxy_service

    @property
    def auth_service(self) -> AuthService:
        if self._auth_service is None:
            raise RuntimeError("runtime not started")
        return self._auth_service

    async def start(self) -> None:
        self._verify_secrets()

        init_db(
            PostgresSettings(
                host=self._settings.postgres_host,
                port=self._settings.postgres_port,
                user=self._settings.postgres_user,
                password=self._settings.postgres_password,
                database=self._settings.postgres_database,
            )
        )

        redis_settings = RedisSettings(
            host=self._settings.redis_host,
            port=self._settings.redis_port,
            password=self._settings.redis_password,
            db=self._settings.redis_db,
        )
        self._redis = RedisClient(redis_settings)
        await self._redis.connect()

        self._proxy_service = ProxyService(self._settings)
        await self._proxy_service.start()

        self._auth_service = create_auth_service(
            self._redis, self._proxy_service.entitlements
        )
        init_operators(self._auth_service)

        # entitlements are cached per replica but changed by whichever replica
        # serves the billing event, so the change has to be broadcast.
        self._invalidation = TenantInvalidation(redis_settings)
        self._invalidation.register(self._auth_service.invalidate_tenant)
        self._invalidation.register(self._proxy_service.entitlements.invalidate)
        edition.register_components(self._settings, self._invalidation)
        await self._invalidation.start()

        logger.info("proxy runtime started")

    async def stop(self) -> None:
        if self._invalidation is not None:
            await self._invalidation.stop()
        if self._proxy_service is not None:
            await self._proxy_service.stop()
        if self._redis is not None:
            await self._redis.close()
        logger.info("proxy runtime stopped")

    async def __aenter__(self) -> "ProxyRuntime":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    def _verify_secrets(self) -> None:
        if self._settings.runenv == "dev":
            return
        if self._settings.jwt_secret_key == "change-me-in-production":
            raise RuntimeError("PROXY_JWT_SECRET_KEY must be set in production")
        if self._settings.token_secret == "change-me-in-production":
            raise RuntimeError("PROXY_TOKEN_SECRET must be set in production")
