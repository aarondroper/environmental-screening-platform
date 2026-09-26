from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from environmental_screening_platform.local_api import LocalScreeningBridge, _lineage_issue
from environmental_screening_platform.store import read_json
from environmental_screening_platform.workflow import create_job, create_project_from_geojson


class ImmediateExecutor:
    def submit(self, function: Any, *args: Any, **kwargs: Any) -> None:
        function(*args, **kwargs)


def _aoi() -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-77.04, 38.89],
                [-77.03, 38.89],
                [-77.03, 38.90],
                [-77.04, 38.90],
                [-77.04, 38.89],
            ]
        ],
    }


def _candidate() -> dict[str, Any]:
    return {
        "candidate_id": "candidate-nlcd",
        "version_id": "version-nlcd",
        "status": "validated",
        "artifact_path": "/external/nlcd.tif",
    }


def _result(geometry_hash: str) -> dict[str, Any]:
    return {
        "project_id": "set-by-test",
        "aoi_id": "set-by-test",
        "aoi_revision": 1,
        "aoi_geometry_sha256": geometry_hash,
        "source_results": [
            {
                "source_id": "annual_nlcd",
                "attempt_status": "validated",
                "source_status": "active_aoi",
                "source_snapshot_id": "snapshot-nlcd",
                "source_version_id": "version-nlcd",
                "candidate_id": "candidate-nlcd",
                "ingestion_run_id": "run-nlcd",
                "aoi_geometry_sha256": geometry_hash,
                "coverage_status": "complete",
                "observation_status": "data_observed",
                "metrics": {"valid_pixel_count": 4},
                "provenance": {
                    "aoi_geometry_sha256": geometry_hash,
                    "sha256": "checksum-nlcd",
                    "artifact_path": None,
                },
            }
        ],
    }


def test_successful_local_run_returns_exact_aoi_and_source_lineage(tmp_path: Path) -> None:
    def fake_run(job_id: str, data_root: Path, **_: Any) -> dict[str, Any]:
        from environmental_screening_platform.store import read_json

        job = read_json(data_root / "workspace" / "jobs" / job_id / "job.json")
        revision = read_json(
            data_root
            / "workspace"
            / "projects"
            / job["project_id"]
            / "aoi-revisions"
            / f"{job['aoi_id']}.json"
        )
        result = _result(revision["geometry_sha256"])
        result["project_id"] = job["project_id"]
        result["aoi_id"] = job["aoi_id"]
        return result

    bridge = LocalScreeningBridge(tmp_path, executor=ImmediateExecutor())

    def fake_snapshots(repository: Any, job_id: str) -> list[dict[str, Any]]:
        from environmental_screening_platform.store import read_json

        job = read_json(repository.data_root / "workspace" / "jobs" / job_id / "job.json")
        revision = read_json(
            repository.data_root
            / "workspace"
            / "projects"
            / job["project_id"]
            / "aoi-revisions"
            / f"{job['aoi_id']}.json"
        )
        return [
            {
                "source_id": "annual_nlcd",
                "snapshot_id": "snapshot-nlcd",
                "version_id": "version-nlcd",
                "candidate_id": "candidate-nlcd",
                "ingestion_run_id": "run-nlcd",
                "provenance": {
                    "sha256": "checksum-nlcd",
                    "aoi_geometry_sha256": revision["geometry_sha256"],
                },
            }
        ]

    with (
        patch(
            "environmental_screening_platform.local_api.ingest_nlcd_aoi",
            return_value={"candidate": _candidate()},
        ),
        patch(
            "environmental_screening_platform.local_api.SQLiteSourceRepository.promote",
            return_value={"decision": "promoted"},
        ),
        patch("environmental_screening_platform.local_api.bind_job_snapshots"),
        patch(
            "environmental_screening_platform.local_api.SQLiteSourceRepository.get_job_snapshots",
            new=fake_snapshots,
        ),
        patch("environmental_screening_platform.local_api.run_job", side_effect=fake_run),
    ):
        created = bridge.submit(project_name="DC test", geojson=_aoi())
        assert created["status"] == "succeeded"
        assert created["report"]["aoi_context"]["geometry_sha256"] == created["aoi_geometry_sha256"]
        assert created["report"]["sources"]["annual_nlcd"]["screening"]
        assert created["report"]["sources"]["3dep"]["status_only_reason"]


