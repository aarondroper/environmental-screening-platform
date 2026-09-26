from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon
from test_active_screening import _project, _promote, _raster_bytes

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.cli import main
from environmental_screening_platform.report import build_aoi_run_report, render_aoi_run_summary
from environmental_screening_platform.store import write_json
from environmental_screening_platform.workflow import create_job, run_job


def _parent_run(
    root: Path,
    project_id: str,
    aoi: dict[str, object],
    source_ids: list[str],
    source_statuses: dict[str, str],
) -> str:
    plan_path = root / "aoi-ingestion" / "plans" / "report-plan.json"
    write_json(
        plan_path,
        {
            "plan_version": 1,
            "project_id": project_id,
            "aoi_id": aoi["aoi_id"],
            "aoi_revision": aoi["revision"],
            "aoi_geometry_sha256": aoi["geometry_sha256"],
            "sources": source_ids,
        },
    )
    plan_body = plan_path.read_bytes()
    parent_id = "parent-report-run"
    source_summary = {
        source_id: {
            "source": source_id,
            "source_id": source_id,
            "status": source_statuses[source_id],
            "planned_artifact_count": 1,
            "acquired_artifact_count": 1 if source_statuses[source_id] == "completed" else 0,
            "bytes_downloaded": 128 if source_statuses[source_id] == "completed" else 0,
            "warnings": [],
            "attempts": [],
        }
        for source_id in source_ids
    }
    summary = {
        "parent_run_id": parent_id,
        "plan_id": "aoi-ingestion:test-report-plan",
        "plan_path": str(plan_path),
        "plan_size_bytes": len(plan_body),
        "plan_sha256": hashlib.sha256(plan_body).hexdigest(),
        "project_id": project_id,
        "aoi_id": aoi["aoi_id"],
        "aoi_revision": aoi["revision"],
        "aoi_geometry_sha256": aoi["geometry_sha256"],
        "sources": source_summary,
    }
    repository = SQLiteSourceRepository(root)
    repository.create_aoi_ingestion_run(
        parent_run_id=parent_id,
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
        aoi_geometry_sha256=str(aoi["geometry_sha256"]),
        source_ids=source_ids,
        limits={"max_total_bytes": 1000},
        plan_id=summary["plan_id"],
        plan_path=str(plan_path),
        status="running",
        summary=summary,
    )
    final_status = (
        "completed"
        if all(value == "completed" for value in source_statuses.values())
        else "partial"
    )
    repository.update_aoi_ingestion_run(parent_id, status=final_status, summary=summary)
    return parent_id


def _failed_retry_runs(root: Path, project_id: str, aoi: dict[str, object]) -> tuple[str, str]:
    repository = SQLiteSourceRepository(root)
    first = repository.begin_run(
        source_id="3dep",
        requested_url="https://provider.example/3dep",
        adapter_version="report-test",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
    )
    repository.record_attempt(
        first["run_id"],
        status="failed",
        requested_url=first["requested_url"],
        error="provider timeout",
    )
    repository.finish_run(first["run_id"], "failed", "provider timeout")
    second = repository.begin_run(
        source_id="3dep",
        requested_url="https://provider.example/3dep",
        adapter_version="report-test",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=int(aoi["revision"]),
        retry_of=first["run_id"],
    )
    repository.record_attempt(
        second["run_id"],
        status="failed",
        requested_url=second["requested_url"],
        error="provider still unavailable",
    )
    repository.finish_run(second["run_id"], "incomplete", "provider still unavailable")
    return str(first["run_id"]), str(second["run_id"])


