import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Position = list[float]


class PolygonGeometry(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[Position]]


class MultiPolygonGeometry(BaseModel):
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[Position]]]


class ScreeningRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geometry: PolygonGeometry | MultiPolygonGeometry = Field(discriminator="type")


class DatasetResult(BaseModel):
    dataset_id: str
    dataset_title: str
    version_id: uuid.UUID | None
    status: str
    metrics: dict[str, Any] | None
    error: str | None


class Screening(BaseModel):
    id: uuid.UUID
    name: str
    status: Literal["queued", "running", "succeeded", "failed"]
    attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    aoi_area_m2: float
    aoi: dict[str, Any] = Field(description="AOI as a GeoJSON MultiPolygon")
    dataset_versions: dict[str, uuid.UUID]
    results: list[DatasetResult]


class IngestionRunSummary(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class DatasetVersionSummary(BaseModel):
    id: uuid.UUID
    activated_at: datetime | None
    provider_release: dict[str, Any]
    stats: dict[str, Any] | None


class DatasetSummary(BaseModel):
    id: str
    title: str
    provider: str
    license: str
    homepage: str
    active_version: DatasetVersionSummary | None
    last_run: IngestionRunSummary | None
