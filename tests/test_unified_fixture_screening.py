from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from shapely.geometry import Polygon, mapping
from shapely.ops import transform

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.models import Acquisition, Observation
from environmental_screening_platform.workflow import (
    FIXTURE_SCREENING_SOURCES,
    create_job,
    create_project,
    export_result,
    retry_job,
    run_job,
)


class _FixtureSpatialRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, str]] = []

    def screen_ssurgo_snapshot(
        self, source_snapshot_id: str, source_version_id: str, aoi_geometry_wkt: str
    ) -> dict[str, object]:
        self.calls.append((source_snapshot_id, source_version_id, aoi_geometry_wkt))
        if self.fail:
            raise RuntimeError("fixture PostGIS query failed")
        return {
            "status": "available",
            "coverage_status": "complete",
            "observation_status": "data_observed",
            "metrics": {
                "covered_aoi_area_sqm": 100.0,
                "covered_aoi_percentage": 100.0,
                "intersecting_mapunit_count": 1,
                "component_record_count": 1,
                "hydric_positive_record_count": 1,
                "hydric_interpretation": (
                    "Hydric-soil information; not a wetlands inventory or regulatory determination."
                ),
            },
            "provenance": {
                "source_snapshot_id": source_snapshot_id,
                "source_version_id": source_version_id,
            },
            "features": [
                {
                    "type": "Feature",
                    "geometry": mapping(
                        Polygon(
                            [
                                (-104.8, 40.2),
                                (-104.7, 40.2),
                                (-104.7, 40.3),
                                (-104.8, 40.3),
                                (-104.8, 40.2),
                            ]
                        )
                    ),
                    "properties": {"mukey": "fixture-mukey"},
                }
            ],
        }


def _project(root: Path, tmp_path: Path) -> tuple[str, dict[str, object]]:
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
                            Polygon(
                                [
                                    (-106, 39),
                                    (-103, 39),
                                    (-103, 42),
                                    (-106, 42),
                                    (-106, 39),
                                ]
                            )
                        ),
                        "properties": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    aoi = Polygon(
        [
            (-104.8, 40.2),
            (-104.7, 40.2),
            (-104.7, 40.3),
            (-104.8, 40.3),
            (-104.8, 40.2),
        ]
    )
    aoi_path = tmp_path / f"aoi-{uuid4().hex}.geojson"
    aoi_path.write_text(json.dumps(mapping(aoi)), encoding="utf-8")
    created = create_project("Unified fixture screening", aoi_path, root)
    return str(created["project"]["project_id"]), created["aoi_revision"]


def _raster_bytes(values: np.ndarray, aoi: Polygon, crs: str, nodata: float) -> bytes:
    projected = transform(Transformer.from_crs(4326, crs, always_xy=True).transform, aoi)
    minx, miny, maxx, maxy = projected.bounds
    raster_transform = Affine(
        (maxx - minx) / values.shape[1],
        0,
        minx,
        0,
        -(maxy - miny) / values.shape[0],
        maxy,
    )
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype=values.dtype,
            crs=crs,
            transform=raster_transform,
            nodata=nodata,
        ) as dataset:
            if crs == "EPSG:5070":
                dataset.update_tags(units="m", vertical_datum="NAVD88")
            dataset.write(values, 1)
        return memory.read()


def _promote(
    root: Path,
    project_id: str,
    aoi: dict[str, object],
    source_id: str,
    body: bytes,
    release: str,
    extension: str,
) -> dict[str, object]:
    artifact = root / "raw" / source_id / f"{release}{extension}"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    url = f"https://provider.example/{source_id}"
    acquisition = Acquisition(
        source_id=source_id,
        provider="fixture provider",
        release=release,
        source_url=url,
        acquired_at="2026-09-24T10:00:00+00:00",
        media_type="image/tiff" if extension == ".tif" else "application/octet-stream",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://provider.example/terms",
    )
    repository = SQLiteSourceRepository(root)
    run = repository.begin_run(
        source_id=source_id,
        requested_url=url,
        adapter_version="unified-fixture-test-1",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )
    repository.record_attempt(
        run["run_id"],
        status="acquired",
        requested_url=url,
        actual_url=url,
        retrieved_at=acquisition.acquired_at,
        sha256=digest,
        byte_size=len(body),
    )
    candidate = repository.record_candidate(
        run["run_id"],
        acquisition=acquisition,
        adapter_version="unified-fixture-test-1",
        status="validated",
        validation_status="validated",
        coverage_status="complete",
        observation_status="data_observed",
        validation={
            "validation_scope": f"Deterministic {source_id} fixture",
            "product_status": "fixture_only",
            "metrics": {},
            "warnings": [],
        },
    )
    repository.promote(candidate["candidate_id"])
    return candidate


