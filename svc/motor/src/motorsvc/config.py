import warnings

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MotorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOTOR_")

    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50051

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    param_cache_ttl: int = 60
    param_cache_maxsize: int = 1000
    agent_cache_ttl: int = 300
    agent_cache_maxsize: int = 100

    @model_validator(mode="after")
    def validate_ttls(self):
        if self.param_cache_ttl > self.agent_cache_ttl:
            warnings.warn(
                "param_cache_ttl > agent_cache_ttl may cause unnecessary redis lookups"
            )
        return self

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"
