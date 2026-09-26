from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from qbrixruntime.config import GrpcSettings


class MotorClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROXY_CLIENT_MOTOR_")

    grpc_keepalive_time_ms: int = 30000
    grpc_keepalive_timeout_ms: int = 10000
    grpc_keepalive_permit_without_calls: bool = True
    grpc_http2_max_pings_without_data: int = 0


class CortexClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROXY_CLIENT_CORTEX_")

    grpc_keepalive_time_ms: int = 30000
    grpc_keepalive_timeout_ms: int = 10000
    grpc_keepalive_permit_without_calls: bool = True
    grpc_http2_max_pings_without_data: int = 0


class ProxySettings(GrpcSettings):
    model_config = SettingsConfigDict(env_prefix="PROXY_")

    runenv: str = "prod"

    grpc_port: int = 50050
    grpc_server_thread_pool_size: int = 100

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "qbrix"
    postgres_password: str = "qbrix"
    postgres_database: str = "qbrix"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    motor_host: str = "localhost"
    motor_port: int = 50051
    motor_client_settings: MotorClientSettings = MotorClientSettings()

    cortex_host: str = "localhost"
    cortex_port: int = 50052
    cortex_client_settings: CortexClientSettings = CortexClientSettings()

    token_secret: str = "change-me-in-production"  # need to come from secrets.
    token_max_age_ms: int | None = None

    gate_cache_maxsize: int = 1000
    gate_cache_ttl: float = 30.0  # seconds
    gate_redis_ttl: int = 300  # seconds

    experiment_cache_maxsize: int = 1000
    experiment_cache_ttl: float = 30.0

    # tenant tier/period resolution cache for the selection meter
    usage_cache_maxsize: int = 1000
    usage_cache_ttl: float = 30.0  # seconds
    # min seconds between authoritative re-resolves before rejecting a tenant,
    # so an over-quota tenant can't turn every rejection into a db read
    usage_recheck_cooldown_sec: float = 5.0

    # jwt settings
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # http settings
    http_host: str = "0.0.0.0"
    http_port: int = 8080

    ee_enabled: bool = False
    analytics_enabled: bool = False

    # clickhouse, read by the analytics endpoints
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "qbrix"

    # who may create a workspace through public registration. self-host
    # defaults to the first caller only; cloud sets "open".
    signup_mode: Literal["open", "first-user", "invite-only"] = "first-user"

    # browser origins granted the credentialed console cors policy, on top of
    # the localhost defaults
    cors_origins: str = ""

    # proxies appending to x-forwarded-for in front of the http api: 1 for an
    # ingress or gateway, 2 for cloudfront → alb
    trusted_proxy_hops: int = Field(default=1, ge=0)
    # any client can send CloudFront-Viewer-Address; trust it only when
    # cloudfront is the sole way in and its origin policy adds the header
    trust_cloudfront_header: bool = False

    # base url of the console, used to build verify/reset/invite links.
    # cloud_url is the previous name and is still honoured.
    console_url: str = ""
    cloud_url: str = ""

    # email
    email_provider: Literal["auto", "smtp", "resend", "none"] = "auto"
    email_from: str = "qbrix <noreply@localhost>"
    email_verification_ttl_seconds: int = 86400  # 24h

    resend_api_key: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # ee stripe billing
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_starter: str = ""
    stripe_price_id_growth: str = ""
    stripe_price_id_scale: str = ""
    stripe_price_id_enterprise: str = ""
    # selections billing meter + per-tier metered (overage) prices
    stripe_meter_id: str = ""
    stripe_metered_price_id_starter: str = ""
    stripe_metered_price_id_growth: str = ""
    stripe_metered_price_id_scale: str = ""

    @property
    def console_origin(self) -> str:
        return self.console_url or self.cloud_url or "http://localhost:3001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"

    @property
    def motor_address(self) -> str:
        return f"{self.motor_host}:{self.motor_port}"

    @property
    def cortex_address(self) -> str:
        return f"{self.cortex_host}:{self.cortex_port}"

    @property
    def token_secret_bytes(self) -> bytes:
        return self.token_secret.encode()


settings = ProxySettings()
