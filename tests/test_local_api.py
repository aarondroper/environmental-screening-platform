from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_bounds
from shapely.geometry import shape
from shapely.ops import transform

from environmental_screening_platform.local_api import (
    LocalScreeningBridge,
    _generate_nlcd_browser_preview,
    _lineage_issue,
    _set_phase,
)
from environmental_screening_platform.store import read_json, write_json
from environmental_screening_platform.workflow import (
    create_job,
    create_project_from_geojson,
    run_job,
    transition_job,
)


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


def _colorado_aoi() -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-105.10, 40.00],
                [-105.09, 40.00],
                [-105.09, 40.01],
                [-105.10, 40.01],
                [-105.10, 40.00],
            ]
        ],
    }


def _write_nlcd_artifact(path: Path, geometry: dict[str, Any]) -> str:
    aoi = shape(geometry)
    to_source = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    minx, miny, maxx, maxy = transform(to_source, aoi).bounds
    bounds = (minx - 1_000, miny - 1_000, maxx + 1_000, maxy + 1_000)
    values = np.full((8, 8), 24, dtype="uint8")
    values[0, 0] = 250
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=8,
        height=8,
        count=1,
        dtype="uint8",
        crs="EPSG:5070",
        transform=from_bounds(*bounds, 8, 8),
        nodata=250,
    ) as dataset:
        dataset.write(values, 1)
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_successful_job_generates_an_aoi_specific_nlcd_preview(tmp_path: Path) -> None:
    created = create_project_from_geojson("Generic preview test", _aoi(), tmp_path)
    project = created["project"]
    revision = created["aoi_revision"]
    job = create_job(
        project["project_id"],
        tmp_path,
        revision["aoi_id"],
        source_ids=("annual_nlcd",),
        screening_mode="active_aoi",
        defer_source_snapshot=True,
    )
    source = tmp_path / "source.tif"
    checksum = _write_nlcd_artifact(source, revision["geometry"])
    result = {
        "source_results": [
            {
                "source_id": "annual_nlcd",
                "source_snapshot_id": "snapshot-generic",
                "source_version_id": "version-generic",
                "candidate_id": "candidate-generic",
                "ingestion_run_id": "run-generic",
                "metrics": {"source_year": 2025},
                "provenance": {
                    "artifact_path": str(source),
                    "sha256": checksum,
                    "source_url": "https://example.invalid/nlcd",
                    "provider_release": "Annual NLCD Collection 1.2",
                },
            }
        ]
    }
    preview = _generate_nlcd_browser_preview(tmp_path, job, result)
    metadata = json.loads(
        (
            tmp_path
            / "workspace"
            / "jobs"
            / job["job_id"]
            / "browser-previews"
            / "annual-nlcd-preview.json"
        ).read_text()
    )
    assert preview["status"] == "available"
    assert preview["source_sha256"] == checksum
    assert preview["aoi_revision"] == revision["revision"]
    assert preview["aoi_geometry_sha256"] == revision["geometry_sha256"]
    assert metadata["source"]["source_snapshot_id"] == "snapshot-generic"
    assert metadata["source"]["source_version_id"] == "version-generic"
    assert metadata["source"]["sha256"] == checksum
    assert metadata["aoi"]["geometry_sha256"] == revision["geometry_sha256"]


def _complete_fake_job(data_root: Path, job_id: str) -> None:
    path = data_root / "workspace" / "jobs" / job_id / "job.json"
    job = read_json(path)
    job["status"] = transition_job(job["status"], "processing")
    job["status"] = transition_job(job["status"], "completed")
    write_json(path, job)


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
        _complete_fake_job(data_root, job_id)
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
        created = bridge.submit(project_name="Colorado test", geojson=_colorado_aoi())
        assert created["status"] == "succeeded"
        assert created["job"]["status"] == "completed"
        assert created["report"]["aoi_context"]["geometry_sha256"] == created["aoi_geometry_sha256"]
        assert created["report"]["sources"]["annual_nlcd"]["screening"]
        assert created["report"]["sources"]["3dep"]["status_only_reason"]
        assert created["report"]["browser_previews"] == {}
        assert created["report"]["screening_run"]["aoi_revision"] == 1
        assert created["report"]["result"]["aoi_revision"] == 1
        source_result = created["report"]["result"]["source_results"][0]
        assert source_result["aoi_geometry_sha256"] == created["aoi_geometry_sha256"]
        assert source_result["source_snapshot_id"] == "snapshot-nlcd"
        assert source_result["source_version_id"] == "version-nlcd"
        assert source_result["candidate_id"] == "candidate-nlcd"
        assert source_result["ingestion_run_id"] == "run-nlcd"
        assert source_result["provenance"]["sha256"] == "checksum-nlcd"
        assert "-77.04" not in json.dumps(created["report"], sort_keys=True)


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
        _complete_fake_job(data_root, job_id)
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
        assert first["job"]["status"] == "failed"
        retried = bridge.retry(first["job_id"])

    assert retried["status"] == "succeeded"
    assert retried["job"]["status"] == "completed"
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


def test_bridge_phases_do_not_duplicate_workflow_processing_transition(tmp_path: Path) -> None:
    created = create_project_from_geojson("generic lifecycle", _colorado_aoi(), tmp_path)
    job = create_job(
        created["project"]["project_id"],
        tmp_path,
        created["aoi_revision"]["aoi_id"],
        source_ids=("annual_nlcd",),
        screening_mode="active_aoi",
        require_aoi_scoped_active=True,
    )

    _set_phase(tmp_path, job["job_id"], "screening")
    assert read_json(tmp_path / "workspace" / "jobs" / job["job_id"] / "job.json")["status"] == (
        "queued"
    )
    result = run_job(job["job_id"], tmp_path)

    assert result["job_status"] == "completed"
    assert read_json(tmp_path / "workspace" / "jobs" / job["job_id"] / "job.json")["status"] == (
        "completed"
    )
    with pytest.raises(ValueError, match="processing -> processing"):
        transition_job("processing", "processing")
