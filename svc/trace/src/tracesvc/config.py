from pydantic_settings import SettingsConfigDict

from qbrixruntime.config import GrpcSettings


class TraceSettings(GrpcSettings):

    model_config = SettingsConfigDict(env_prefix="TRACE_")

    grpc_port: int = 50053

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    consumer_name: str = "worker-0"

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "qbrix"

    batch_size: int = 500
    flush_interval_sec: float = 5.0
