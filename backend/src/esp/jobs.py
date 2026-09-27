"""Screening jobs on a PostgreSQL queue.

Workers claim with `FOR UPDATE SKIP LOCKED`, so several can run safely. A job whose worker
died is reclaimed once its lease expires. Results are upserted per dataset, so a retried
job overwrites rather than duplicates.
"""

import json
import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from esp import catalog
from esp.models import Aoi, Dataset, ScreeningJob, ScreeningResult
from esp.screening import SCREENERS

log = logging.getLogger(__name__)

LEASE_SECONDS = 600
RETRY_DELAY_SECONDS = 10


def submit(
    session: Session, name: str, geojson: dict[str, Any], idempotency_key: str | None = None
) -> ScreeningJob:
    """Create an AOI and a queued job pinned to the currently active dataset versions."""
    if idempotency_key:
        existing = session.scalar(
            select(ScreeningJob).where(ScreeningJob.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
    geom, area = session.execute(
        text(
            "SELECT ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)),"
            " ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)::geography)"
        ),
        {"g": json.dumps(geojson)},
    ).one()
    aoi = Aoi(name=name, geom=geom, area_m2=area)
    session.add(aoi)
    session.flush()
    job = ScreeningJob(
        aoi_id=aoi.id,
        dataset_versions=catalog.active_versions(session),
        idempotency_key=idempotency_key,
    )
    session.add(job)
    session.flush()
    log.info("screening submitted", extra={"job_id": str(job.id), "area_m2": round(area)})
    return job


def claim(session: Session, worker_id: str) -> uuid.UUID | None:
    job_id: uuid.UUID | None = session.execute(
        text(
            """
            UPDATE screening_jobs
            SET status = 'running', attempts = attempts + 1, locked_by = :worker,
                locked_at = now(), started_at = coalesce(started_at, now())
            WHERE id = (
                SELECT id FROM screening_jobs
                WHERE (status = 'queued' AND run_after <= now())
                   OR (status = 'running' AND locked_at < now() - make_interval(secs => :lease))
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1)
            RETURNING id
            """
        ),
        {"worker": worker_id, "lease": LEASE_SECONDS},
    ).scalar()
    session.commit()
    return job_id


def run(session: Session, job_id: uuid.UUID) -> None:
    """Compute every pinned dataset's result. One dataset failing does not fail the others."""
    job = session.get(ScreeningJob, job_id)
    assert job is not None
    if job.attempts > job.max_attempts:
        _fail(session, job, "exceeded max attempts (worker lost or crashed repeatedly)")
        return
    try:
        known = session.scalars(select(Dataset.id).where(Dataset.id.in_(SCREENERS))).all()
        for dataset_id in known:
            values: dict[str, Any] = {"job_id": job.id, "dataset_id": dataset_id}
            version_id = job.dataset_versions.get(dataset_id)
            if version_id is None:
                values |= {"status": "unavailable", "error": "no active version when submitted"}
                _upsert_result(session, values)
                continue
            screener = SCREENERS[dataset_id]
            try:
                with session.begin_nested():
                    status, metrics = screener(session, job.aoi_id, version_id)
                values |= {"version_id": version_id, "status": status, "metrics": metrics}
            except Exception as exc:
                log.exception("dataset screening failed", extra={"job_id": str(job.id)})
                values |= {"version_id": version_id, "status": "failed", "error": str(exc)}
            _upsert_result(session, values)
        job.status, job.error = "succeeded", None
        job.finished_at = func.now()
        session.commit()
        log.info("screening succeeded", extra={"job_id": str(job.id)})
    except Exception as exc:
        session.rollback()
        job = session.get(ScreeningJob, job_id)
        assert job is not None
        if job.attempts >= job.max_attempts:
            _fail(session, job, str(exc))
        else:
            job.status, job.error, job.locked_by = "queued", str(exc), None
            job.run_after = func.now() + timedelta(seconds=RETRY_DELAY_SECONDS * job.attempts)
            session.commit()
            log.warning("screening will retry", extra={"job_id": str(job.id), "error": str(exc)})


def _fail(session: Session, job: ScreeningJob, error: str) -> None:
    job.status, job.error = "failed", error
    job.finished_at = func.now()
    session.commit()
    log.error("screening failed", extra={"job_id": str(job.id), "error": error})


def _upsert_result(session: Session, values: dict[str, Any]) -> None:
    values.setdefault("version_id", None)
    values.setdefault("metrics", None)
    values.setdefault("error", None)
    stmt = insert(ScreeningResult).values(**values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["job_id", "dataset_id"],
            set_={
                "version_id": stmt.excluded.version_id,
                "status": stmt.excluded.status,
                "metrics": stmt.excluded.metrics,
                "error": stmt.excluded.error,
                "computed_at": text("now()"),
            },
        )
    )
