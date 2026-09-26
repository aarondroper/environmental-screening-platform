from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from shapely.geometry import Polygon, mapping
from shapely.ops import transform

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.models import Acquisition, Observation
from environmental_screening_platform.workflow import (
    create_job,
    create_project,
    export_result,
    retry_job,
    run_job,
)


def _project(root: Path, tmp_path: Path) -> tuple[str, dict[str, object]]:
    aoi = Polygon(
        [
            (-77.041, 38.900),
            (-77.039, 38.900),
            (-77.039, 38.902),
            (-77.041, 38.902),
            (-77.041, 38.900),
        ]
    )
    aoi_path = tmp_path / "dc-aoi.geojson"
    aoi_path.write_text(json.dumps(mapping(aoi)), encoding="utf-8")
    created = create_project("Active raster screening", aoi_path, root)
    return str(created["project"]["project_id"]), created["aoi_revision"]


def _raster_bytes(aoi: Polygon, source: str, values: np.ndarray) -> bytes:
    crs = "EPSG:5070" if source == "annual_nlcd" else "EPSG:4269"
    nodata = 250 if source == "annual_nlcd" else -999999.0
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
            if source == "3dep":
                dataset.update_tags(units="m", vertical_datum="NAVD88")
            dataset.write(values, 1)
        return memory.read()


def _metrics(source: str) -> dict[str, object]:
    common: dict[str, object] = {
        "coverage": {
            "covered_aoi_percentage": 100.0,
            "uncovered_aoi_percentage": 0.0,
        },
        "pixel_accounting": {"valid_pixel_count": 4, "nodata_pixel_count": 0},
    }
    if source == "annual_nlcd":
        return {
            **common,
            "crs": "EPSG:5070",
            "width": 2,
            "height": 2,
            "dtype": "uint8",
            "transform": [30.0, 0.0, 0.0, 0.0, -30.0, 0.0],
            "resolution_m": [30.0, 30.0],
            "nodata": 250,
            "observed_class_values": [21, 22],
        }
    return {
        **common,
        "source_crs": "EPSG:4269",
        "dimensions": {"width": 2, "height": 2},
        "dtype": "float32",
        "transform": [1 / 10800, 0.0, 0.0, 0.0, -1 / 10800, 0.0],
        "resolution_arc_seconds": [1 / 3, 1 / 3],
        "nodata": -999999.0,
        "elevation_m": {"min": 1.0, "mean": 2.5, "max": 4.0},
    }


