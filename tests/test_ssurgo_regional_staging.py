from __future__ import annotations

import os
from pathlib import Path

import pytest
from shapely.geometry import box
from test_ssurgo_regional import _package_zip, _spec

from environmental_screening_platform.spatial import PostGISRepository
from environmental_screening_platform.ssurgo_packages import SsurgoPackageSpec
from environmental_screening_platform.ssurgo_regional import audit_ssurgo_package_discrepancies
from environmental_screening_platform.ssurgo_regional_staging import (
    RegionalComponentStagingRecord,
    RegionalFeatureStagingRecord,
    RegionalMapUnitStagingRecord,
    RegionalPackageStagingRecord,
    parse_regional_package_for_staging,
)


def _candidate(spec: SsurgoPackageSpec, *, version_id: str = "v" * 64) -> dict[str, str]:
    package = spec
    return {
        "source_id": "ssurgo",
        "version_id": version_id,
        "run_id": "run-fixture",
        "candidate_id": "candidate-fixture",
        "source_url": package.package_url,
        "provider_release": package.provider_release,
        "retrieved_at": "2026-09-24T00:00:00+00:00",
        "terms_url": "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
    }


def _package_record(
    *, batch_id: str, status: str = "unchanged_valid"
) -> RegionalPackageStagingRecord:
    component = RegionalComponentStagingRecord(
        mukey="100",
        cokey="200",
        comppct_r=50.0,
        hydricrating="No",
        hydricon="",
        source_attributes={"cokey": "200", "hydricrating": "No"},
    )
    map_unit = RegionalMapUnitStagingRecord(
        mukey="100",
        musym="M1",
        muname="Example",
        areasymbol="CO001",
        areaname="Example survey area",
        source_attributes={"mukey": "100", "musym": "M1", "muname": "Example"},
        components=(component,),
    )
    feature = RegionalFeatureStagingRecord(
        stable_feature_id=f"soilmu_a:CO001:0:100:{batch_id}",
        source_record_index=0,
        mukey="100",
        source_geometry_wkt=box(0, 0, 1, 1).wkt,
        derived_geometry_wkt=box(0, 0, 1, 1).wkt,
        original_valid=True,
        original_validity_reason="Valid Geometry",
        original_geometry_type="Polygon",
        original_component_count=1,
        original_ring_count=1,
        original_empty=False,
        original_area_epsg5070_m2=1.0,
        derived_valid=True,
        derived_geometry_type="Polygon",
        derived_component_count=1,
        derived_ring_count=1,
        derived_empty=False,
        derived_area_epsg5070_m2=1.0,
        area_delta_percentage=0.0,
        repair_operation=None,
        geometry_status=status,
        attributes_joinable=status != "quarantined",
        source_attributes={"AREASYMBOL": "CO001", "MUKEY": "100"},
        audited_diagnostic=None,
    )
    return RegionalPackageStagingRecord(
        batch_id=batch_id,
        areasymbol="CO001",
        areaname="Example survey area",
        provider_package_identifier="CO001.zip",
        source_snapshot_id=f"ssurgo-package:CO001:{batch_id}",
        source_version_id=f"version:{batch_id}",
        ingestion_run_id=f"run:{batch_id}",
        candidate_id=f"candidate:{batch_id}",
        source_url="https://websoilsurvey.sc.egov.usda.gov/CO001.zip",
        provider_release="SSURGO CO001 fixture",
        retrieved_at="2026-09-24T00:00:00+00:00",
        terms_url="https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
        artifact_path="/external/ssurgo/CO001.zip",
        artifact_sha256="a" * 64,
        artifact_size_bytes=1,
        source_crs="EPSG:4326",
        canonical_crs="EPSG:4326",
        analysis_crs="EPSG:5070",
        map_units=(map_unit,),
        features=(feature,),
        coverage_status="intersects",
        validation_status="validated" if status != "quarantined" else "conditionally_validated",
        staging_status="complete" if status != "quarantined" else "quarantined",
        quarantine_count=1 if status == "quarantined" else 0,
        provenance={"fixture": True, "raw_unchanged": True},
    )


def test_regional_parser_preserves_audited_repair_and_quarantines_failed_candidate(
    tmp_path: Path,
) -> None:
    archive = _package_zip(tmp_path, invalid=True)
    spec = _spec()
    audit = audit_ssurgo_package_discrepancies(archive, spec)["geometry_diagnostics"]

    package = parse_regional_package_for_staging(
        archive,
        spec,
        candidate=_candidate(spec),
        audited_diagnostics=audit,
    )

    feature = package.features[0]
    assert package.staging_status == "quarantined"
    assert feature.geometry_status == "quarantined"
    assert feature.audited_diagnostic == audit[0]
    assert feature.source_geometry_wkt != feature.derived_geometry_wkt
    assert feature.attributes_joinable is True
    assert feature.original_valid is False


def test_regional_staging_migration_retains_repair_and_lineage_contract() -> None:
    migration = Path(__file__).parents[1] / "migrations" / "003_ssurgo_regional_staging.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "ssurgo_regional_staging_batches" in sql
    assert "ssurgo_regional_features_staging" in sql
    assert "source_snapshot_id" in sql and "source_version_id" in sql
    assert "candidate_id" in sql and "ingestion_run_id" in sql
    assert "source_geometry" in sql and "derived_geometry" in sql
    assert "area_delta_percentage" in sql
    assert "staging_only" in sql
    assert "abs(area_delta_percentage) <= 0.1" in sql


POSTGIS_AVAILABLE = bool(os.environ.get("ESGP_POSTGIS_URL"))
try:
    import psycopg  # noqa: F401
except ImportError:
    POSTGIS_AVAILABLE = False


@pytest.mark.skipif(
    not POSTGIS_AVAILABLE,
    reason="Regional SSURGO staging integration requires ESGP_POSTGIS_URL and psycopg",
)
def test_regional_staging_lineage_quarantine_idempotence_and_rollback() -> None:
    repository = PostGISRepository()
    repository.migrate()

    package = _package_record(batch_id="regional-staging-test-valid")
    inserted = repository.stage_ssurgo_regional_package(package)
    assert inserted["source_snapshot_id"] == package.source_snapshot_id
    assert inserted["source_version_id"] == package.source_version_id
    assert inserted["staging_status"] == "complete"
    assert inserted["feature_count"] == 1
    assert inserted["map_unit_count"] == 1
    assert inserted["component_count"] == 1
    assert repository.stage_ssurgo_regional_package(package)["idempotent"] is True

    quarantined = _package_record(batch_id="regional-staging-test-quarantine", status="quarantined")
    quarantined_result = repository.stage_ssurgo_regional_package(quarantined)
    assert quarantined_result["quarantined_feature_count"] == 1

    broken = _package_record(batch_id="regional-staging-test-rollback")
    broken = RegionalPackageStagingRecord(
        **{**broken.__dict__, "map_units": (broken.map_units[0], broken.map_units[0])}
    )
    from psycopg.errors import UniqueViolation

    with pytest.raises(UniqueViolation):
        repository.stage_ssurgo_regional_package(broken)
    assert repository.get_ssurgo_regional_staging_batch(broken.batch_id) is None
