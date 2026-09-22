from __future__ import annotations

import hashlib
import json
from pathlib import Path

from shapely.geometry import Polygon, mapping

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.models import Acquisition
from environmental_screening_platform.workflow import (
    create_job,
    create_project,
    export_result,
    retry_job,
    run_job,
)


def _boundary(root: Path) -> None:
    path = root / "workspace" / "reference" / "approved_counties.geojson"
    geometry = Polygon([(-106, 39), (-103, 39), (-103, 42), (-106, 42), (-106, 39)])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "geometry": mapping(geometry), "properties": {}}],
                "union_metrics": {"feature_count": 1},
                "provenance": {"source": "fixture"},
            }
        )
    )


def _project(root: Path) -> tuple[str, dict[str, object]]:
    _boundary(root)
    aoi = root / "aoi.geojson"
    aoi.write_text(
        json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [[-105.5, 40], [-105.4, 40], [-105.4, 40.1], [-105.5, 40.1], [-105.5, 40]]
                ],
            }
        )
    )
    created = create_project("snapshot fixture", aoi, root)
    return str(created["project"]["project_id"]), created["aoi_revision"]


def _promote_source(
    root: Path, source_id: str, project_id: str, aoi: dict[str, object], body: bytes, release: str
) -> dict[str, object]:
    repository = SQLiteSourceRepository(root)
    artifact = root / "raw" / source_id / f"{release}.bin"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    acquisition = Acquisition(
        source_id=source_id,
        provider="fixture provider",
        release=release,
        source_url="https://provider.example/source",
        acquired_at="2026-09-22T12:00:00+00:00",
        media_type="application/octet-stream",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://provider.example/terms",
    )
    run = repository.begin_run(
        source_id=source_id,
        requested_url=acquisition.source_url,
        adapter_version="fixture-adapter-1",
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
        details={"release": release},
    )
    candidate = repository.record_candidate(
        run["run_id"],
        acquisition=acquisition,
        adapter_version="fixture-adapter-1",
        status="validated",
        validation_status="validated",
        coverage_status="complete",
        observation_status="data_observed",
        validation={
            "validation_scope": "deterministic fixture",
            "product_status": release,
            "metrics": {"fixture_count": 1},
            "warnings": [],
            "features": [],
            "quarantined_count": 0,
        },
    )
    repository.promote(candidate["candidate_id"])
    return candidate


def test_job_snapshots_capture_active_missing_padus_and_blocked_fema(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root)
    candidate = _promote_source(root, "annual_nlcd", project_id, aoi, b"old", "nlcd-1")

    job = create_job(
        project_id,
        root,
        str(aoi["aoi_id"]),
        source_ids=("annual_nlcd", "padus", "fema_nfhl"),
    )
    repository = SQLiteSourceRepository(root)
    snapshots = repository.get_job_snapshots(job["job_id"])
    by_source = {row["source_id"]: row for row in snapshots}
    assert by_source["annual_nlcd"]["version_id"] == candidate["version_id"]
    assert by_source["annual_nlcd"]["snapshot_status"] == "active"
    assert by_source["padus"]["snapshot_status"] == "quarantined"
    assert by_source["fema_nfhl"]["snapshot_status"] == "blocked"

    result = run_job(job["job_id"], root)
    assert result["source_results"][0]["source_version_id"] == candidate["version_id"]
    assert result["source_results"][1]["observation_status"] == "geometry_quarantined"
    assert result["source_results"][2]["observation_status"] == "unavailable"


def test_promotion_after_job_creation_does_not_change_snapshot_and_fresh_job_does(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root)
    first = _promote_source(root, "annual_nlcd", project_id, aoi, b"first", "nlcd-1")
    old_job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("annual_nlcd",))
    second = _promote_source(root, "annual_nlcd", project_id, aoi, b"second", "nlcd-2")

    old_result = run_job(old_job["job_id"], root)
    assert old_result["source_results"][0]["source_version_id"] == first["version_id"]
    fresh_job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("annual_nlcd",))
    fresh_result = run_job(fresh_job["job_id"], root)
    assert fresh_result["source_results"][0]["source_version_id"] == second["version_id"]


def test_retry_reuses_snapshot_and_missing_artifact_is_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root)
    candidate = _promote_source(root, "annual_nlcd", project_id, aoi, b"stable", "nlcd-1")
    job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("annual_nlcd",))
    revision_path = (
        root / "workspace" / "projects" / project_id / "aoi-revisions" / f"{aoi['aoi_id']}.json"
    )
    revision = revision_path.read_text()
    revision_path.unlink()
    try:
        try:
            run_job(job["job_id"], root)
        except FileNotFoundError:
            pass
    finally:
        revision_path.write_text(revision)
    retried = retry_job(job["job_id"], root)
    assert retried["source_snapshot_ids"] == job["source_snapshot_ids"]
    assert retried["source_results"][0]["source_version_id"] == candidate["version_id"]

    historical_job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("annual_nlcd",))
    artifact = Path(candidate["artifact_path"])
    artifact.unlink()
    historical = run_job(historical_job["job_id"], root)
    assert historical["source_results"][0]["snapshot_status"] == "unavailable"
    assert historical["source_results"][0]["source_version_id"] == candidate["version_id"]
    unavailable_job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("annual_nlcd",))
    unavailable = run_job(unavailable_job["job_id"], root)
    source = unavailable["source_results"][0]
    assert source["source_version_id"] == candidate["version_id"]
    assert source["snapshot_status"] == "unavailable"
    assert source["coverage_status"] == "unavailable"
    assert source["observation_status"] == "unavailable"


def test_snapshot_provenance_is_present_in_all_exports(tmp_path: Path) -> None:
    root = tmp_path / "external"
    project_id, aoi = _project(root)
    _promote_source(root, "annual_nlcd", project_id, aoi, b"export", "nlcd-1")
    job = create_job(project_id, root, str(aoi["aoi_id"]), source_ids=("annual_nlcd", "fema_nfhl"))
    run_job(job["job_id"], root)
    outputs = export_result(job["job_id"], root, tmp_path / "exports")
    payload = json.loads(outputs[0].read_text())
    assert payload["job_id"] == job["job_id"]
    assert len(payload["source_snapshot_ids"]) == 2
    csv_text = outputs[1].read_text()
    assert "source_snapshot_id" in csv_text
    geojson = json.loads(outputs[2].read_text())
    assert geojson["properties"]["source_snapshot_ids"] == payload["source_snapshot_ids"]
    assert {state["source_id"] for state in geojson["properties"]["source_states"]} == {
        "annual_nlcd",
        "fema_nfhl",
    }
