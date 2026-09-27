"""Database schema. Migrations in `migrations/versions` must match this (see test_migrations)."""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from esp.db import Base

MultiPolygon4326 = Geometry("MULTIPOLYGON", srid=4326, spatial_index=False)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Source catalog -------------------------------------------------------------------


class Dataset(Base):
    """One external source (e.g. 'ssurgo'). `active_version_id` is what screenings use."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    homepage: Mapped[str] = mapped_column(Text)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_versions.id", use_alter=True)
    )


VERSION_STATUSES = ("loading", "failed", "validated", "active", "superseded")


class DatasetVersion(Base):
    """An immutable, checksum-identified load of a dataset.

    Canonical rows carry `version_id`; a version is invisible to screenings until promoted.
    """

    __tablename__ = "dataset_versions"
    __table_args__ = (
        CheckConstraint(f"status IN {VERSION_STATUSES}", name="ck_dataset_versions_status"),
        # Same raw content is never loaded twice (unless the earlier attempt failed).
        Index(
            "uq_dataset_versions_content",
            "dataset_id",
            "content_sha256",
            unique=True,
            postgresql_where=text("status <> 'failed'"),
        ),
        Index(
            "uq_dataset_versions_one_active",
            "dataset_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    status: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(Text)
    provider_release: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    coverage: Mapped[Any] = mapped_column(MultiPolygon4326, nullable=True)
    created_at: Mapped[datetime] = _now()
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawSnapshot(Base):
    """An immutable raw download, stored content-addressed under the raw data directory."""

    __tablename__ = "raw_snapshots"
    __table_args__ = (UniqueConstraint("dataset_id", "sha256"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    url: Mapped[str] = mapped_column(Text)
    provider_release: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = _now()


class DatasetVersionSnapshot(Base):
    __tablename__ = "dataset_version_snapshots"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_snapshots.id"), primary_key=True)


RUN_STATUSES = ("running", "succeeded", "unchanged", "failed")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="ck_ingestion_runs_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    status: Mapped[str] = mapped_column(Text, default="running")
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# --- Canonical source tables ----------------------------------------------------------


class SsurgoMapunit(Base):
    __tablename__ = "ssurgo_mapunits"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), primary_key=True
    )
    mukey: Mapped[str] = mapped_column(Text, primary_key=True)
    areasymbol: Mapped[str] = mapped_column(Text)
    musym: Mapped[str] = mapped_column(Text)
    muname: Mapped[str] = mapped_column(Text)
    # muaggatt.hydclprs: percent of the map unit made up of hydric components (NRCS).
    hydric_pct: Mapped[int | None] = mapped_column(SmallInteger)


class SsurgoPolygon(Base):
    __tablename__ = "ssurgo_polygons"
    __table_args__ = (
        Index("ix_ssurgo_polygons_version", "version_id"),
        Index("ix_ssurgo_polygons_geom", "geom", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE")
    )
    mukey: Mapped[str] = mapped_column(Text)
    areasymbol: Mapped[str] = mapped_column(Text)
    geom: Mapped[Any] = mapped_column(MultiPolygon4326)
    # True when the source geometry was invalid and repaired with ST_MakeValid.
    repaired: Mapped[bool] = mapped_column(server_default=text("false"))


# --- Screening ------------------------------------------------------------------------


class Aoi(Base):
    __tablename__ = "aois"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text)
    geom: Mapped[Any] = mapped_column(MultiPolygon4326)
    area_m2: Mapped[float]
    created_at: Mapped[datetime] = _now()


JOB_STATUSES = ("queued", "running", "succeeded", "failed")


class ScreeningJob(Base):
    __tablename__ = "screening_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {JOB_STATUSES}", name="ck_screening_jobs_status"),
        Index(
            "ix_screening_jobs_claimable", "run_after", postgresql_where=text("status = 'queued'")
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    aoi_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("aois.id"))
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    # {dataset_id: version_id} pinned at submission, so retries use the same data.
    dataset_versions: Mapped[dict[str, str]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    run_after: Mapped[datetime] = _now()
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


RESULT_STATUSES = ("complete", "partial_coverage", "not_covered", "unavailable", "failed")


class ScreeningResult(Base):
    __tablename__ = "screening_results"
    __table_args__ = (
        CheckConstraint(f"status IN {RESULT_STATUSES}", name="ck_screening_results_status"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screening_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), primary_key=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    status: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = _now()
