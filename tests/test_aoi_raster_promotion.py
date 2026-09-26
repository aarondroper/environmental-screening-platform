from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import Polygon, mapping

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.models import Acquisition
from environmental_screening_platform.workflow import create_job, create_project


def _project(root: Path, tmp_path: Path, *, offset: float = 0.0) -> tuple[str, dict[str, Any]]:
    geometry = Polygon(
        [
            (-75.0 + offset, 40.0),
            (-74.99 + offset, 40.0),
            (-74.99 + offset, 40.01),
            (-75.0 + offset, 40.01),
            (-75.0 + offset, 40.0),
        ]
    )
    aoi_path = tmp_path / f"aoi-{offset}.geojson"
    aoi_path.write_text(json.dumps(mapping(geometry)), encoding="utf-8")
    created = create_project("AOI promotion", aoi_path, root)
    return str(created["project"]["project_id"]), created["aoi_revision"]


def _metrics(source: str, *, nodata: int = 0, uncovered: float = 0.0) -> dict[str, Any]:
    common = {
        "coverage": {
            "covered_aoi_percentage": 100.0 - uncovered,
            "uncovered_aoi_percentage": uncovered,
            "uncovered_aoi_area_sqkm": uncovered,
        },
        "pixel_accounting": {
            "valid_pixel_count": 10,
            "nodata_pixel_count": nodata,
        },
    }
    if source == "annual_nlcd":
        return {
            **common,
            "crs": "EPSG:5070",
            "width": 10,
            "height": 10,
            "dtype": "uint8",
            "transform": [30.0, 0.0, 0.0, 0.0, -30.0, 0.0],
            "resolution_m": [30.0, 30.0],
            "nodata": 250,
            "observed_class_values": [21, 22],
        }
    return {
        **common,
        "source_crs": "EPSG:4269",
        "dimensions": {"width": 10, "height": 10},
        "dtype": "float32",
        "transform": [1 / 10800, 0.0, 0.0, 0.0, -1 / 10800, 0.0],
        "resolution_arc_seconds": [1 / 3, 1 / 3],
        "nodata": -999999.0,
        "elevation_m": {"min": 100.0, "mean": 110.0, "max": 120.0},
    }


def _candidate(
    repo: SQLiteSourceRepository,
    root: Path,
    project_id: str,
    aoi: dict[str, Any],
    source: str,
    *,
    body: bytes,
    release: str,
    validation_metrics: dict[str, Any] | None = None,
    validation_status: str = "validated",
    candidate_status: str = "validated",
    coverage_status: str = "complete",
    observation_status: str = "data_observed",
    geometry_hash: str | None = None,
) -> dict[str, Any]:
    artifact = root / "raw" / source / f"{release}.bin"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    acquisition = Acquisition(
        source_id=source,
        provider="fixture provider",
        release=release,
        source_url="https://provider.example/raster",
        acquired_at="2026-09-26T10:00:00+00:00",
        media_type="image/tiff",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://provider.example/terms",
    )
    run = repo.begin_run(
        source_id=source,
        requested_url=acquisition.source_url,
        adapter_version="aoi-promotion-test-1",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )
    repo.record_attempt(
        run["run_id"],
        status="acquired",
        requested_url=acquisition.source_url,
        actual_url=acquisition.source_url,
        retrieved_at=acquisition.acquired_at,
        sha256=digest,
        byte_size=len(body),
    )
    validation = {
        "validation_scope": f"Generic {source} AOI raster fixture",
        "product_status": "fixture",
        "metrics": validation_metrics or _metrics(source),
        "quarantined_count": 0,
        "warnings": [],
        "source_provenance": {
            "aoi_id": str(aoi["aoi_id"]),
            "aoi_revision": int(aoi["revision"]),
            "aoi_geometry_sha256": geometry_hash or str(aoi["geometry_sha256"]),
        },
    }
    return repo.record_candidate(
        run["run_id"],
        acquisition=acquisition,
        adapter_version="aoi-promotion-test-1",
        status=candidate_status,
        validation_status=validation_status,
        coverage_status=coverage_status,
        observation_status=observation_status,
        validation=validation,
    )


