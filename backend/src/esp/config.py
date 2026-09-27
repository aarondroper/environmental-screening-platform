from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ESP_")

    database_url: str = "postgresql+psycopg://esp:esp@localhost:5432/esp"
    log_level: str = "INFO"
    raw_dir: Path = Path("data/raw")
    # Public-demo guardrail on screening cost.
    max_aoi_km2: float = 250.0
    # Screening region (D3). Colorado's borders follow lines of latitude/longitude, so its
    # bounding box (TIGER 2025) is a close interim stand-in for the state boundary.
    region_name: str = "Colorado"
    region_bbox: tuple[float, float, float, float] = (
        -109.060253,
        36.992426,
        -102.041524,
        41.003444,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
