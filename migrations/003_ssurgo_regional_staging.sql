CREATE TABLE IF NOT EXISTS screening.ssurgo_regional_staging_batches (
    batch_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL CHECK (source_id = 'ssurgo'),
    package_areasymbol TEXT NOT NULL,
    package_name TEXT NOT NULL,
    provider_package_identifier TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    ingestion_run_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    provider_release TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ,
    artifact_path TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    artifact_size_bytes BIGINT NOT NULL CHECK (artifact_size_bytes >= 0),
    terms_url TEXT NOT NULL,
    source_crs TEXT NOT NULL,
    analysis_crs TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK
        (validation_status IN ('validated','conditionally_validated','failed','incomplete')),
    coverage_status TEXT NOT NULL CHECK
        (coverage_status IN ('intersects','unknown','unavailable')),
    staging_status TEXT NOT NULL CHECK
        (staging_status IN ('complete','quarantined','failed')),
    promotion_status TEXT NOT NULL CHECK (promotion_status = 'staging_only'),
    feature_count INTEGER NOT NULL CHECK (feature_count >= 0),
    map_unit_count INTEGER NOT NULL CHECK (map_unit_count >= 0),
    component_count INTEGER NOT NULL CHECK (component_count >= 0),
    original_invalid_count INTEGER NOT NULL CHECK (original_invalid_count >= 0),
    repaired_accepted_count INTEGER NOT NULL CHECK (repaired_accepted_count >= 0),
    quarantined_count INTEGER NOT NULL CHECK (quarantined_count >= 0),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_snapshot_id, source_version_id)
);

CREATE INDEX IF NOT EXISTS idx_ssurgo_regional_batches_source_version
    ON screening.ssurgo_regional_staging_batches (source_version_id, staging_status);

CREATE TABLE IF NOT EXISTS screening.ssurgo_regional_map_units_staging (
    batch_id TEXT NOT NULL REFERENCES screening.ssurgo_regional_staging_batches(batch_id)
        ON DELETE RESTRICT,
    mukey TEXT NOT NULL,
    musym TEXT NOT NULL,
    muname TEXT NOT NULL,
    areasymbol TEXT NOT NULL,
    areaname TEXT NOT NULL,
    source_attributes JSONB NOT NULL,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (batch_id, mukey)
);

CREATE TABLE IF NOT EXISTS screening.ssurgo_regional_components_staging (
    batch_id TEXT NOT NULL,
    mukey TEXT NOT NULL,
    cokey TEXT NOT NULL,
    comppct_r NUMERIC(5, 2),
    hydricrating TEXT NOT NULL,
    hydricon TEXT NOT NULL,
    source_attributes JSONB NOT NULL,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (batch_id, mukey, cokey),
    FOREIGN KEY (batch_id, mukey)
        REFERENCES screening.ssurgo_regional_map_units_staging (batch_id, mukey)
        ON DELETE RESTRICT,
    CHECK (comppct_r IS NULL OR (comppct_r >= 0 AND comppct_r <= 100))
);

CREATE INDEX IF NOT EXISTS idx_ssurgo_regional_components_staging_join
    ON screening.ssurgo_regional_components_staging (batch_id, mukey);

CREATE TABLE IF NOT EXISTS screening.ssurgo_regional_features_staging (
    batch_id TEXT NOT NULL,
    stable_feature_id TEXT NOT NULL,
    source_record_index INTEGER NOT NULL CHECK (source_record_index >= 0),
    mukey TEXT NOT NULL,
    source_geometry geometry(Geometry, 4326) NOT NULL,
    derived_geometry geometry(Geometry, 4326) NOT NULL,
    original_valid BOOLEAN NOT NULL,
    original_validity_reason TEXT NOT NULL,
    original_geometry_type TEXT NOT NULL,
    original_component_count INTEGER NOT NULL CHECK (original_component_count >= 0),
    original_ring_count INTEGER NOT NULL CHECK (original_ring_count >= 0),
    original_empty BOOLEAN NOT NULL,
    original_area_epsg5070_m2 DOUBLE PRECISION NOT NULL CHECK (original_area_epsg5070_m2 >= 0),
    derived_valid BOOLEAN NOT NULL,
    derived_geometry_type TEXT NOT NULL,
    derived_component_count INTEGER NOT NULL CHECK (derived_component_count >= 0),
    derived_ring_count INTEGER NOT NULL CHECK (derived_ring_count >= 0),
    derived_empty BOOLEAN NOT NULL,
    derived_area_epsg5070_m2 DOUBLE PRECISION NOT NULL CHECK (derived_area_epsg5070_m2 >= 0),
    area_delta_percentage DOUBLE PRECISION,
    repair_operation TEXT,
    geometry_status TEXT NOT NULL CHECK
        (geometry_status IN ('unchanged_valid','repaired_accepted','quarantined')),
    attributes_joinable BOOLEAN NOT NULL,
    source_attributes JSONB NOT NULL,
    audited_diagnostic JSONB,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (batch_id, stable_feature_id),
    FOREIGN KEY (batch_id, mukey)
        REFERENCES screening.ssurgo_regional_map_units_staging (batch_id, mukey)
        ON DELETE RESTRICT,
    CHECK (ST_SRID(source_geometry) = 4326),
    CHECK (ST_SRID(derived_geometry) = 4326),
    CHECK (geometry_status <> 'repaired_accepted' OR
        (derived_valid AND NOT derived_empty AND
         derived_geometry_type IN ('Polygon','MultiPolygon') AND
         derived_component_count = original_component_count AND
         area_delta_percentage IS NOT NULL AND abs(area_delta_percentage) <= 0.1 AND
         attributes_joinable)),
    CHECK (geometry_status <> 'unchanged_valid' OR
        (original_valid AND derived_valid AND NOT derived_empty AND
         original_geometry_type IN ('Polygon','MultiPolygon') AND
         derived_geometry_type = original_geometry_type)),
    CHECK (geometry_status <> 'quarantined' OR NOT attributes_joinable OR
        (derived_valid AND NOT derived_empty AND
         derived_geometry_type IN ('Polygon','MultiPolygon')))
);

CREATE INDEX IF NOT EXISTS idx_ssurgo_regional_features_staging_geometry
    ON screening.ssurgo_regional_features_staging USING GIST (derived_geometry);
CREATE INDEX IF NOT EXISTS idx_ssurgo_regional_features_staging_join
    ON screening.ssurgo_regional_features_staging (batch_id, mukey);

INSERT INTO screening.schema_migrations (migration_id)
VALUES ('003_ssurgo_regional_staging')
ON CONFLICT (migration_id) DO NOTHING;
