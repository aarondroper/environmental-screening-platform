from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from shapely.geometry import Polygon, mapping

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.models import Acquisition
from environmental_screening_platform.spatial import PostGISRepository, PostGISUnavailable
from environmental_screening_platform.ssurgo import (
    SsurgoBatchRecord,
    SsurgoComponentRecord,
    SsurgoMapUnitRecord,
)
from environmental_screening_platform.workflow import (
    create_job,
    create_project,
    export_result,
    revise_aoi,
    run_job,
)

POSTGIS_AVAILABLE = bool(os.environ.get("ESGP_POSTGIS_URL"))
try:
    import psycopg  # noqa: F401
except ImportError:
    POSTGIS_AVAILABLE = False


def _project(root: Path, tmp_path: Path, aoi_geometry: Polygon) -> tuple[str, dict[str, object]]:
    boundary_path = root / "workspace" / "reference" / "approved_counties.geojson"
    boundary_path.parent.mkdir(parents=True, exist_ok=True)
    boundary_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(
                            Polygon([(-106, 39), (-103, 39), (-103, 42), (-106, 42), (-106, 39)])
                        ),
                        "properties": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    aoi_path = tmp_path / f"aoi-{uuid4().hex}.geojson"
    aoi_path.write_text(json.dumps(mapping(aoi_geometry)), encoding="utf-8")
    created = create_project("SSURGO fixture screening", aoi_path, root)
    return str(created["project"]["project_id"]), created["aoi_revision"]


def _promote_source(
    root: Path,
    project_id: str,
    aoi: dict[str, object],
    release: str,
) -> dict[str, object]:
    body = f"ssurgo-fixture-{release}".encode()
    artifact = root / "raw" / "ssurgo" / f"{release}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    acquisition = Acquisition(
        source_id="ssurgo",
        provider="USDA NRCS Soil Data Access",
        release=release,
        source_url="https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
        acquired_at="2026-09-24T10:00:00+00:00",
        media_type="application/json",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
    )
    repository = SQLiteSourceRepository(root)
    run = repository.begin_run(
        source_id="ssurgo",
        requested_url=acquisition.source_url,
        adapter_version="fixture-screening-test-1",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )
    repository.record_attempt(
        run["run_id"],
        status="acquired",
        requested_url=acquisition.source_url,
        actual_url=acquisition.source_url,
        retrieved_at=acquisition.acquired_at,
        sha256=digest,
        byte_size=len(body),
    )
    candidate = repository.record_candidate(
        run["run_id"],
        acquisition=acquisition,
        adapter_version="fixture-screening-test-1",
        status="validated",
        validation_status="validated",
        coverage_status="complete",
        observation_status="data_observed",
        validation={
            "validation_scope": "deterministic SSURGO screening fixture",
            "product_status": "fixture_only",
            "metrics": {},
            "warnings": [],
        },
    )
    repository.promote(candidate["candidate_id"])
    return candidate


def _load_batch(
    repository: PostGISRepository,
    root: Path,
    job: dict[str, object],
    candidate: dict[str, object],
    *,
    hydricrating: str | None = "Yes",
) -> dict[str, object]:
    snapshot = SQLiteSourceRepository(root).get_job_snapshots(str(job["job_id"]))[0]
    component = SsurgoComponentRecord(
        mukey="497588",
        cokey="26856137",
        comppct_r=20,
        hydricrating=hydricrating,
        hydricon=None,
        provenance={"fixture": True},
    )
    batch = SsurgoBatchRecord(
        batch_id=f"screening-{uuid4().hex}",
        source_snapshot_id=snapshot["snapshot_id"],
        source_version_id=candidate["version_id"],
        ingestion_run_id=candidate["run_id"],
        candidate_id=candidate["candidate_id"],
        artifact_path=candidate["artifact_path"],
        artifact_sha256=candidate["sha256"],
        artifact_size_bytes=candidate["byte_size"],
        source_url="https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
        provider_release="representative screening fixture",
        retrieved_at="2026-09-24T10:00:00+00:00",
        terms_url="https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
        map_units=(
            SsurgoMapUnitRecord(
                mukey="497588",
                musym="NdD",
                muname="Nederland fixture",
                geometry_wkt="MULTIPOLYGON (((-105 40,-104 40,-104 41,-105 41,-105 40)))",
                source_geometry_piece_count=1,
                analysis_area_sqm=1_000_000,
                components=(component,),
                provenance={"fixture": True},
            ),
        ),
        provenance={
            "validation_scope": "Representative screening fixture only",
            "hydric_interpretation": "Hydric-soil information; not a wetlands inventory or regulatory determination.",
        },
    )
    repository.stage_ssurgo_batch(batch)
    assert repository.validate_ssurgo_batch(batch.batch_id)["validation_status"] == "validated"
    return repository.promote_ssurgo_batch(batch.batch_id)


