from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from environmental_screening_platform.spatial import PostGISRepository
from environmental_screening_platform.ssurgo import (
    SsurgoBatchRecord,
    SsurgoComponentRecord,
    SsurgoMapUnitRecord,
    parse_ssurgo_fixture,
)

SSURGO_VERSION = "ssurgo:test-version-1"


def _batch(
    tmp_path: Path,
    *,
    batch_id: str,
    snapshot_id: str,
    version_id: str,
    invalid_geometry: bool = False,
) -> SsurgoBatchRecord:
    geometry = (
        "MULTIPOLYGON (((-105 40,-104 41,-105 41,-104 40,-105 40)))"
        if invalid_geometry
        else "MULTIPOLYGON (((-105 40,-104 40,-104 41,-105 41,-105 40)))"
    )
    component = SsurgoComponentRecord(
        mukey="497588",
        cokey="26856137",
        comppct_r=20,
        hydricrating="No",
        hydricon=None,
        provenance={"fixture": True},
    )
    map_unit = SsurgoMapUnitRecord(
        mukey="497588",
        musym="NdD",
        muname="Nederland very cobbly sandy loam",
        geometry_wkt=geometry,
        source_geometry_piece_count=1,
        analysis_area_sqm=1_000_000,
        components=(component,),
        geometry_status="invalid" if invalid_geometry else "valid",
        provenance={"fixture": True},
    )
    artifact = tmp_path / f"{batch_id}.json"
    artifact.write_text("{}", encoding="utf-8")
    return SsurgoBatchRecord(
        batch_id=batch_id,
        source_snapshot_id=snapshot_id,
        source_version_id=version_id,
        artifact_path=str(artifact),
        artifact_sha256=hashlib.sha256(b"{}").hexdigest(),
        artifact_size_bytes=2,
        source_url="https://example.test/ssurgo",
        provider_release="test fixture",
        retrieved_at="2026-09-23T00:00:00+00:00",
        terms_url="https://example.test/terms",
        map_units=(map_unit,),
        ingestion_run_id="ssurgo-test-run",
        candidate_id="ssurgo-test-candidate",
        provenance={"fixture": True},
    )


def test_parse_ssurgo_fixture_preserves_component_attributes_and_lineage(tmp_path: Path) -> None:
    payload = {
        "Table": [
            [
                "mukey",
                "musym",
                "muname",
                "cokey",
                "comppct_r",
                "hydricrating",
                "hydricon",
                "polygon_wkt",
            ],
            [
                "497588",
                "NdD",
                "Nederland",
                "26856137",
                "20",
                "No",
                None,
                "POLYGON ((-105 40,-104 40,-104 41,-105 41,-105 40))",
            ],
            [
                "497588",
                "NdD",
                "Nederland",
                "26856138",
                "80",
                "Yes",
                "Farmable under natural conditions",
                "POLYGON ((-105 40,-104 40,-104 41,-105 41,-105 40))",
            ],
        ]
    }
    artifact = tmp_path / "ssurgo.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata = tmp_path / "ssurgo.json.metadata.json"
    metadata.write_text(
        json.dumps(
            {"sha256": digest, "size_bytes": artifact.stat().st_size, "version_id": SSURGO_VERSION}
        ),
        encoding="utf-8",
    )
    batch = parse_ssurgo_fixture(
        artifact,
        batch_id="parser-batch",
        source_snapshot_id="parser-snapshot",
        source_version_id=SSURGO_VERSION,
        metadata_path=metadata,
    )
    assert len(batch.map_units) == 1
    assert batch.map_units[0].source_geometry_piece_count == 1
    assert [component.cokey for component in batch.map_units[0].components] == [
        "26856137",
        "26856138",
    ]
    assert batch.map_units[0].components[1].hydricon == "Farmable under natural conditions"
    assert batch.provenance["hydric_interpretation"].startswith("component-level soil")


POSTGIS_AVAILABLE = bool(os.environ.get("ESGP_POSTGIS_URL"))
try:
    import psycopg  # noqa: F401
except ImportError:
    POSTGIS_AVAILABLE = False