def _setup_sources(
    tmp_path: Path,
) -> tuple[Path, str, dict[str, object], dict[str, dict[str, object]]]:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    geometry = Polygon(
        [
            (-104.8, 40.2),
            (-104.7, 40.2),
            (-104.7, 40.3),
            (-104.8, 40.3),
            (-104.8, 40.2),
        ]
    )
    candidates = {
        "ssurgo": _promote(
            root, project_id, aoi, "ssurgo", b"ssurgo-fixture", "ssurgo-v1", ".json"
        ),
        "annual_nlcd": _promote(
            root,
            project_id,
            aoi,
            "annual_nlcd",
            _raster_bytes(
                np.array([[21, 22], [23, 41]], dtype="uint8"), geometry, "EPSG:3857", 255
            ),
            "nlcd-v1",
            ".tif",
        ),
        "3dep": _promote(
            root,
            project_id,
            aoi,
            "3dep",
            _raster_bytes(
                np.array([[1600, 1601], [1602, 1603]], dtype="float32"),
                geometry,
                "EPSG:5070",
                -999999,
            ),
            "3dep-v1",
            ".tif",
        ),
    }
    return root, project_id, aoi, candidates


def test_screen_fixtures_unifies_sources_statuses_and_exports(tmp_path: Path) -> None:
    root, project_id, aoi, candidates = _setup_sources(tmp_path)
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=FIXTURE_SCREENING_SOURCES,
        screening_mode="fixtures",
    )
    repository = _FixtureSpatialRepository()
    result = run_job(job["job_id"], root, spatial_repository=repository)

    assert result["job_status"] == "completed"
    assert result["overall_status"] == "partial"
    assert result["product_status"] == "fixture_only"
    assert result["job_outcome"]["blocked_sources"] == ["fema_nfhl"]
    assert result["job_outcome"]["quarantined_sources"] == ["padus"]
    assert result["job_outcome"]["successful_sources"] == ["ssurgo", "annual_nlcd", "3dep"]
    assert [source["source_id"] for source in result["source_results"]] == list(
        FIXTURE_SCREENING_SOURCES
    )
    by_source = {source["source_id"]: source for source in result["source_results"]}
    assert by_source["ssurgo"]["metrics"]["hydric_positive_record_count"] == 1
    assert by_source["annual_nlcd"]["metrics"]["valid_pixel_count"] == 4
    assert by_source["3dep"]["metrics"]["mean_elevation"] == pytest.approx(1601.5)
    assert by_source["padus"]["validation_status"] == "conditionally_validated"
    assert by_source["padus"]["snapshot_status"] == "quarantined"
    assert by_source["fema_nfhl"]["validation_status"] == "access_blocked"
    assert by_source["fema_nfhl"]["snapshot_status"] == "blocked"
    assert len(repository.calls) == 1
    ssurgo_call = repository.calls[0]
    assert ssurgo_call[0] == by_source["ssurgo"]["source_snapshot_id"]
    assert ssurgo_call[1] == candidates["ssurgo"]["version_id"]
    assert ssurgo_call[2]
    matrix = {row["source_id"]: row for row in result["source_status_matrix"]}
    assert matrix["annual_nlcd"]["sha256"] == candidates["annual_nlcd"]["sha256"]
    assert matrix["3dep"]["availability_status"] == "fixture_only"
    assert matrix["padus"]["availability_status"] == "quarantined"
    assert matrix["fema_nfhl"]["availability_status"] == "blocked"

    outputs = export_result(job["job_id"], root, tmp_path / "exports")
    exported = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert len(exported["source_results"]) == 5
    assert exported["source_status_matrix"] == result["source_status_matrix"]
    with outputs[1].open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 5
    assert {row["source_id"] for row in rows} == set(FIXTURE_SCREENING_SOURCES)
    assert json.loads(rows[0]["source_status_matrix_json"])[-1]["source_id"] == "fema_nfhl"
    geojson = json.loads(outputs[2].read_text(encoding="utf-8"))
    assert geojson["properties"]["overall_status"] == "partial"
    assert len(geojson["properties"]["source_status_matrix"]) == 5
    assert {feature["properties"].get("source_id") for feature in geojson["features"][1:]} == {
        "ssurgo",
        "3dep",
    }