def test_ssurgo_postgis_unavailability_remains_source_level(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(
        root,
        tmp_path,
        Polygon([(-104.8, 40.2), (-104.7, 40.2), (-104.7, 40.3), (-104.8, 40.3), (-104.8, 40.2)]),
    )
    candidate = _promote_source(root, project_id, aoi, "ssurgo-screen-unavailable")
    job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("ssurgo",))

    class UnavailableSpatialRepository:
        def screen_ssurgo_snapshot(
            self, source_snapshot_id: str, source_version_id: str, aoi_geometry_wkt: str
        ) -> dict[str, object]:
            raise PostGISUnavailable("test database unavailable")

    result = run_job(
        job["job_id"],
        root,
        spatial_repository=UnavailableSpatialRepository(),  # type: ignore[arg-type]
    )
    source = result["source_results"][0]
    assert source["source_version_id"] == candidate["version_id"]
    assert source["source_status"] == "unavailable"
    assert source["observation_status"] == "unavailable"
    assert result["job_status"] == "completed"


@pytest.mark.skipif(
    not POSTGIS_AVAILABLE,
    reason="SSURGO screening integration requires ESGP_POSTGIS_URL and psycopg",
)
def test_fixture_screening_is_snapshot_pinned_and_exports_provenance(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(
        root,
        tmp_path,
        Polygon([(-104.8, 40.2), (-104.7, 40.2), (-104.7, 40.3), (-104.8, 40.3), (-104.8, 40.2)]),
    )
    candidate_one = _promote_source(root, project_id, aoi, "ssurgo-screen-v1")
    job_one = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("ssurgo",),
        screening_mode="ssurgo_fixture_only",
    )
    repository = PostGISRepository()
    repository.migrate()
    _load_batch(repository, root, job_one, candidate_one)

    result_one = run_job(job_one["job_id"], root, spatial_repository=repository)
    source_one = result_one["source_results"][0]
    assert result_one["screening_mode"] == "ssurgo_fixture_only"
    assert source_one["source_version_id"] == candidate_one["version_id"]
    assert source_one["source_status"] == "fixture_only"
    assert source_one["product_status"] == "fixture_only"
    assert source_one["metrics"]["screening_status"] == "observed"
    assert source_one["metrics"]["intersecting_mapunit_count"] == 1
    assert source_one["metrics"]["component_record_count"] == 1
    assert source_one["metrics"]["hydric_positive_record_count"] == 1
    assert (
        "not a wetlands inventory or regulatory determination"
        in source_one["metrics"]["hydric_interpretation"]
    )
    assert (
        source_one["features"][0]["properties"]["source_snapshot_id"]
        == source_one["source_snapshot_id"]
    )

    outputs = export_result(job_one["job_id"], root, tmp_path / "exports")
    exported = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert exported["source_results"][0]["source_version_id"] == candidate_one["version_id"]
    with outputs[1].open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["source_status"] == "fixture_only"
    assert row["source_snapshot_id"] == source_one["source_snapshot_id"]
    geojson = json.loads(outputs[2].read_text(encoding="utf-8"))
    source_feature = geojson["features"][1]
    assert source_feature["properties"]["source_version_id"] == candidate_one["version_id"]
    assert (
        geojson["properties"]["source_states"][0]["source_snapshot_id"]
        == source_one["source_snapshot_id"]
    )

    candidate_two = _promote_source(root, project_id, aoi, "ssurgo-screen-v2")
    job_two = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("ssurgo",),
        screening_mode="ssurgo_fixture_only",
    )
    _load_batch(repository, root, job_two, candidate_two, hydricrating="No")
    result_two = run_job(job_two["job_id"], root, spatial_repository=repository)
    assert result_two["source_results"][0]["source_version_id"] == candidate_two["version_id"]
    historical = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert historical["source_results"][0]["source_version_id"] == candidate_one["version_id"]


