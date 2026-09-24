from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.models import Acquisition, Observation
from environmental_screening_platform.raster import screen_nlcd_raster
from environmental_screening_platform.workflow import (
    create_job,
    create_project,
    export_result,
    run_job,
)


def _project(root: Path, tmp_path: Path, aoi: Polygon) -> tuple[str, dict[str, object]]:
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
    aoi_path = tmp_path / f"aoi-{uuid4().hex}.geojson"
    aoi_path.write_text(json.dumps(mapping(aoi)), encoding="utf-8")
    created = create_project("NLCD fixture screening", aoi_path, root)
    return str(created["project"]["project_id"]), created["aoi_revision"]


def _raster_bytes(values: np.ndarray, aoi: Polygon) -> bytes:
    projected = transform(Transformer.from_crs(4326, 3857, always_xy=True).transform, aoi)
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
            crs="EPSG:3857",
            transform=raster_transform,
            nodata=255,
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


def _promote_nlcd(
    root: Path,
    project_id: str,
    aoi: dict[str, object],
    body: bytes,
    release: str,
) -> dict[str, object]:
    artifact = root / "raw" / "annual_nlcd" / f"{release}.tif"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    acquisition = Acquisition(
        source_id="annual_nlcd",
        provider="USGS EROS / MRLC Annual NLCD WCS",
        release=release,
        source_url="https://dmsdata.cr.usgs.gov/geoserver/wcs",
        acquired_at="2026-09-24T10:00:00+00:00",
        media_type="image/tiff",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://doi.org/10.5066/P143HE8T",
    )
    repository = SQLiteSourceRepository(root)
    run = repository.begin_run(
        source_id="annual_nlcd",
        requested_url=acquisition.source_url,
        adapter_version="nlcd-screening-test-1",
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
        adapter_version="nlcd-screening-test-1",
        status="validated",
        validation_status="validated",
        coverage_status="complete",
        observation_status="data_observed",
        validation={
            "validation_scope": "Representative Annual NLCD Collection 1.2 2025 raster fixture",
            "product_status": "effective 2025 annual land cover",
            "metrics": {},
            "warnings": [],
        },
    )
    repository.promote(candidate["candidate_id"])
    return candidate


def test_nlcd_fixture_screening_is_snapshot_pinned_and_exported(tmp_path: Path) -> None:
    root = tmp_path / "external"
    aoi = Polygon(
        [
            (-104.8, 40.2),
            (-104.7, 40.2),
            (-104.7, 40.3),
            (-104.8, 40.3),
            (-104.8, 40.2),
        ]
    )
    project_id, aoi_revision = _project(root, tmp_path, aoi)
    values = np.array([[21, 21, 22, 22], [23, 23, 23, 255], [41, 41, 42, 42]], dtype="uint8")
    candidate_one = _promote_nlcd(
        root, project_id, aoi_revision, _raster_bytes(values, aoi), "nlcd-v1"
    )
    job_one = create_job(
        project_id,
        root,
        str(aoi_revision["aoi_id"]),
        source_ids=("annual_nlcd",),
        screening_mode="nlcd_fixture_only",
    )
    result_one = run_job(job_one["job_id"], root)
    source_one = result_one["source_results"][0]
    assert result_one["screening_mode"] == "nlcd_fixture_only"
    assert source_one["source_version_id"] == candidate_one["version_id"]
    assert source_one["source_status"] == "fixture_only"
    assert source_one["product_status"] == "fixture_only"
    assert source_one["metrics"]["screening_status"] == "nodata"
    assert source_one["metrics"]["valid_pixel_count"] == 11
    assert source_one["metrics"]["nodata_pixel_count"] == 1
    assert source_one["metrics"]["classes"]["21"]["class_name"] == "developed_open_space"
    assert source_one["metrics"]["raster"]["crs"] == "EPSG:3857"
    assert source_one["metrics"]["raster"]["source_year"] == 2025
    assert source_one["observation_status"] == Observation.NODATA.value

    outputs = export_result(job_one["job_id"], root, tmp_path / "exports")
    exported = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert (
        exported["source_results"][0]["provenance"]["source_version_id"]
        == candidate_one["version_id"]
    )
    assert exported["source_results"][0]["metrics"]["valid_pixel_count"] == 11
    with outputs[1].open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["source_status"] == "fixture_only"
    assert json.loads(row["metrics_json"])["source_year"] == 2025
    geojson = json.loads(outputs[2].read_text(encoding="utf-8"))
    assert len(geojson["features"]) == 1
    assert (
        geojson["properties"]["source_states"][0]["source_version_id"]
        == candidate_one["version_id"]
    )

    candidate_two = _promote_nlcd(
        root,
        project_id,
        aoi_revision,
        _raster_bytes(np.full((3, 4), 90, dtype="uint8"), aoi),
        "nlcd-v2",
    )
    job_two = create_job(
        project_id,
        root,
        str(aoi_revision["aoi_id"]),
        source_ids=("annual_nlcd",),
        screening_mode="nlcd_fixture_only",
    )
    result_two = run_job(job_two["job_id"], root)
    assert result_two["source_results"][0]["source_version_id"] == candidate_two["version_id"]
    assert result_two["source_results"][0]["metrics"]["classes"]["90"]["class_name"] == (
        "woody_wetlands_classification"
    )
    historical = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert historical["source_results"][0]["source_version_id"] == candidate_one["version_id"]