def test_failed_acquisition_can_retry_without_replacing_the_aoi(tmp_path: Path) -> None:
    attempts = 0

    def fake_ingest(*_: Any, **__: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("provider unavailable")
        return {"candidate": _candidate()}

    def fake_run(job_id: str, data_root: Path, **_: Any) -> dict[str, Any]:
        from environmental_screening_platform.store import read_json

        job = read_json(data_root / "workspace" / "jobs" / job_id / "job.json")
        revision = read_json(
            data_root
            / "workspace"
            / "projects"
            / job["project_id"]
            / "aoi-revisions"
            / f"{job['aoi_id']}.json"
        )
        result = _result(revision["geometry_sha256"])
        result.update(
            {
                "project_id": job["project_id"],
                "aoi_id": job["aoi_id"],
            }
        )
        return result

    bridge = LocalScreeningBridge(tmp_path, executor=ImmediateExecutor())

    def fake_snapshots(repository: Any, job_id: str) -> list[dict[str, Any]]:
        from environmental_screening_platform.store import read_json

        job = read_json(repository.data_root / "workspace" / "jobs" / job_id / "job.json")
        revision = read_json(
            repository.data_root
            / "workspace"
            / "projects"
            / job["project_id"]
            / "aoi-revisions"
            / f"{job['aoi_id']}.json"
        )
        return [
            {
                "source_id": "annual_nlcd",
                "snapshot_id": "snapshot-nlcd",
                "version_id": "version-nlcd",
                "candidate_id": "candidate-nlcd",
                "ingestion_run_id": "run-nlcd",
                "provenance": {
                    "sha256": "checksum-nlcd",
                    "aoi_geometry_sha256": revision["geometry_sha256"],
                },
            }
        ]

    with (
        patch(
            "environmental_screening_platform.local_api.ingest_nlcd_aoi",
            side_effect=fake_ingest,
        ),
        patch(
            "environmental_screening_platform.local_api.SQLiteSourceRepository.promote",
            return_value={"decision": "promoted"},
        ),
        patch("environmental_screening_platform.local_api.bind_job_snapshots"),
        patch(
            "environmental_screening_platform.local_api.SQLiteSourceRepository.get_job_snapshots",
            new=fake_snapshots,
        ),
        patch("environmental_screening_platform.local_api.run_job", side_effect=fake_run),
    ):
        first = bridge.submit(project_name="retry test", geojson=_aoi())
        assert first["status"] == "failed"
        retried = bridge.retry(first["job_id"])

    assert retried["status"] == "succeeded"
    assert retried["job"]["bridge"]["attempt"] == 2
    assert retried["report"]["screening_run"]["aoi_revision"] == 1


def test_stale_result_is_hidden_when_geometry_lineage_changes(tmp_path: Path) -> None:
    created = create_project_from_geojson("stale result", _aoi(), tmp_path)
    job = create_job(
        created["project"]["project_id"],
        tmp_path,
        created["aoi_revision"]["aoi_id"],
        source_ids=("annual_nlcd",),
        screening_mode="active_aoi",
        require_aoi_scoped_active=True,
        defer_source_snapshot=True,
    )
    revision = read_json(
        tmp_path
        / "workspace"
        / "projects"
        / created["project"]["project_id"]
        / "aoi-revisions"
        / f"{created['aoi_revision']['aoi_id']}.json"
    )
    result = _result(revision["geometry_sha256"])
    result.update(
        {
            "project_id": job["project_id"],
            "aoi_id": job["aoi_id"],
            "aoi_geometry_sha256": "stale-geometry-hash",
        }
    )
    assert _lineage_issue(tmp_path, job, result, result["source_results"][0], revision) == (
        "Stored result geometry hash does not match the immutable AOI revision"
    )