@pytest.mark.skipif(
    not POSTGIS_AVAILABLE,
    reason="SSURGO screening integration requires ESGP_POSTGIS_URL and psycopg",
)
def test_fixture_screening_distinguishes_uncovered_and_missing_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(
        root,
        tmp_path,
        Polygon([(-105.8, 40.2), (-105.7, 40.2), (-105.7, 40.3), (-105.8, 40.3), (-105.8, 40.2)]),
    )
    candidate = _promote_source(root, project_id, aoi, "ssurgo-screen-uncovered")
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("ssurgo",),
        screening_mode="ssurgo_fixture_only",
    )
    repository = PostGISRepository()
    repository.migrate()
    _load_batch(repository, root, job, candidate, hydricrating=None)
    result = run_job(job["job_id"], root, spatial_repository=repository)
    source = result["source_results"][0]
    assert source["metrics"]["screening_status"] == "uncovered"
    assert source["observation_status"] == "not_covered"
    assert source["metrics"]["covered_aoi_percentage"] == 0
    assert source["features"] == []

    covered_path = tmp_path / "covered-revision.geojson"
    covered_path.write_text(
        json.dumps(
            mapping(
                Polygon(
                    [
                        (-104.8, 40.2),
                        (-104.7, 40.2),
                        (-104.7, 40.3),
                        (-104.8, 40.3),
                        (-104.8, 40.2),
                    ]
                )
            )
        ),
        encoding="utf-8",
    )
    covered_aoi = revise_aoi(project_id, covered_path, root)
    covered_candidate = _promote_source(root, project_id, covered_aoi, "ssurgo-screen-no-indicator")
    no_indicator_job = create_job(
        project_id,
        root,
        str(covered_aoi["aoi_id"]),
        source_ids=("ssurgo",),
        screening_mode="ssurgo_fixture_only",
    )
    _load_batch(repository, root, no_indicator_job, covered_candidate, hydricrating=None)
    no_indicator_source = run_job(no_indicator_job["job_id"], root, spatial_repository=repository)[
        "source_results"
    ][0]
    assert no_indicator_source["metrics"]["screening_status"] == "no_indicator_observed"
    assert no_indicator_source["metrics"]["intersecting_mapunit_count"] == 1

    missing_root = tmp_path / "missing-external"
    missing_project_id, missing_aoi = _project(
        missing_root,
        tmp_path,
        Polygon([(-104.8, 40.2), (-104.7, 40.2), (-104.7, 40.3), (-104.8, 40.3), (-104.8, 40.2)]),
    )
    missing_job = create_job(
        missing_project_id,
        missing_root,
        str(missing_aoi["aoi_id"]),
        source_ids=("ssurgo",),
        screening_mode="ssurgo_fixture_only",
    )
    missing_result = run_job(missing_job["job_id"], missing_root, spatial_repository=repository)
    missing_source = missing_result["source_results"][0]
    assert missing_source["source_status"] == "unknown"
    assert missing_source["observation_status"] == "incomplete_source"