def test_nlcd_fixture_screening_distinguishes_uncovered_and_missing_artifact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external"
    aoi = Polygon(
        [
            (-104.8, 40.2),
            (-104.7, 40.2),
            (-104.7, 40.3),
            (-104.8, 40.3),
            (-104.8, 40.2),
        ]
    )
    project_id, aoi_revision = _project(root, tmp_path, aoi)
    raster_aoi = Polygon(
        [
            (-105.8, 40.2),
            (-105.7, 40.2),
            (-105.7, 40.3),
            (-105.8, 40.3),
            (-105.8, 40.2),
        ]
    )
    candidate = _promote_nlcd(
        root,
        project_id,
        aoi_revision,
        _raster_bytes(np.full((2, 2), 41, dtype="uint8"), raster_aoi),
        "nlcd-uncovered",
    )
    job = create_job(
        project_id,
        root,
        str(aoi_revision["aoi_id"]),
        source_ids=("annual_nlcd",),
        screening_mode="nlcd_fixture_only",
    )
    result = run_job(job["job_id"], root)
    source = result["source_results"][0]
    assert source["source_status"] == "fixture_only"
    assert source["metrics"]["screening_status"] == "uncovered"
    assert source["observation_status"] == Observation.NOT_COVERED.value
    assert source["metrics"]["valid_pixel_count"] == 0
    assert source["metrics"]["covered_aoi_percentage"] == 0

    artifact_path = Path(str(candidate["artifact_path"]))
    artifact_path.unlink()
    missing_job = create_job(
        project_id,
        root,
        str(aoi_revision["aoi_id"]),
        source_ids=("annual_nlcd",),
        screening_mode="nlcd_fixture_only",
    )
    missing = run_job(missing_job["job_id"], root)["source_results"][0]
    assert missing["source_status"] == "unavailable"
    assert missing["coverage_status"] == "unavailable"
    assert missing["observation_status"] == Observation.UNAVAILABLE.value

    no_version_root = tmp_path / "no-version-external"
    no_version_project_id, no_version_aoi = _project(no_version_root, tmp_path, aoi)
    no_version_job = create_job(
        no_version_project_id,
        no_version_root,
        str(no_version_aoi["aoi_id"]),
        source_ids=("annual_nlcd",),
        screening_mode="nlcd_fixture_only",
    )
    no_version = run_job(no_version_job["job_id"], no_version_root)["source_results"][0]
    assert no_version["source_status"] == "unknown"
    assert no_version["observation_status"] == Observation.INCOMPLETE_SOURCE.value


def test_nlcd_screening_metrics_are_reproducible(tmp_path: Path) -> None:
    aoi = Polygon(
        [
            (-104.8, 40.2),
            (-104.7, 40.2),
            (-104.7, 40.3),
            (-104.8, 40.3),
            (-104.8, 40.2),
        ]
    )
    body = _raster_bytes(np.array([[11, 12], [71, 82]], dtype="uint8"), aoi)
    artifact = tmp_path / "fixture.tif"
    artifact.write_bytes(body)
    provenance = {"sha256": hashlib.sha256(body).hexdigest(), "release": "test"}
    first = screen_nlcd_raster(
        artifact,
        aoi,
        source_snapshot_id="snapshot-1",
        source_version_id="version-1",
        provenance=provenance,
    )
    second = screen_nlcd_raster(
        artifact,
        aoi,
        source_snapshot_id="snapshot-1",
        source_version_id="version-1",
        provenance=provenance,
    )
    assert first == second


EXTERNAL_NLCD_FIXTURE = os.environ.get("ESGP_NLCD_FIXTURE_PATH")


@pytest.mark.skipif(
    not EXTERNAL_NLCD_FIXTURE,
    reason="ESGP_NLCD_FIXTURE_PATH is not configured",
)
def test_validated_external_nlcd_fixture_is_readable() -> None:
    path = Path(EXTERNAL_NLCD_FIXTURE)
    with rasterio.open(path) as dataset:
        bounds = dataset.bounds
        to_wgs84 = Transformer.from_crs(dataset.crs, 4326, always_xy=True).transform
        aoi = transform(
            to_wgs84,
            shape(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [bounds.left, bounds.bottom],
                            [bounds.right, bounds.bottom],
                            [bounds.right, bounds.top],
                            [bounds.left, bounds.top],
                            [bounds.left, bounds.bottom],
                        ]
                    ],
                }
            ),
        )
    result = screen_nlcd_raster(
        path,
        aoi,
        source_snapshot_id="external-fixture-snapshot",
        source_version_id="external-fixture-version",
        provenance={"artifact_path": str(path)},
    )
    assert result["status"] == "available"
    assert result["metrics"]["valid_pixel_count"] > 0
    assert result["metrics"]["raster"]["source_year"] == 2025