def _promote(
    root: Path,
    project_id: str,
    aoi: dict[str, object],
    source: str,
    body: bytes,
    release: str,
) -> dict[str, object]:
    artifact = root / "raw" / source / f"{release}.tif"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    repository = SQLiteSourceRepository(root)
    url = f"https://provider.example/{source}"
    acquisition = Acquisition(
        source_id=source,
        provider="active raster test provider",
        release=release,
        source_url=url,
        acquired_at="2026-09-26T10:00:00+00:00",
        media_type="image/tiff",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://provider.example/terms",
    )
    run = repository.begin_run(
        source_id=source,
        requested_url=url,
        adapter_version="active-screening-test-1",
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
        adapter_version="active-screening-test-1",
        status="validated",
        validation_status="validated",
        coverage_status="complete",
        observation_status="data_observed",
        validation={
            "validation_scope": f"AOI-scoped {source} test artifact",
            "product_status": "active_aoi_version",
            "metrics": _metrics(source),
            "source_provenance": {
                "aoi_id": str(aoi["aoi_id"]),
                "aoi_revision": int(aoi["revision"]),
                "aoi_geometry_sha256": str(aoi["geometry_sha256"]),
            },
            "quarantined_count": 0,
        },
    )
    decision = repository.promote(
        candidate["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )
    assert decision["decision"] == "promoted"
    return candidate


@pytest.mark.parametrize("source", ["annual_nlcd", "3dep"])
def test_screen_active_uses_exact_aoi_scoped_active_version(tmp_path: Path, source: str) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    geometry = Polygon(
        [
            (-77.041, 38.900),
            (-77.039, 38.900),
            (-77.039, 38.902),
            (-77.041, 38.902),
            (-77.041, 38.900),
        ]
    )
    values = (
        np.array([[21, 22], [23, 24]], dtype="uint8")
        if source == "annual_nlcd"
        else np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32")
    )
    candidate = _promote(
        root, project_id, aoi, source, _raster_bytes(geometry, source, values), "v1"
    )
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=(source,),
        screening_mode="active_aoi",
        require_aoi_scoped_active=True,
    )
    result = run_job(job["job_id"], root)
    source_result = result["source_results"][0]

    assert result["screening_mode"] == "active_aoi"
    assert result["aoi_geometry_sha256"] == aoi["geometry_sha256"]
    assert source_result["source_status"] == "active_aoi"
    assert source_result["product_status"] == "active_aoi_version"
    assert source_result["active_version_id"] == candidate["version_id"]
    assert source_result["source_version_id"] == candidate["version_id"]
    assert source_result["candidate_id"] == candidate["candidate_id"]
    assert source_result["ingestion_run_id"] == candidate["run_id"]
    assert source_result["provenance"]["sha256"] == candidate["sha256"]
    if source == "annual_nlcd":
        assert source_result["metrics"]["valid_pixel_count"] == 4
        assert source_result["metrics"]["source_year"] == 2025
    else:
        assert source_result["metrics"]["valid_cell_count"] == 4
        assert source_result["metrics"]["elevation_units"] == "m"
        assert source_result["metrics"]["vertical_datum"] == "NAVD88"

    outputs = export_result(job["job_id"], root, tmp_path / "exports")
    exported = json.loads(outputs[0].read_text(encoding="utf-8"))
    exported_source = exported["source_results"][0]
    assert exported_source["active_version_id"] == candidate["version_id"]
    with outputs[1].open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["active_version_id"] == candidate["version_id"]
    assert row["aoi_geometry_sha256"] == aoi["geometry_sha256"]
    geojson = json.loads(outputs[2].read_text(encoding="utf-8"))
    assert geojson["properties"]["aoi_geometry_sha256"] == aoi["geometry_sha256"]
    if source == "3dep":
        assert geojson["features"][1]["properties"]["active_version_id"] == candidate["version_id"]


def test_screen_active_missing_and_unpromoted_sources_are_explicit(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    geometry = Polygon(
        [
            (-77.041, 38.900),
            (-77.039, 38.900),
            (-77.039, 38.902),
            (-77.041, 38.902),
            (-77.041, 38.900),
        ]
    )
    body = _raster_bytes(geometry, "annual_nlcd", np.ones((2, 2), dtype="uint8"))
    # A candidate exists but is deliberately not promoted.
    repository = SQLiteSourceRepository(root)
    artifact = root / "raw" / "unpromoted.tif"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    acquisition = Acquisition(
        source_id="annual_nlcd",
        provider="test",
        release="unpromoted",
        source_url="https://provider.example/nlcd",
        acquired_at="2026-09-26T10:00:00+00:00",
        media_type="image/tiff",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://provider.example/terms",
    )
    run = repository.begin_run(
        source_id="annual_nlcd",
        requested_url=acquisition.source_url,
        adapter_version="active-screening-test-1",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=1,
    )
    repository.record_candidate(
        run["run_id"],
        acquisition=acquisition,
        adapter_version="active-screening-test-1",
        status="incomplete",
        validation_status="validated",
        coverage_status="complete",
        observation_status="data_observed",
        validation={"source_provenance": {"aoi_geometry_sha256": aoi["geometry_sha256"]}},
    )
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("annual_nlcd", "3dep"),
        screening_mode="active_aoi",
        require_aoi_scoped_active=True,
    )
    result = run_job(job["job_id"], root)
    by_source = {item["source_id"]: item for item in result["source_results"]}

    assert by_source["annual_nlcd"]["snapshot_status"] == "incomplete"
    assert by_source["annual_nlcd"]["observation_status"] == Observation.INCOMPLETE_SOURCE.value
    assert by_source["annual_nlcd"]["aoi_geometry_sha256"] == aoi["geometry_sha256"]
    assert by_source["3dep"]["snapshot_status"] == "unknown"
    assert by_source["3dep"]["source_status"] == "unknown"
    assert by_source["3dep"]["aoi_geometry_sha256"] == aoi["geometry_sha256"]
    assert by_source["3dep"]["metrics"] == {}
    assert result["overall_status"] == "partial"


def test_screen_active_reuses_snapshot_after_later_promotion_and_retry(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    geometry = Polygon(
        [
            (-77.041, 38.900),
            (-77.039, 38.900),
            (-77.039, 38.902),
            (-77.041, 38.902),
            (-77.041, 38.900),
        ]
    )
    first = _promote(
        root,
        project_id,
        aoi,
        "annual_nlcd",
        _raster_bytes(geometry, "annual_nlcd", np.ones((2, 2), dtype="uint8")),
        "v1",
    )
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("annual_nlcd",),
        screening_mode="active_aoi",
        require_aoi_scoped_active=True,
    )
    revision_path = (
        root / "workspace" / "projects" / project_id / "aoi-revisions" / f"{aoi['aoi_id']}.json"
    )
    revision = revision_path.read_text(encoding="utf-8")
    revision_path.unlink()
    with pytest.raises(FileNotFoundError):
        run_job(job["job_id"], root)
    revision_path.write_text(revision, encoding="utf-8")
    second = _promote(
        root,
        project_id,
        aoi,
        "annual_nlcd",
        _raster_bytes(geometry, "annual_nlcd", np.full((2, 2), 2, dtype="uint8")),
        "v2",
    )
    retried = retry_job(job["job_id"], root)

    assert job["source_snapshot_ids"] == retried["source_snapshot_ids"]
    assert retried["source_results"][0]["source_version_id"] == first["version_id"]
    assert retried["source_results"][0]["active_version_id"] == first["version_id"]
    fresh = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("annual_nlcd",),
        screening_mode="active_aoi",
        require_aoi_scoped_active=True,
    )
    fresh_result = run_job(fresh["job_id"], root)
    assert fresh_result["source_results"][0]["source_version_id"] == second["version_id"]


