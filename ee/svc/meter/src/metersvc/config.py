from pydantic_settings import SettingsConfigDict

from qbrixruntime.config import GrpcSettings


class MeterSettings(GrpcSettings):
    model_config = SettingsConfigDict(env_prefix="METER_")

    grpc_port: int = 50054

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    consumer_name: str = "worker-0"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "qbrix"
    postgres_password: str = ""
    postgres_database: str = "qbrix"

    stripe_secret_key: str = ""
    # the meter's event_name (Stripe MeterEvent.create keys on this, not the
    # meter id).
    stripe_meter_event_name: str = "selections"

    # wall-clock bucket width; selections are summed per (tenant, bucket) and
    # emitted once per bucket with a deterministic idempotency identifier.
    bucket_seconds: int = 60
    # grace after a bucket ends before it is closed and emitted, so late-arriving
    # stream messages for that bucket are included.
    close_grace_seconds: int = 30
    # how often the close/emit pass runs.
    emit_interval_seconds: float = 5.0

    # tenant -> stripe customer resolution cache.
    customer_cache_maxsize: int = 10_000
    customer_cache_ttl_seconds: float = 60.0

    batch_size: int = 500
    block_ms: int = 100

    log_level: str = "INFO"

    @property
    def bucket_ms(self) -> int:
        return self.bucket_seconds * 1000
