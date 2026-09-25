from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import Polygon, mapping

from environmental_screening_platform import aoi_ingestion
from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.workflow import create_project


def _project(root: Path, tmp_path: Path) -> tuple[str, str]:
    aoi_path = tmp_path / "aoi.geojson"
    aoi_path.write_text(
        json.dumps(
            mapping(Polygon([(-75, 40), (-74.99, 40), (-74.99, 40.01), (-75, 40.01), (-75, 40)]))
        ),
        encoding="utf-8",
    )
    created = create_project("generic orchestration", aoi_path, root)
    return str(created["project"]["project_id"]), str(created["aoi_revision"]["aoi_id"])


def _candidate(source: str, candidate_id: str, *, status: str = "validated") -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "run_id": f"run-{candidate_id}",
        "status": status,
        "validation_status": "validated" if status == "validated" else "failed",
        "coverage_status": "complete" if status == "validated" else "unavailable",
        "observation_status": "data_observed" if status == "validated" else "unavailable",
        "artifact_path": f"/external/raw/{source}/{candidate_id}.bin"
        if status == "validated"
        else None,
        "byte_size": 10 if status == "validated" else None,
        "sha256": "a" * 64 if status == "validated" else None,
        "promotion_status": "not_promoted",
        "validation": {
            "source_provenance": {
                "aoi_geometry_sha256": "fixture-hash",
                "request_parameters": {"source": source},
            },
            "warnings": [],
        },
        "error": {"message": "checksum mismatch"} if status == "failed" else None,
    }


def _outcome(source: str, candidate_id: str, *, status: str = "validated") -> dict[str, Any]:
    candidate = _candidate(source, candidate_id, status=status)
    if source == "nlcd":
        return {"candidate": candidate, "run": {"run_id": candidate["run_id"]}}
    key = "tiles" if source == "3dep" else "packages"
    item = {"candidate": candidate}
    return {key: [item], "plan_id": f"{source}-plan", "run": {"run_id": candidate["run_id"]}}


def test_dry_run_is_deterministic_and_does_not_call_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "external"
    project_id, aoi_id = _project(root, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        aoi_ingestion, "ingest_nlcd_aoi", lambda *args, **kwargs: calls.append("nlcd")
    )
    monkeypatch.setattr(aoi_ingestion, "ingest_3dep", lambda *args, **kwargs: calls.append("3dep"))

    first = aoi_ingestion.ingest_aoi(
        root, project_id=project_id, aoi_id=aoi_id, sources=["3dep", "nlcd"], dry_run=True
    )
    second = aoi_ingestion.ingest_aoi(
        root, project_id=project_id, aoi_id=aoi_id, sources=["nlcd", "3dep"], dry_run=True
    )

    assert calls == []
    assert first["status"] == second["status"] == "dry_run"
    assert first["plan_id"] == second["plan_id"]
    assert first["plan_size_bytes"] > 0
    assert len(first["plan_sha256"]) == 64
    assert first["aoi_geometry_sha256"] == second["aoi_geometry_sha256"]
    assert (
        SQLiteSourceRepository(root).get_aoi_ingestion_run(first["parent_run_id"])["status"]
        == "dry_run"
    )


def test_all_sources_are_independent_and_preserve_aoi_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "external"
    project_id, aoi_id = _project(root, tmp_path)
    monkeypatch.setattr(
        aoi_ingestion, "ingest_nlcd_aoi", lambda *args, **kwargs: _outcome("nlcd", "n1")
    )
    monkeypatch.setattr(
        aoi_ingestion, "ingest_3dep", lambda *args, **kwargs: _outcome("3dep", "d1")
    )
    monkeypatch.setattr(
        aoi_ingestion, "ingest_ssurgo_aoi", lambda *args, **kwargs: _outcome("ssurgo", "s1")
    )

    result = aoi_ingestion.ingest_aoi(
        root,
        project_id=project_id,
        aoi_id=aoi_id,
        sources=["nlcd", "3dep", "ssurgo"],
        per_source_limits={"nlcd": {"max_bytes": 100}},
        max_total_bytes=1_000,
    )

    assert result["status"] == "completed"
    assert result["bytes_downloaded"] == 30
    assert result["sources"]["nlcd"]["candidate_ids"] == ["n1"]
    assert result["sources"]["3dep"]["candidate_ids"] == ["d1"]
    assert result["sources"]["ssurgo"]["candidate_ids"] == ["s1"]
    assert result["sources"]["nlcd"]["availability_status"] == "available"
    assert len(result["aoi_geometry_sha256"]) == 64
    assert result["sources"]["nlcd"]["attempts"][0]["candidate_ids"] == ["n1"]


def test_partial_failure_does_not_erase_success_and_checksum_error_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "external"
    project_id, aoi_id = _project(root, tmp_path)
    monkeypatch.setattr(
        aoi_ingestion, "ingest_nlcd_aoi", lambda *args, **kwargs: _outcome("nlcd", "n1")
    )
    monkeypatch.setattr(
        aoi_ingestion,
        "ingest_3dep",
        lambda *args, **kwargs: _outcome("3dep", "d1", status="failed"),
    )

    result = aoi_ingestion.ingest_aoi(
        root, project_id=project_id, aoi_id=aoi_id, sources=["nlcd", "3dep"]
    )

    assert result["status"] == "partial"
    assert result["sources"]["nlcd"]["status"] == "completed"
    assert result["sources"]["3dep"]["status"] == "failed"
    assert "checksum mismatch" in json.dumps(result["sources"]["3dep"])


def test_retry_only_retries_failed_source_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "external"
    project_id, aoi_id = _project(root, tmp_path)
    calls = 0

    def failed_then_success(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _outcome("nlcd", f"n{calls}", status="failed" if calls == 1 else "validated")

    monkeypatch.setattr(aoi_ingestion, "ingest_nlcd_aoi", failed_then_success)
    first = aoi_ingestion.ingest_aoi(root, project_id=project_id, aoi_id=aoi_id, sources=["nlcd"])
    retried = aoi_ingestion.ingest_aoi(
        root,
        project_id=project_id,
        aoi_id=aoi_id,
        sources=["nlcd"],
        retry_parent_run_id=first["parent_run_id"],
        retry_sources=["nlcd"],
    )
    repeated = aoi_ingestion.ingest_aoi(
        root,
        project_id=project_id,
        aoi_id=aoi_id,
        sources=["nlcd"],
        retry_parent_run_id=first["parent_run_id"],
        retry_sources=["nlcd"],
    )

    assert calls == 2
    assert retried["status"] == "completed"
    assert retried["sources"]["nlcd"]["candidate_ids"] == ["n2"]
    assert len(retried["sources"]["nlcd"]["attempts"]) == 2
    assert retried["sources"]["nlcd"]["attempts"][0]["artifacts"][0]["sha256"] is None
    assert repeated == retried