LIVE_SMOKE_ROOT = Path(
    os.environ.get(
        "ESGP_LIVE_GENERIC_SMOKE_DIR",
        "/home/aarondroper/projects/environmental-screening-platform-data/live-generic-smoke-20260925",
    )
)


@pytest.mark.skipif(
    os.environ.get("ESGP_RUN_LIVE_SMOKE") != "1"
    or not (
        LIVE_SMOKE_ROOT
        / "raw/annual_nlcd/6b/6bc353d127a2a7d5a66c8152cfea099f271275e172d0924c18470fc0d93a6c4e.tif"
    ).exists()
    or not (
        LIVE_SMOKE_ROOT
        / "raw/3dep/8c/8c67738d7c829e9f408958b61fb2526df94a645d89805389c248dac84a9f3d18.tif"
    ).exists(),
    reason="Set ESGP_RUN_LIVE_SMOKE=1 with the retained Washington, DC artifacts to run",
)
def test_screen_active_retained_washington_dc_artifacts_without_redownload(
    tmp_path: Path,
) -> None:
    # The test uses hard links into a temporary catalog root; no provider request
    # or raw-artifact copy/download is performed.
    source_aoi = json.loads((LIVE_SMOKE_ROOT / "aoi.geojson").read_text(encoding="utf-8"))
    aoi_path = tmp_path / "aoi.geojson"
    aoi_path.write_text(json.dumps(source_aoi), encoding="utf-8")
    root = tmp_path / "external"
    created = create_project("Retained DC smoke", aoi_path, root)
    project_id = str(created["project"]["project_id"])
    aoi = created["aoi_revision"]
    sources = {
        "annual_nlcd": LIVE_SMOKE_ROOT
        / "raw/annual_nlcd/6b/6bc353d127a2a7d5a66c8152cfea099f271275e172d0924c18470fc0d93a6c4e.tif",
        "3dep": LIVE_SMOKE_ROOT
        / "raw/3dep/8c/8c67738d7c829e9f408958b61fb2526df94a645d89805389c248dac84a9f3d18.tif",
    }
    for source, original in sources.items():
        artifact = root / "raw" / source / original.name
        artifact.parent.mkdir(parents=True, exist_ok=True)
        os.link(original, artifact)
        body_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        with rasterio.open(artifact) as dataset:
            raster_profile = {
                "width": dataset.width,
                "height": dataset.height,
                "dtype": dataset.dtypes[0],
                "transform": [float(value) for value in list(dataset.transform)[:6]],
                "nodata": dataset.nodata,
            }
        metrics = _metrics(source)
        if source == "annual_nlcd":
            metrics.update(
                {"crs": "EPSG:5070", "observed_class_values": [22, 23, 24], **raster_profile}
            )
            metrics["resolution_m"] = [30.0, 30.0]
        else:
            metrics.update({"source_crs": "EPSG:4269", **raster_profile})
            metrics["dimensions"] = {
                "width": raster_profile["width"],
                "height": raster_profile["height"],
            }
            metrics["resolution_arc_seconds"] = [1 / 3, 1 / 3]
        # Reuse the normal catalog path with the retained bytes and promote only
        # after the same AOI-scoped validation metadata is present.
        repository = SQLiteSourceRepository(root)
        url = f"https://retained.example/{source}"
        acquisition = Acquisition(
            source_id=source,
            provider="retained official smoke artifact",
            release="retained-2026-09-25",
            source_url=url,
            acquired_at="2026-09-25T00:00:00+00:00",
            media_type="image/tiff",
            raw_path=str(artifact),
            size_bytes=artifact.stat().st_size,
            sha256=body_hash,
            terms_url="https://www.usgs.gov/",
        )
        run = repository.begin_run(
            source_id=source,
            requested_url=url,
            adapter_version="retained-smoke-test-1",
            project_id=project_id,
            aoi_id=str(aoi["aoi_id"]),
            aoi_revision=1,
        )
        repository.record_attempt(
            run["run_id"],
            status="acquired",
            requested_url=url,
            sha256=body_hash,
            byte_size=artifact.stat().st_size,
        )
        candidate = repository.record_candidate(
            run["run_id"],
            acquisition=acquisition,
            adapter_version="retained-smoke-test-1",
            status="validated",
            validation_status="validated",
            coverage_status="complete",
            observation_status="data_observed",
            validation={
                "validation_scope": "retained DC smoke",
                "metrics": metrics,
                "source_provenance": {
                    "aoi_id": str(aoi["aoi_id"]),
                    "aoi_revision": 1,
                    "aoi_geometry_sha256": aoi["geometry_sha256"],
                },
            },
        )
        repository.promote(
            candidate["candidate_id"],
            project_id=project_id,
            aoi_id=str(aoi["aoi_id"]),
            aoi_revision=1,
        )
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("annual_nlcd", "3dep"),
        screening_mode="active_aoi",
        require_aoi_scoped_active=True,
    )
    result = run_job(job["job_id"], root)
    assert {item["source_status"] for item in result["source_results"]} == {"active_aoi"}