def test_report_aoi_run_success_is_deterministic_and_preserves_active_screening(
    tmp_path: Path, capsys: object
) -> None:
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
    nlcd = _promote(
        root,
        project_id,
        aoi,
        "annual_nlcd",
        _raster_bytes(geometry, "annual_nlcd", np.array([[21, 22], [23, 24]], dtype="uint8")),
        "report-nlcd",
    )
    dep = _promote(
        root,
        project_id,
        aoi,
        "3dep",
        _raster_bytes(geometry, "3dep", np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32")),
        "report-3dep",
    )
    _parent_run(
        root,
        project_id,
        aoi,
        ["annual_nlcd", "3dep"],
        {"annual_nlcd": "completed", "3dep": "completed"},
    )
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("annual_nlcd", "3dep"),
        screening_mode="active_aoi",
    )
    run_job(job["job_id"], root)

    report = build_aoi_run_report(
        root, project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1
    )
    assert report["aoi"]["geometry_sha256"] == aoi["geometry_sha256"]
    assert report["aoi"]["area"]["value_sqkm"] == aoi["spatial_validation"]["area_sqkm"]
    assert report["parent_ingestion_runs"][0]["plan_record"]["integrity_matches"] is True
    assert report["sources"]["annual_nlcd"]["acquisition_summary"] == {
        "planned_artifact_counts": [1],
        "acquired_artifact_counts": [1],
        "bytes_downloaded": [128],
    }
    assert report["active_aoi_versions"]
    assert {item["version_id"] for item in report["active_aoi_versions"]} == {
        nlcd["version_id"],
        dep["version_id"],
    }
    assert len(report["screening_jobs"]) == 1
    for source_id in ("annual_nlcd", "3dep"):
        lifecycle = report["sources"][source_id]["lifecycle"]
        assert lifecycle["stopped_at"] == "screened"
        assert lifecycle["promoted"]["observed"] is True
        assert lifecycle["screened"]["observed"] is True
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    assert encoded == json.dumps(
        build_aoi_run_report(
            root, project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    assert (
        main(
            [
                "--data-dir",
                str(root),
                "report-aoi-run",
                "--project-id",
                project_id,
                "--aoi-id",
                str(aoi["aoi_id"]),
                "--aoi-revision",
                "1",
            ]
        )
        == 0
    )
    cli_report = json.loads(capsys.readouterr().out)  # type: ignore[union-attr]
    assert (
        cli_report["sources"]["annual_nlcd"]["screening"][0]["result"][0]["active_version_id"]
        == nlcd["version_id"]
    )


def test_report_aoi_run_preserves_partial_failure_and_retry_history(tmp_path: Path) -> None:
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
    _promote(
        root,
        project_id,
        aoi,
        "annual_nlcd",
        _raster_bytes(geometry, "annual_nlcd", np.ones((2, 2), dtype="uint8")),
        "partial-nlcd",
    )
    first_run, retry_run = _failed_retry_runs(root, project_id, aoi)
    _parent_run(
        root,
        project_id,
        aoi,
        ["annual_nlcd", "3dep"],
        {"annual_nlcd": "completed", "3dep": "partial"},
    )
    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("annual_nlcd", "3dep"),
        screening_mode="active_aoi",
    )
    result = run_job(job["job_id"], root)
    report = build_aoi_run_report(
        root, project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1
    )
    dep_runs = report["sources"]["3dep"]["ingestion_runs"]
    assert {run["run_id"] for run in dep_runs} == {first_run, retry_run}
    retry_record = next(run for run in dep_runs if run["run_id"] == retry_run)
    assert retry_record["retry_of"] == first_run
    assert report["sources"]["3dep"]["lifecycle"]["incomplete"]
    dep_result = next(item for item in result["source_results"] if item["source_id"] == "3dep")
    assert dep_result["snapshot_status"] == "unknown"
    assert dep_result["observation_status"] == "incomplete_source"
    assert dep_result["aoi_geometry_sha256"] == aoi["geometry_sha256"]
    assert report["sources"]["annual_nlcd"]["lifecycle"]["promoted"]["observed"] is True


def test_report_aoi_run_preserves_rejected_incomplete_ssurgo(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    repository = SQLiteSourceRepository(root)
    run = repository.begin_run(
        source_id="ssurgo",
        requested_url="https://provider.example/ssurgo",
        adapter_version="report-test",
        project_id=project_id,
        aoi_id=str(aoi["aoi_id"]),
        aoi_revision=1,
    )
    candidate = repository.record_candidate(
        run["run_id"],
        acquisition=None,
        adapter_version="report-test",
        status="incomplete",
        validation_status="conditionally_validated",
        coverage_status="partial",
        observation_status="incomplete_source",
        validation={"warnings": ["Regional coverage is incomplete."]},
        error="Regional residual remains unknown",
    )
    rejection = repository.promote(candidate["candidate_id"])
    assert rejection["decision"] == "rejected"
    _parent_run(root, project_id, aoi, ["ssurgo"], {"ssurgo": "incomplete"})
    report = build_aoi_run_report(
        root, project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1
    )
    source = report["sources"]["ssurgo"]
    assert source["candidates"][0]["status"] == "incomplete"
    assert source["promotion_decisions"][0]["decision"] == "rejected"
    assert source["lifecycle"]["stopped_at"] == "rejected"
    assert source["lifecycle"]["rejected"][0]["reason"] == rejection["reason"]
    assert "Regional coverage is incomplete." in source["candidates"][0]["validation"]["warnings"]


def test_report_is_read_only_when_catalog_is_absent(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root, tmp_path)
    report = build_aoi_run_report(
        root, project_id=project_id, aoi_id=str(aoi["aoi_id"]), aoi_revision=1
    )
    assert not (root / "catalog" / "sources.sqlite3").exists()
    assert report["parent_ingestion_runs"] == []
    assert report["screening_jobs"] == []
    assert "Source lifecycle:" in render_aoi_run_summary(report)
