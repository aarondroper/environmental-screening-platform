from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ESP_")

    database_url: str = "postgresql+psycopg://esp:esp@localhost:5432/esp"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