def test_screen_fixtures_preserves_other_sources_when_one_fails(tmp_path: Path) -> None:
    root, project_id, aoi, _candidates = _setup_sources(tmp_path)
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=FIXTURE_SCREENING_SOURCES,
        screening_mode="fixtures",
    )
    result = run_job(job["job_id"], root, spatial_repository=_FixtureSpatialRepository(fail=True))
    by_source = {source["source_id"]: source for source in result["source_results"]}
    assert result["job_status"] == "completed"
    assert result["overall_status"] == "partial"
    assert by_source["ssurgo"]["observation_status"] == Observation.UNAVAILABLE.value
    assert by_source["ssurgo"]["product_status"] == "source_failure"
    assert by_source["ssurgo"]["source_status"] == "unavailable"
    assert by_source["annual_nlcd"]["observation_status"] == Observation.DATA_OBSERVED.value
    assert by_source["3dep"]["observation_status"] == Observation.DATA_OBSERVED.value
    assert by_source["fema_nfhl"]["source_status"] == "blocked"


def test_screen_fixtures_retries_same_snapshot_and_new_job_uses_new_version(
    tmp_path: Path,
) -> None:
    root, project_id, aoi, candidates = _setup_sources(tmp_path)
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=FIXTURE_SCREENING_SOURCES,
        screening_mode="fixtures",
    )
    revision_path = (
        root / "workspace" / "projects" / project_id / "aoi-revisions" / f"{aoi['aoi_id']}.json"
    )
    revision = revision_path.read_text(encoding="utf-8")
    revision_path.unlink()
    with pytest.raises(FileNotFoundError):
        run_job(job["job_id"], root, spatial_repository=_FixtureSpatialRepository())
    revision_path.write_text(revision, encoding="utf-8")
    retried = retry_job(job["job_id"], root, spatial_repository=_FixtureSpatialRepository())
    assert retried["source_snapshot_ids"] == job["source_snapshot_ids"]
    assert retried["source_results"][0]["source_version_id"] == candidates["ssurgo"]["version_id"]

    new_nlcd = _promote(
        root,
        project_id,
        aoi,
        "annual_nlcd",
        _raster_bytes(
            np.full((2, 2), 90, dtype="uint8"),
            Polygon(
                [
                    (-104.8, 40.2),
                    (-104.7, 40.2),
                    (-104.7, 40.3),
                    (-104.8, 40.3),
                    (-104.8, 40.2),
                ]
            ),
            "EPSG:3857",
            255,
        ),
        "nlcd-v2",
        ".tif",
    )
    fresh = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=FIXTURE_SCREENING_SOURCES,
        screening_mode="fixtures",
    )
    assert fresh["source_snapshot_ids"] != job["source_snapshot_ids"]
    fresh_result = run_job(fresh["job_id"], root, spatial_repository=_FixtureSpatialRepository())
    fresh_nlcd = next(
        source for source in fresh_result["source_results"] if source["source_id"] == "annual_nlcd"
    )
    assert fresh_nlcd["source_version_id"] == new_nlcd["version_id"]
    historical_nlcd = next(
        source for source in retried["source_results"] if source["source_id"] == "annual_nlcd"
    )
    assert historical_nlcd["source_version_id"] == candidates["annual_nlcd"]["version_id"]
