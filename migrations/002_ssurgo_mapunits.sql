CREATE TABLE IF NOT EXISTS screening.ssurgo_ingestion_batches (
    batch_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL CHECK (source_id = 'ssurgo'),
    source_snapshot_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    ingestion_run_id TEXT,
    candidate_id TEXT,
    source_url TEXT NOT NULL,
    provider_release TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ,
    terms_url TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    artifact_size_bytes BIGINT NOT NULL CHECK (artifact_size_bytes >= 0),
    source_crs TEXT NOT NULL,
    canonical_crs TEXT NOT NULL,
    analysis_crs TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK (validation_status IN
        ('validated','conditionally_validated','failed','incomplete','blocked','not_acquired')),
    coverage_status TEXT NOT NULL CHECK (coverage_status IN
        ('complete','partial','unknown','unavailable','not_assessed')),
    observation_status TEXT NOT NULL CHECK (observation_status IN
        ('data_observed','incomplete_source','unavailable','not_assessed')),
    promotion_status TEXT NOT NULL CHECK (promotion_status IN
        ('staged','validated','fixture_only','failed','rejected')),
    validation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    validated_at TIMESTAMPTZ,
    promoted_at TIMESTAMPTZ,
    UNIQUE (source_snapshot_id, source_version_id)
);

CREATE INDEX IF NOT EXISTS idx_ssurgo_batches_source_version
    ON screening.ssurgo_ingestion_batches (source_id, source_version_id, promotion_status);

CREATE TABLE IF NOT EXISTS screening.ssurgo_map_units_staging (
    batch_id TEXT NOT NULL REFERENCES screening.ssurgo_ingestion_batches(batch_id)
        ON DELETE RESTRICT,
    mukey TEXT NOT NULL,
    areasymbol TEXT,
    areaname TEXT,
    musym TEXT NOT NULL,
    muname TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    source_crs TEXT NOT NULL,
    canonical_crs TEXT NOT NULL,
    analysis_crs TEXT NOT NULL,
    source_geometry geometry(MultiPolygon, 4326) NOT NULL,
    geometry geometry(MultiPolygon, 4326) NOT NULL,
    geometry_status TEXT NOT NULL CHECK (geometry_status IN ('valid','invalid','quarantined')),
    analysis_area_sqm DOUBLE PRECISION,
    source_geometry_piece_count INTEGER NOT NULL CHECK (source_geometry_piece_count > 0),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (batch_id, mukey),
    CHECK (ST_SRID(source_geometry) = 4326),
    CHECK (ST_SRID(geometry) = 4326),
    CHECK (geometry_status <> 'valid' OR (NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry)))
);

CREATE INDEX IF NOT EXISTS idx_ssurgo_map_units_staging_geometry
    ON screening.ssurgo_map_units_staging USING GIST (geometry);

CREATE TABLE IF NOT EXISTS screening.ssurgo_components_staging (
    batch_id TEXT NOT NULL,
    mukey TEXT NOT NULL,
    cokey TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    comppct_r NUMERIC(5, 2),
    hydricrating TEXT,
    hydricon TEXT,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (batch_id, mukey, cokey),
    FOREIGN KEY (batch_id, mukey)
        REFERENCES screening.ssurgo_map_units_staging (batch_id, mukey)
        ON DELETE RESTRICT,
    CHECK (comppct_r IS NULL OR (comppct_r >= 0 AND comppct_r <= 100))
);

CREATE TABLE IF NOT EXISTS screening.ssurgo_map_units (
    source_snapshot_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES screening.ssurgo_ingestion_batches(batch_id)
        ON DELETE RESTRICT,
    mukey TEXT NOT NULL,
    areasymbol TEXT,
    areaname TEXT,
    musym TEXT NOT NULL,
    muname TEXT NOT NULL,
    source_crs TEXT NOT NULL,
    canonical_crs TEXT NOT NULL,
    analysis_crs TEXT NOT NULL,
    source_geometry geometry(MultiPolygon, 4326) NOT NULL,
    geometry geometry(MultiPolygon, 4326) NOT NULL,
    geometry_status TEXT NOT NULL CHECK (geometry_status IN ('valid','invalid','quarantined')),
    analysis_area_sqm DOUBLE PRECISION,
    source_geometry_piece_count INTEGER NOT NULL CHECK (source_geometry_piece_count > 0),
    promotion_status TEXT NOT NULL CHECK (promotion_status = 'fixture_only'),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (source_snapshot_id, source_version_id, mukey),
    CHECK (ST_SRID(source_geometry) = 4326),
    CHECK (ST_SRID(geometry) = 4326),
    CHECK (geometry_status <> 'valid' OR (NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry)))
);

CREATE INDEX IF NOT EXISTS idx_ssurgo_map_units_geometry
    ON screening.ssurgo_map_units USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_ssurgo_map_units_version
    ON screening.ssurgo_map_units (source_version_id, mukey);

CREATE TABLE IF NOT EXISTS screening.ssurgo_components (
    source_snapshot_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES screening.ssurgo_ingestion_batches(batch_id)
        ON DELETE RESTRICT,
    mukey TEXT NOT NULL,
    cokey TEXT NOT NULL,
    comppct_r NUMERIC(5, 2),
    hydricrating TEXT,
    hydricon TEXT,
    promotion_status TEXT NOT NULL CHECK (promotion_status = 'fixture_only'),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (source_snapshot_id, source_version_id, mukey, cokey),
    FOREIGN KEY (source_snapshot_id, source_version_id, mukey)
        REFERENCES screening.ssurgo_map_units
            (source_snapshot_id, source_version_id, mukey)
        ON DELETE RESTRICT,
    CHECK (comppct_r IS NULL OR (comppct_r >= 0 AND comppct_r <= 100))
);

CREATE INDEX IF NOT EXISTS idx_ssurgo_components_version
    ON screening.ssurgo_components (source_version_id, mukey, cokey);

INSERT INTO screening.schema_migrations (migration_id)
VALUES ('002_ssurgo_mapunits')
ON CONFLICT (migration_id) DO NOTHING;
