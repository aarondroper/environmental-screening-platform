CREATE SCHEMA IF NOT EXISTS screening;
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS screening.schema_migrations (
    migration_id TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS screening.aoi_revisions (
    aoi_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    aoi_revision INTEGER NOT NULL CHECK (aoi_revision > 0),
    source_snapshot_id TEXT NOT NULL,
    source_version_id TEXT,
    geometry geometry(MultiPolygon, 4326) NOT NULL,
    source_crs TEXT NOT NULL,
    analysis_crs TEXT NOT NULL,
    geometry_status TEXT NOT NULL CHECK (geometry_status IN ('valid', 'invalid', 'quarantined')),
    analysis_area_sqm DOUBLE PRECISION,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (aoi_id, aoi_revision),
    UNIQUE (project_id, aoi_id, aoi_revision),
    CHECK (ST_SRID(geometry) = 4326),
    CHECK (geometry_status <> 'valid' OR (NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry)))
);

CREATE INDEX IF NOT EXISTS idx_aoi_revisions_geometry
    ON screening.aoi_revisions USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_aoi_revisions_snapshot
    ON screening.aoi_revisions (source_snapshot_id, source_version_id);

CREATE TABLE IF NOT EXISTS screening.aoi_revision_components (
    aoi_id TEXT NOT NULL,
    aoi_revision INTEGER NOT NULL,
    component_index INTEGER NOT NULL CHECK (component_index >= 0),
    source_feature_id TEXT NOT NULL,
    source_name TEXT,
    source_geometry geometry(MultiPolygon, 4269) NOT NULL,
    geometry geometry(MultiPolygon, 4326) NOT NULL,
    source_crs TEXT NOT NULL,
    geometry_status TEXT NOT NULL CHECK (geometry_status IN ('valid', 'invalid', 'quarantined')),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (aoi_id, aoi_revision, component_index),
    UNIQUE (aoi_id, aoi_revision, source_feature_id),
    FOREIGN KEY (aoi_id, aoi_revision)
        REFERENCES screening.aoi_revisions (aoi_id, aoi_revision)
        ON DELETE RESTRICT,
    CHECK (ST_SRID(source_geometry) = 4269),
    CHECK (ST_SRID(geometry) = 4326),
    CHECK (geometry_status <> 'valid' OR (NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry)))
);

CREATE INDEX IF NOT EXISTS idx_aoi_components_geometry
    ON screening.aoi_revision_components USING GIST (geometry);

INSERT INTO screening.schema_migrations (migration_id)
VALUES ('001_aoi_revisions')
ON CONFLICT (migration_id) DO NOTHING;
