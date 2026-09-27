import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from esp import jobs
from esp.api.schemas import (
    DatasetResult,
    DatasetSummary,
    DatasetVersionSummary,
    IngestionRunSummary,
    Screening,
    ScreeningRequest,
)
from esp.config import get_settings
from esp.db import get_session
from esp.models import Dataset, DatasetVersion, IngestionRun, ScreeningJob, ScreeningResult
from esp.screening import FEATURES

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


def _validate_aoi(session: Session, geometry: dict[str, Any]) -> None:
    """Reject AOIs that are invalid, too large, or outside the screening region."""
    settings = get_settings()
    west, south, east, north = settings.region_bbox
    check = session.execute(
        text(
            """
            WITH g AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS geom)
            SELECT ST_IsValid(geom), ST_IsValidReason(geom), ST_Area(geom::geography),
                   ST_Within(geom, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
            FROM g
            """
        ),
        {"g": json.dumps(geometry), "w": west, "s": south, "e": east, "n": north},
    ).one()
    valid, reason, area_m2, inside = check
    if not valid:
        raise HTTPException(422, f"AOI geometry is invalid: {reason}")
    if area_m2 <= 0:
        raise HTTPException(422, "AOI has no area")
    if area_m2 > settings.max_aoi_km2 * 1e6:
        raise HTTPException(
            422,
            f"AOI is {area_m2 / 1e6:.1f} km²; the public demo accepts up to "
            f"{settings.max_aoi_km2:g} km²",
        )
    if not inside:
        raise HTTPException(422, f"AOI must lie within {settings.region_name}")


def _screening(session: Session, job: ScreeningJob) -> Screening:
    aoi = session.execute(
        text("SELECT name, area_m2, ST_AsGeoJSON(geom, 6) FROM aois WHERE id = :id"),
        {"id": job.aoi_id},
    ).one()
    titles: dict[str, str] = {
        id_: title for id_, title in session.execute(select(Dataset.id, Dataset.title))
    }
    results = session.scalars(select(ScreeningResult).where(ScreeningResult.job_id == job.id)).all()
    return Screening(
        id=job.id,
        name=aoi.name,
        status=job.status,
        attempts=job.attempts,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        aoi_area_m2=aoi.area_m2,
        aoi=json.loads(aoi[2]),
        dataset_versions={k: uuid.UUID(v) for k, v in job.dataset_versions.items()},
        results=[
            DatasetResult(
                dataset_id=r.dataset_id,
                dataset_title=titles.get(r.dataset_id, r.dataset_id),
                version_id=r.version_id,
                status=r.status,
                metrics=r.metrics,
                error=r.error,
            )
            for r in results
        ],
    )


@router.post("/screenings", status_code=202, response_model=Screening)
def create_screening(
    request: ScreeningRequest,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> Screening:
    geometry = request.geometry.model_dump()
    _validate_aoi(session, geometry)
    job = jobs.submit(session, request.name, geometry, idempotency_key)
    session.commit()
    response.headers["Location"] = f"/api/screenings/{job.id}"
    return _screening(session, job)


@router.get("/screenings/{job_id}", response_model=Screening)
def get_screening(job_id: uuid.UUID, session: SessionDep) -> Screening:
    job = session.get(ScreeningJob, job_id)
    if job is None:
        raise HTTPException(404, "screening not found")
    return _screening(session, job)


@router.get("/screenings/{job_id}/features/{dataset_id}")
def get_screening_features(job_id: uuid.UUID, dataset_id: str, session: SessionDep) -> Any:
    """Features of the pinned dataset version, clipped to the AOI (GeoJSON)."""
    job = session.get(ScreeningJob, job_id)
    if job is None:
        raise HTTPException(404, "screening not found")
    version_id = job.dataset_versions.get(dataset_id)
    if version_id is None or dataset_id not in FEATURES:
        raise HTTPException(404, f"no {dataset_id} features for this screening")
    return FEATURES[dataset_id](session, job.aoi_id, version_id)


@router.get("/datasets", response_model=list[DatasetSummary])
def list_datasets(session: SessionDep) -> list[DatasetSummary]:
    summaries = []
    for dataset in session.scalars(select(Dataset).order_by(Dataset.id)):
        active = (
            session.get(DatasetVersion, dataset.active_version_id)
            if dataset.active_version_id
            else None
        )
        last_run = session.scalar(
            select(IngestionRun)
            .where(IngestionRun.dataset_id == dataset.id)
            .order_by(IngestionRun.started_at.desc())
            .limit(1)
        )
        summaries.append(
            DatasetSummary(
                id=dataset.id,
                title=dataset.title,
                provider=dataset.provider,
                license=dataset.license,
                homepage=dataset.homepage,
                active_version=DatasetVersionSummary.model_validate(active, from_attributes=True)
                if active
                else None,
                last_run=IngestionRunSummary.model_validate(last_run, from_attributes=True)
                if last_run
                else None,
            )
        )
    return summaries