def test_generic_nlcd_promotion_is_aoi_scoped_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    repo = SQLiteSourceRepository(root)
    candidate = _candidate(repo, root, project_id, aoi, "annual_nlcd", body=b"nlcd", release="v1")

    decision = repo.promote(
        candidate["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )

    assert decision["decision"] == "promoted"
    assert decision["aoi_scope"]["aoi_geometry_sha256"] == aoi["geometry_sha256"]
    stored_decision = repo.promote(candidate["candidate_id"])
    assert stored_decision["aoi_scope"]["aoi_id"] == str(aoi["aoi_id"])
    active = repo.get_active(
        "annual_nlcd",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )
    assert active is not None
    assert active["candidate_id"] == candidate["candidate_id"]
    assert repo.get_active("annual_nlcd") is None
    assert repo.promote(candidate["candidate_id"])["idempotent"] is True

    job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("annual_nlcd",))
    snapshot = SQLiteSourceRepository(root).get_job_snapshots(job["job_id"])[0]
    assert snapshot["snapshot_status"] == "active"
    assert snapshot["version_id"] == candidate["version_id"]


def test_generic_3dep_promotion_uses_native_raster_gate(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    repo = SQLiteSourceRepository(root)
    candidate = _candidate(repo, root, project_id, aoi, "3dep", body=b"3dep", release="v1")

    decision = repo.promote(
        candidate["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )

    assert decision["decision"] == "promoted"
    assert (
        repo.get_active(
            "3dep",
            project_id=project_id,
            aoi_id=str(aoi["aoi_id"]),
            aoi_revision=int(aoi["revision"]),
        )["version_id"]
        == candidate["version_id"]
    )


@pytest.mark.parametrize("source", ["annual_nlcd", "3dep"])
def test_incomplete_or_nodata_candidate_stays_inactive(tmp_path: Path, source: str) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    repo = SQLiteSourceRepository(root)
    candidate = _candidate(
        repo,
        root,
        project_id,
        aoi,
        source,
        body=b"incomplete",
        release="bad",
        validation_metrics=_metrics(source, nodata=1, uncovered=1.0),
        validation_status="incomplete",
        candidate_status="incomplete",
        coverage_status="partial",
        observation_status="nodata",
    )

    decision = repo.promote(
        candidate["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )

    assert decision["decision"] == "rejected"
    assert "not validated" in decision["reason"]
    assert (
        repo.get_active(source, project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1)
        is None
    )


def test_wrong_native_raster_metadata_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    repo = SQLiteSourceRepository(root)
    metrics = _metrics("annual_nlcd")
    metrics["crs"] = "EPSG:3857"
    candidate = _candidate(
        repo,
        root,
        project_id,
        aoi,
        "annual_nlcd",
        body=b"wrong-crs",
        release="wrong-crs",
        validation_metrics=metrics,
    )

    decision = repo.promote(
        candidate["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=1,
    )

    assert decision["decision"] == "rejected"
    assert "CRS" in decision["reason"]


@pytest.mark.parametrize("source", ["annual_nlcd", "3dep"])
def test_missing_complete_coverage_metrics_are_rejected(tmp_path: Path, source: str) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    repo = SQLiteSourceRepository(root)
    metrics = _metrics(source)
    del metrics["coverage"]["covered_aoi_percentage"]
    candidate = _candidate(
        repo,
        root,
        project_id,
        aoi,
        source,
        body=b"missing-coverage",
        release="missing-coverage",
        validation_metrics=metrics,
    )

    decision = repo.promote(
        candidate["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=1,
    )

    assert decision["decision"] == "rejected"
    assert "complete AOI coverage" in decision["reason"]
    assert (
        repo.get_active(source, project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1)
        is None
    )


def test_checksum_aoi_mismatch_and_failed_replacement_preserve_prior_active(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    other_project, other_aoi = _project(root, tmp_path, offset=1.0)
    repo = SQLiteSourceRepository(root)
    first = _candidate(repo, root, project_id, aoi, "annual_nlcd", body=b"first", release="v1")
    repo.promote(
        first["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=1,
    )

    mismatch = _candidate(
        repo,
        root,
        project_id,
        aoi,
        "annual_nlcd",
        body=b"mismatch",
        release="v2",
        geometry_hash=str(other_aoi["geometry_sha256"]),
    )
    mismatch_decision = repo.promote(
        mismatch["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=1,
    )
    assert mismatch_decision["decision"] == "rejected"
    assert "geometry hash" in mismatch_decision["reason"]

    checksum = _candidate(
        repo, root, project_id, aoi, "annual_nlcd", body=b"checksum", release="v3"
    )
    Path(checksum["artifact_path"]).write_bytes(b"changed")
    checksum_decision = repo.promote(
        checksum["candidate_id"],
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=1,
    )
    assert checksum_decision["decision"] == "rejected"
    assert "checksum" in checksum_decision["reason"]

    active = repo.get_active(
        "annual_nlcd", project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1
    )
    assert active is not None and active["version_id"] == first["version_id"]
    assert (
        repo.get_active(
            "annual_nlcd", project_id=other_project, aoi_id=str(other_aoi["aoi_id"]), aoi_revision=1
        )
        is None
    )
    other_job = create_job(
        other_project, root, str(other_aoi["aoi_id"]), source_ids=("annual_nlcd",)
    )
    other_snapshot = repo.get_job_snapshots(other_job["job_id"])[0]
    assert other_snapshot["snapshot_status"] == "incomplete"
    assert other_snapshot["version_id"] is None


def test_generic_promotion_requires_exact_scope_and_does_not_use_other_aoi(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    repo = SQLiteSourceRepository(root)
    candidate = _candidate(repo, root, project_id, aoi, "3dep", body=b"scope", release="v1")

    missing_scope = repo.promote(candidate["candidate_id"])
    assert missing_scope["decision"] == "rejected"
    assert "AOI-scoped" in missing_scope["reason"]
    assert repo.get_active("3dep") is None
