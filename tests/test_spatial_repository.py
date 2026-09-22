from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from shapely import wkt
from shapely.geometry import shape

from environmental_screening_platform.spatial import (
    ANALYSIS_CRS,
    EXPECTED_COUNTY_GEOIDS,
    MIGRATION_ID,
    SOURCE_CRS,
    AoiRevisionRecord,
    PostGISRepository,
    census_boundary_record,
)

FIXTURE = Path(__file__).parent / "fixtures" / "census_boundary_three_counties.geojson"


def test_migration_and_compose_boundary_are_pinned_and_credential_free() -> None:
    migration = Path(__file__).parents[1] / "migrations" / "001_aoi_revisions.sql"
    compose = Path(__file__).parents[1] / "docker-compose.yml"
    sql = migration.read_text()
    compose_text = compose.read_text()
    assert MIGRATION_ID in sql
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in sql
    assert "aoi_revision_components" in sql
    assert "source_snapshot_id" in sql and "source_version_id" in sql
    assert "postgis/postgis:16-3.4" in compose_text
    assert "POSTGIS_PASSWORD:?" in compose_text
    assert "POSTGIS_PASSWORD: change-me" not in compose_text
    assert "ESGP_POSTGIS_DATA_DIR:?" in compose_text


def test_census_boundary_record_preserves_three_components_and_linkage() -> None:
    record = census_boundary_record(
        FIXTURE,
        project_id="project-1",
        aoi_id="aoi-1",
        aoi_revision=1,
        source_snapshot_id="snapshot-1",
        source_version_id="census_boundary:fixture-version",
    )
    assert record.source_crs == SOURCE_CRS
    assert record.analysis_crs == ANALYSIS_CRS
    assert record.geometry_status == "valid"
    assert record.source_snapshot_id == "snapshot-1"
    assert record.source_version_id == "census_boundary:fixture-version"
    assert [component.source_feature_id for component in record.components] == list(
        EXPECTED_COUNTY_GEOIDS
    )
    union = shape(json.loads(FIXTURE.read_text())["features"][0]["geometry"])
    assert union.is_valid
    assert len(record.components) == 3
    assert shape(json.loads(FIXTURE.read_text())["features"][1]["geometry"]).is_valid
    assert record.analysis_area_sqm > 0
    assert wkt.loads(record.geometry_wkt).geom_type == "MultiPolygon"
    assert len(wkt.loads(record.geometry_wkt).geoms) == 3
    assert "EPSG:4269 to EPSG:4326" in record.provenance["normalization"]


def test_census_boundary_record_rejects_missing_or_extra_county(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["features"] = payload["features"][:2]
    damaged = tmp_path / "damaged-boundary-fixture.geojson"
    damaged.write_text(json.dumps(payload))
    try:
        with pytest.raises(ValueError, match="exactly the approved three county GEOIDs"):
            census_boundary_record(
                damaged,
                project_id="project-1",
                aoi_id="aoi-1",
                aoi_revision=1,
                source_snapshot_id="snapshot-1",
                source_version_id=None,
            )
    finally:
        damaged.unlink()


def test_postgis_client_requires_explicit_connection_configuration() -> None:
    with pytest.raises(ValueError, match="ESGP_POSTGIS_URL"):
        PostGISRepository()


POSTGIS_CLIENT_AVAILABLE = bool(os.environ.get("ESGP_POSTGIS_URL"))
try:
    import psycopg  # noqa: F401
except ImportError:
    POSTGIS_CLIENT_AVAILABLE = False


@pytest.mark.skipif(
    not POSTGIS_CLIENT_AVAILABLE,
    reason="PostGIS integration requires ESGP_POSTGIS_URL and psycopg",
)
def test_postgis_schema_fixture_and_rollback() -> None:
    from psycopg.errors import UniqueViolation

    repository = PostGISRepository()
    repository.migrate()
    record = census_boundary_record(
        FIXTURE,
        project_id="postgis-fixture-project",
        aoi_id="postgis-fixture-aoi",
        aoi_revision=1,
        source_snapshot_id="postgis-fixture-snapshot",
        source_version_id="census_boundary:fixture-version",
    )
    inserted = repository.insert_aoi_revision(record)
    assert inserted["source_snapshot_id"] == record.source_snapshot_id
    assert len(repository.get_aoi_revision(record.aoi_id, record.aoi_revision)["components"]) == 3
    validation = repository.validate_geometry(record.aoi_id, record.aoi_revision)
    assert validation["valid"] is True
    assert validation["srid"] == 4326
    assert validation["component_count"] == 3
    assert repository.get_geometry_for_snapshot(record.source_snapshot_id, record.source_version_id)
    assert repository.get_geometry_for_snapshot("missing-snapshot", "missing-version") is None
    assert repository.get_geometry_for_snapshot(record.source_snapshot_id, "wrong-version") is None
    assert repository.insert_aoi_revision(record)["aoi_id"] == record.aoi_id

    bad = AoiRevisionRecord(
        **{
            **record.__dict__,
            "aoi_id": "postgis-fixture-bad",
            "components": (record.components[0], record.components[0]),
        }
    )
    with pytest.raises(UniqueViolation):
        repository.insert_aoi_revision(bad)
    assert repository.get_aoi_revision("postgis-fixture-bad", 1) is None