@pytest.mark.skipif(
    not POSTGIS_AVAILABLE,
    reason="SSURGO PostGIS integration requires ESGP_POSTGIS_URL and psycopg",
)
def test_ssurgo_staging_validation_fixture_promotion_and_idempotence(tmp_path: Path) -> None:
    repository = PostGISRepository()
    repository.migrate()
    suffix = f"{tmp_path.name}-{uuid4().hex[:8]}"
    batch = _batch(
        tmp_path,
        batch_id=f"ssurgo-test-batch-v1-{suffix}",
        snapshot_id=f"ssurgo-test-snapshot-v1-{suffix}",
        version_id=f"{SSURGO_VERSION}-{suffix}",
    )
    staged = repository.stage_ssurgo_batch(batch)
    assert staged["promotion_status"] == "staged"
    assert staged["ingestion_run_id"] == "ssurgo-test-run"
    assert staged["candidate_id"] == "ssurgo-test-candidate"
    validated = repository.validate_ssurgo_batch(batch.batch_id)
    assert validated["validation_status"] == "validated"
    assert validated["staging_map_unit_count"] == 1
    assert validated["staging_component_count"] == 1
    promoted = repository.promote_ssurgo_batch(batch.batch_id)
    assert promoted["promotion_status"] == "fixture_only"
    rows = repository.get_ssurgo_map_units(batch.source_snapshot_id, batch.source_version_id)
    assert rows["map_unit_count"] == 1
    assert rows["component_count"] == 1
    assert rows["map_units"][0]["mukey"] == "497588"
    assert rows["map_units"][0]["source_crs"] == "EPSG:4326"
    assert rows["map_units"][0]["canonical_crs"] == "EPSG:4326"
    assert rows["map_units"][0]["analysis_crs"] == "EPSG:5070"
    assert rows["map_units"][0]["components"][0]["cokey"] == "26856137"
    assert rows["map_units"][0]["components"][0]["hydricrating"] == "No"

    assert repository.stage_ssurgo_batch(batch)["batch_id"] == batch.batch_id
    with pytest.raises(ValueError, match="checksum or size"):
        repository.stage_ssurgo_batch(replace(batch, artifact_sha256="0" * 64))
    assert repository.promote_ssurgo_batch(batch.batch_id)["idempotent"] is True
    repeated = repository.get_ssurgo_map_units(batch.source_snapshot_id, batch.source_version_id)
    assert repeated["map_unit_count"] == 1
    assert repeated["component_count"] == 1

    next_batch = _batch(
        tmp_path,
        batch_id=f"ssurgo-test-batch-v2-{suffix}",
        snapshot_id=f"ssurgo-test-snapshot-v2-{suffix}",
        version_id=f"ssurgo:test-version-2-{suffix}",
    )
    repository.stage_ssurgo_batch(next_batch)
    assert repository.validate_ssurgo_batch(next_batch.batch_id)["validation_status"] == "validated"
    repository.promote_ssurgo_batch(next_batch.batch_id)
    assert (
        repository.get_ssurgo_map_units(batch.source_snapshot_id, batch.source_version_id)[
            "map_unit_count"
        ]
        == 1
    )
    assert (
        repository.get_ssurgo_map_units(
            next_batch.source_snapshot_id, next_batch.source_version_id
        )["map_unit_count"]
        == 1
    )


@pytest.mark.skipif(
    not POSTGIS_AVAILABLE,
    reason="SSURGO PostGIS integration requires ESGP_POSTGIS_URL and psycopg",
)
def test_ssurgo_failed_validation_is_retained_and_not_promoted(tmp_path: Path) -> None:
    repository = PostGISRepository()
    repository.migrate()
    suffix = f"{tmp_path.name}-{uuid4().hex[:8]}"
    batch = _batch(
        tmp_path,
        batch_id=f"ssurgo-test-invalid-batch-{suffix}",
        snapshot_id=f"ssurgo-test-invalid-snapshot-{suffix}",
        version_id=f"ssurgo:test-invalid-version-{suffix}",
        invalid_geometry=True,
    )
    repository.stage_ssurgo_batch(batch)
    result = repository.validate_ssurgo_batch(batch.batch_id)
    assert result["validation_status"] == "failed"
    assert result["promotion_status"] == "failed"
    assert result["staging_map_unit_count"] == 1
    assert (
        repository.get_ssurgo_map_units(batch.source_snapshot_id, batch.source_version_id)[
            "map_unit_count"
        ]
        == 0
    )
    with pytest.raises(ValueError, match="successfully validated"):
        repository.promote_ssurgo_batch(batch.batch_id)
