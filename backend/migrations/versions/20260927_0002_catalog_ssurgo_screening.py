"""Source catalog, SSURGO canonical tables, AOIs and screening jobs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def multipolygon() -> Geometry:
    return Geometry("MULTIPOLYGON", srid=4326, spatial_index=False)


def created_at(name: str = "created_at") -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("homepage", sa.Text(), nullable=False),
        sa.Column("active_version_id", sa.UUID(), nullable=True),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("dataset_id", sa.Text(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("provider_release", JSONB(), nullable=False),
        sa.Column("validation", JSONB(), nullable=True),
        sa.Column("stats", JSONB(), nullable=True),
        sa.Column("coverage", multipolygon(), nullable=True),
        created_at(),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('loading', 'failed', 'validated', 'active', 'superseded')",
            name="ck_dataset_versions_status",
        ),
    )
    op.create_foreign_key(None, "datasets", "dataset_versions", ["active_version_id"], ["id"])
    op.create_index(
        "uq_dataset_versions_content",
        "dataset_versions",
        ["dataset_id", "content_sha256"],
        unique=True,
        postgresql_where=sa.text("status <> 'failed'"),
    )
    op.create_index(
        "uq_dataset_versions_one_active",
        "dataset_versions",
        ["dataset_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "raw_snapshots",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("dataset_id", sa.Text(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("provider_release", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        created_at("retrieved_at"),
        sa.UniqueConstraint("dataset_id", "sha256"),
    )
    op.create_table(
        "dataset_version_snapshots",
        sa.Column(
            "version_id",
            sa.UUID(),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("snapshot_id", sa.UUID(), sa.ForeignKey("raw_snapshots.id"), primary_key=True),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("dataset_id", sa.Text(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version_id", sa.UUID(), sa.ForeignKey("dataset_versions.id"), nullable=True),
        created_at("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'unchanged', 'failed')",
            name="ck_ingestion_runs_status",
        ),
    )

    op.create_table(
        "ssurgo_mapunits",
        sa.Column(
            "version_id",
            sa.UUID(),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mukey", sa.Text(), primary_key=True),
        sa.Column("areasymbol", sa.Text(), nullable=False),
        sa.Column("musym", sa.Text(), nullable=False),
        sa.Column("muname", sa.Text(), nullable=False),
        sa.Column("hydric_pct", sa.SmallInteger(), nullable=True),
    )
    op.create_table(
        "ssurgo_polygons",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "version_id",
            sa.UUID(),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mukey", sa.Text(), nullable=False),
        sa.Column("areasymbol", sa.Text(), nullable=False),
        sa.Column("geom", multipolygon(), nullable=False),
        sa.Column("repaired", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("ix_ssurgo_polygons_version", "ssurgo_polygons", ["version_id"])
    op.create_index("ix_ssurgo_polygons_geom", "ssurgo_polygons", ["geom"], postgresql_using="gist")

    op.create_table(
        "aois",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("geom", multipolygon(), nullable=False),
        sa.Column("area_m2", sa.Double(), nullable=False),
        created_at(),
    )
    op.create_table(
        "screening_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("aoi_id", sa.UUID(), sa.ForeignKey("aois.id"), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("dataset_versions", JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        created_at("run_after"),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
        sa.Column("error", sa.Text(), nullable=True),
        created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_screening_jobs_status",
        ),
    )
    op.create_index(
        "ix_screening_jobs_claimable",
        "screening_jobs",
        ["run_after"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_table(
        "screening_results",
        sa.Column(
            "job_id",
            sa.UUID(),
            sa.ForeignKey("screening_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("dataset_id", sa.Text(), sa.ForeignKey("datasets.id"), primary_key=True),
        sa.Column("version_id", sa.UUID(), sa.ForeignKey("dataset_versions.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("metrics", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        created_at("computed_at"),
        sa.CheckConstraint(
            "status IN ('complete', 'partial_coverage', 'not_covered', 'unavailable', 'failed')",
            name="ck_screening_results_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("screening_results")
    op.drop_table("screening_jobs")
    op.drop_table("aois")
    op.drop_table("ssurgo_polygons")
    op.drop_table("ssurgo_mapunits")
    op.drop_table("ingestion_runs")
    op.drop_table("dataset_version_snapshots")
    op.drop_table("raw_snapshots")
    op.drop_constraint("datasets_active_version_id_fkey", "datasets", type_="foreignkey")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
