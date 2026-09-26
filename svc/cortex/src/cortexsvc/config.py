from pydantic_settings import SettingsConfigDict

from qbrixruntime.config import GrpcSettings


class CortexSettings(GrpcSettings):

    model_config = SettingsConfigDict(env_prefix="CORTEX_")

    grpc_port: int = 50052

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    consumer_name: str = "worker-0"

    batch_size: int = 256
    batch_timeout_ms: int = 100
    num_workers: int = 4
