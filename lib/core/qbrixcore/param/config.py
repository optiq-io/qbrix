from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class ParamBackendCacheConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARAM_BACKEND_CACHE")

    ttl: int = 300
