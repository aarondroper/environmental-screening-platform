"""Read-only operational reports over the existing AOI lifecycle records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .catalog import SQLiteSourceRepository
from .store import read_json


def _project_paths(data_root: Path, project_id: str, aoi_id: str) -> tuple[Path, Path]:
    project_dir = data_root / "workspace" / "projects" / project_id
    return project_dir / "project.json", project_dir / "aoi-revisions" / f"{aoi_id}.json"


def _load_aoi(data_root: Path, project_id: str, aoi_id: str, aoi_revision: int) -> dict[str, Any]:
    project_path, revision_path = _project_paths(data_root, project_id, aoi_id)
    project = read_json(project_path)
    revision = read_json(revision_path)
    if project.get("project_id") != project_id:
        raise ValueError("Requested project identifier does not match the persisted project")
    if revision.get("project_id") != project_id or revision.get("aoi_id") != aoi_id:
        raise ValueError("Requested AOI revision does not belong to the persisted project/AOI")
    if int(revision.get("revision", -1)) != aoi_revision:
        raise ValueError("Requested AOI revision number does not match the persisted revision")
    return {"project": project, "revision": revision}


def _plan_record(path_value: str, expected_sha256: str, expected_size: int) -> dict[str, Any]:
    path = Path(path_value)
    record: dict[str, Any] = {
        "path": str(path),
        "expected_sha256": expected_sha256,
        "expected_size_bytes": expected_size,
        "exists": path.exists(),
        "observed_sha256": None,
        "observed_size_bytes": None,
        "integrity_matches": False,
        "plan": None,
        "read_error": None,
    }
    if not path.exists():
        record["read_error"] = "Deterministic plan file is unavailable"
        return record
    try:
        body = path.read_bytes()
        record["observed_size_bytes"] = len(body)
        record["observed_sha256"] = hashlib.sha256(body).hexdigest()
        record["integrity_matches"] = (
            record["observed_sha256"] == expected_sha256
            and record["observed_size_bytes"] == expected_size
        )
        record["plan"] = json.loads(body)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        record["read_error"] = f"{type(exc).__name__}: {exc}"
    return record


def _read_screening_jobs(
    data_root: Path,
    *,
    project_id: str,
    aoi_id: str,
    aoi_revision: int,
    repository: SQLiteSourceRepository | None,
) -> list[dict[str, Any]]:
    jobs_dir = data_root / "workspace" / "jobs"
    if not jobs_dir.exists():
        return []
    reports: list[dict[str, Any]] = []
    for job_path in sorted(jobs_dir.glob("*/job.json")):
        try:
            job = read_json(job_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            reports.append(
                {
                    "job_path": str(job_path),
                    "read_error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if (
            job.get("project_id") != project_id
            or job.get("aoi_id") != aoi_id
            or int(job.get("aoi_revision", -1)) != aoi_revision
        ):
            continue
        job_dir = job_path.parent
        result_path = job_dir / "result.json"
        attempt_results: list[dict[str, Any]] = []
        for attempt_path in sorted(job_dir.glob("attempt-*.result.json")):
            try:
                attempt_results.append(
                    {"path": str(attempt_path), "result": read_json(attempt_path)}
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                attempt_results.append(
                    {"path": str(attempt_path), "read_error": f"{type(exc).__name__}: {exc}"}
                )
        result: dict[str, Any] | None = None
        result_error: str | None = None
        if result_path.exists():
            try:
                result = read_json(result_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                result_error = f"{type(exc).__name__}: {exc}"
        snapshots = repository.get_job_snapshots(str(job["job_id"])) if repository else []
        reports.append(
            {
                "job_path": str(job_path),
                "job": job,
                "source_snapshots": snapshots,
                "result_path": str(result_path) if result_path.exists() else None,
                "result": result,
                "result_read_error": result_error,
                "attempt_results": attempt_results,
            }
        )
    return reports


def _run_record(repository: SQLiteSourceRepository, run: dict[str, Any]) -> dict[str, Any]:
    result = dict(run)
    result["acquisition_attempts"] = repository.list_attempts(str(run["run_id"]))
    return result


def _source_ids(
    parent_runs: list[dict[str, Any]],
    child_runs: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> list[str]:
    values: set[str] = set()
    for parent in parent_runs:
        values.update(str(item) for item in parent.get("source_ids", []))
    values.update(str(item["source_id"]) for item in child_runs)
    values.update(str(item["source_id"]) for item in candidates)
    for job in jobs:
        for snapshot in job.get("source_snapshots", []):
            values.add(str(snapshot["source_id"]))
    return sorted(values)


def _state_values(records: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(record[key]) for record in records if record.get(key) is not None})


def _source_lifecycle(
    source_id: str,
    *,
    parent_summaries: list[dict[str, Any]],
    child_runs: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    versions: list[dict[str, Any]],
    promotions: list[dict[str, Any]],
    active_versions: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    source_candidates = [item for item in candidates if item["source_id"] == source_id]
    source_runs = [item for item in child_runs if item["source_id"] == source_id]
    source_versions = [item for item in versions if item["source_id"] == source_id]
    source_promotions = [item for item in promotions if item["source_id"] == source_id]
    source_active = [item for item in active_versions if item["source_id"] == source_id]
    source_screening: list[dict[str, Any]] = []
    for job in jobs:
        for snapshot in job.get("source_snapshots", []):
            if snapshot.get("source_id") != source_id:
                continue
            source_screening.append(
                {
                    "job_id": job.get("job", {}).get("job_id"),
                    "job_status": job.get("job", {}).get("status"),
                    "snapshot": snapshot,
                    "result": next(
                        (
                            item
                            for item in (job.get("result") or {}).get("source_results", [])
                            if item.get("source_id") == source_id
                        ),
                        None,
                    ),
                }
            )
    parent_sources = [
        summary for summary in parent_summaries if summary.get("source_id") == source_id
    ]
    parent_failed = [
        {
            "parent_run_id": summary.get("parent_run_id"),
            "status": summary.get("status"),
            "reason": summary.get("warnings", []),
        }
        for summary in parent_sources
        if summary.get("status") in {"failed", "partial", "rejected"}
    ]
    acquired_attempts = [
        attempt
        for run in source_runs
        for attempt in run.get("acquisition_attempts", [])
        if attempt.get("status") == "acquired"
    ]
    validated_candidates = [
        item
        for item in source_candidates
        if item.get("status") == "validated" and item.get("validation_status") == "validated"
    ]
    failed = (
        [
            {
                "candidate_id": item.get("candidate_id"),
                "run_id": item.get("run_id"),
                "status": item.get("status"),
                "reason": item.get("error"),
            }
            for item in source_candidates
            if item.get("status") == "failed"
        ]
        + [
            {
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "reason": run.get("error"),
            }
            for run in source_runs
            if run.get("status") == "failed"
        ]
        + parent_failed
    )
    failed.extend(
        {
            "job_id": item["job_id"],
            "status": item["job_status"],
            "reason": item["result"].get("reason") if item["result"] else None,
        }
        for item in source_screening
        if item.get("job_status") == "failed"
    )
    incomplete = [
        {
            "candidate_id": item.get("candidate_id"),
            "run_id": item.get("run_id"),
            "status": item.get("status"),
            "coverage_status": item.get("coverage_status"),
            "observation_status": item.get("observation_status"),
            "reason": item.get("error"),
        }
        for item in source_candidates
        if item.get("status") == "incomplete"
        or item.get("coverage_status") not in {None, "complete"}
        or item.get("observation_status")
        in {
            "unavailable",
            "incomplete_source",
            "not_assessed",
            "pending_data",
            "nodata",
            "not_covered",
        }
    ]
    incomplete.extend(
        {
            "parent_run_id": summary.get("parent_run_id"),
            "status": summary.get("status"),
            "reason": summary.get("warnings", []),
        }
        for summary in parent_sources
        if summary.get("status") == "incomplete"
    )
    unavailable = [
        {
            "job_id": item["job_id"],
            "snapshot_id": item["snapshot"].get("snapshot_id"),
            "reason": (item["result"] or {}).get("reason") or item["snapshot"].get("reason"),
        }
        for item in source_screening
        if item["snapshot"].get("snapshot_status") == "unavailable"
        or (item["result"] or {}).get("observation_status") == "unavailable"
    ]
    unavailable.extend(
        {
            "parent_run_id": summary.get("parent_run_id"),
            "reason": summary.get("warnings", []),
        }
        for summary in parent_sources
        if summary.get("availability_status") == "unavailable"
    )
    screening_incomplete = [
        {
            "job_id": item["job_id"],
            "snapshot_id": item["snapshot"].get("snapshot_id"),
            "snapshot_status": item["snapshot"].get("snapshot_status"),
            "observation_status": (item["result"] or {}).get("observation_status")
            or item["snapshot"].get("observation_status"),
            "reason": (item["result"] or {}).get("reason") or item["snapshot"].get("reason"),
        }
        for item in source_screening
        if item["snapshot"].get("snapshot_status") == "incomplete"
        or (item["result"] or {}).get("observation_status")
        in {"incomplete_source", "nodata", "not_covered"}
    ]
    unknown = [
        {
            "job_id": item["job_id"],
            "snapshot_id": item["snapshot"].get("snapshot_id"),
            "snapshot_status": item["snapshot"].get("snapshot_status"),
            "coverage_status": (item["result"] or {}).get("coverage_status")
            or item["snapshot"].get("coverage_status"),
            "reason": (item["result"] or {}).get("reason") or item["snapshot"].get("reason"),
        }
        for item in source_screening
        if item["snapshot"].get("snapshot_status") == "unknown"
        or (item["result"] or {}).get("coverage_status") in {"unknown", "partial"}
    ]
    quarantined = [
        {
            "job_id": item["job_id"],
            "snapshot_id": item["snapshot"].get("snapshot_id"),
            "reason": (item["result"] or {}).get("reason") or item["snapshot"].get("reason"),
        }
        for item in source_screening
        if item["snapshot"].get("snapshot_status") == "quarantined"
        or (item["result"] or {}).get("observation_status") == "geometry_quarantined"
    ]
    blocked = [
        {
            "job_id": item["job_id"],
            "snapshot_id": item["snapshot"].get("snapshot_id"),
            "reason": (item["result"] or {}).get("reason") or item["snapshot"].get("reason"),
        }
        for item in source_screening
        if item["snapshot"].get("snapshot_status") == "blocked"
    ]
    rejected = [
        {
            "candidate_id": item.get("candidate_id"),
            "decision_id": item.get("decision_id"),
            "reason": item.get("reason"),
        }
        for item in source_promotions
        if item.get("decision") == "rejected"
    ]
    rejected.extend(
        {
            "parent_run_id": summary.get("parent_run_id"),
            "reason": summary.get("warnings", []),
        }
        for summary in parent_sources
        if summary.get("status") == "rejected"
    )
    if source_screening:
        stopped_at = "screened"
    elif source_active:
        stopped_at = "promoted"
    elif rejected:
        stopped_at = "rejected"
    elif failed:
        stopped_at = "failed"
    elif incomplete:
        stopped_at = "incomplete"
    elif validated_candidates:
        stopped_at = "validated"
    elif acquired_attempts:
        stopped_at = "acquired"
    elif parent_sources or source_runs or source_candidates:
        stopped_at = "planned"
    else:
        stopped_at = "not_started"
    return {
        "source_id": source_id,
        "stopped_at": stopped_at,
        "acquired": {
            "observed": bool(
                acquired_attempts or any(item.get("artifact_path") for item in source_candidates)
            ),
            "attempt_count": len(acquired_attempts),
            "artifact_count": sum(1 for item in source_candidates if item.get("artifact_path")),
        },
        "validated": {
            "observed": bool(validated_candidates),
            "candidate_ids": [item["candidate_id"] for item in validated_candidates],
        },
        "promoted": {
            "observed": bool(
                source_active
                or any(item.get("decision") == "promoted" for item in source_promotions)
            ),
            "active_version_ids": [item["version_id"] for item in source_active],
            "decision_ids": [
                item["decision_id"]
                for item in source_promotions
                if item.get("decision") == "promoted"
            ],
        },
        "screened": {
            "observed": bool(source_screening),
            "job_ids": [item["job_id"] for item in source_screening],
            "snapshot_ids": [item["snapshot"].get("snapshot_id") for item in source_screening],
        },
        "failed": failed,
        "incomplete": [*incomplete, *screening_incomplete],
        "unavailable": unavailable,
        "rejected": rejected,
        "unknown": unknown,
        "quarantined": quarantined,
        "blocked": blocked,
        "candidate_statuses": _state_values(source_candidates, "status"),
        "validation_statuses": _state_values(source_candidates, "validation_status"),
        "coverage_statuses": _state_values(source_candidates, "coverage_status"),
        "observation_statuses": _state_values(source_candidates, "observation_status"),
        "source_version_ids": [item.get("version_id") for item in source_versions],
    }


def build_aoi_run_report(
    data_root: Path,
    *,
    project_id: str,
    aoi_id: str,
    aoi_revision: int,
) -> dict[str, Any]:
    """Build a deterministic, read-only report for one immutable AOI revision."""
    root = data_root.resolve()
    persisted = _load_aoi(root, project_id, aoi_id, aoi_revision)
    revision = persisted["revision"]
    catalog_path = root / "catalog" / "sources.sqlite3"
    repository = SQLiteSourceRepository(root, read_only=True) if catalog_path.exists() else None
    parent_runs = (
        repository.list_aoi_ingestion_runs(
            project_id=project_id, aoi_id=aoi_id, aoi_revision=aoi_revision
        )
        if repository
        else []
    )
    parent_records: list[dict[str, Any]] = []
    for parent in parent_runs:
        parent_record = dict(parent)
        parent_record["plan_record"] = _plan_record(
            parent["plan_path"],
            parent["summary"].get("plan_sha256", ""),
            parent["summary"].get("plan_size_bytes", 0),
        )
        parent_records.append(parent_record)
    if repository:
        child_runs = [
            _run_record(repository, run)
            for run in repository.list_runs()
            if run.get("project_id") == project_id
            and run.get("aoi_id") == aoi_id
            and int(run.get("aoi_revision") or -1) == aoi_revision
        ]
    else:
        child_runs = []
    run_ids = {str(run["run_id"]) for run in child_runs}
    candidates = [
        item
        for item in (repository.list_candidates() if repository else [])
        if str(item["run_id"]) in run_ids
    ]
    candidate_ids = [str(item["candidate_id"]) for item in candidates]
    promotions = (
        repository.list_promotion_decisions(candidate_ids=candidate_ids) if repository else []
    )
    active_versions = (
        repository.list_active_aoi_versions(
            project_id=project_id, aoi_id=aoi_id, aoi_revision=aoi_revision
        )
        if repository
        else []
    )
    version_ids = {str(item["version_id"]) for item in candidates if item.get("version_id")} | {
        str(item["version_id"]) for item in active_versions
    }
    versions = [
        item
        for item in (repository.list_versions() if repository else [])
        if str(item["version_id"]) in version_ids
    ]
    jobs = _read_screening_jobs(
        root,
        project_id=project_id,
        aoi_id=aoi_id,
        aoi_revision=aoi_revision,
        repository=repository,
    )
    selected_sources = _source_ids(parent_records, child_runs, candidates, jobs)
    parent_summaries = [
        {**summary, "parent_run_id": parent["parent_run_id"]}
        for parent in parent_records
        for summary in parent.get("summary", {}).get("sources", {}).values()
    ]
    sources: dict[str, dict[str, Any]] = {}
    for source_id in selected_sources:
        source_candidates = [item for item in candidates if item["source_id"] == source_id]
        source_runs = [item for item in child_runs if item["source_id"] == source_id]
        source_promotions = [item for item in promotions if item["source_id"] == source_id]
        source_parent_summaries = [
            item for item in parent_summaries if item.get("source_id") == source_id
        ]
        sources[source_id] = {
            "source_id": source_id,
            "parent_summaries": source_parent_summaries,
            "acquisition_summary": {
                "planned_artifact_counts": [
                    item.get("planned_artifact_count") for item in source_parent_summaries
                ],
                "acquired_artifact_counts": [
                    item.get("acquired_artifact_count") for item in source_parent_summaries
                ],
                "bytes_downloaded": [
                    item.get("bytes_downloaded") for item in source_parent_summaries
                ],
            },
            "ingestion_runs": source_runs,
            "candidates": source_candidates,
            "source_versions": [item for item in versions if item["source_id"] == source_id],
            "promotion_decisions": source_promotions,
            "active_aoi_versions": [
                item for item in active_versions if item["source_id"] == source_id
            ],
            "screening": [
                {
                    "job_id": job.get("job", {}).get("job_id"),
                    "source_snapshots": [
                        snapshot
                        for snapshot in job.get("source_snapshots", [])
                        if snapshot.get("source_id") == source_id
                    ],
                    "result": [
                        result
                        for result in (job.get("result") or {}).get("source_results", [])
                        if result.get("source_id") == source_id
                    ],
                }
                for job in jobs
                if any(
                    snapshot.get("source_id") == source_id
                    for snapshot in job.get("source_snapshots", [])
                )
            ],
        }
        sources[source_id]["lifecycle"] = _source_lifecycle(
            source_id,
            parent_summaries=parent_summaries,
            child_runs=child_runs,
            candidates=candidates,
            versions=versions,
            promotions=promotions,
            active_versions=active_versions,
            jobs=jobs,
        )
    spatial = revision.get("spatial_validation", {})
    area_sqkm = spatial.get("area_sqkm")
    report = {
        "report_type": "aoi_operational_run",
        "report_version": 1,
        "project": {
            "project_id": project_id,
            "name": persisted["project"].get("name"),
        },
        "aoi": {
            "aoi_id": aoi_id,
            "revision": aoi_revision,
            "geometry_sha256": revision.get("geometry_sha256"),
            "policy": revision.get("validation_policy"),
            "policy_description": spatial.get("validation_policy_description"),
            "area": {
                "value_sqkm": area_sqkm,
                "value_sqm": float(area_sqkm) * 1_000_000 if area_sqkm is not None else None,
                "crs": spatial.get("area_crs"),
            },
            "spatial_validation": spatial,
        },
        "selected_sources": selected_sources,
        "parent_ingestion_runs": parent_records,
        "ingestion_runs": child_runs,
        "acquisition_attempts": [
            attempt for run in child_runs for attempt in run.get("acquisition_attempts", [])
        ],
        "candidates": candidates,
        "source_versions": versions,
        "promotion_decisions": promotions,
        "active_aoi_versions": active_versions,
        "screening_jobs": jobs,
        "sources": sources,
        "warnings": [
            "This report is read-only and preserves source-specific lifecycle states; it does not infer an overall suitability or absence conclusion.",
            "Unknown, unavailable, incomplete, nodata, pending, and quarantined states remain distinct from no constraint observed.",
        ],
    }
    return report


def render_aoi_run_summary(report: dict[str, Any]) -> str:
    """Render a concise human-readable summary without collapsing source states."""
    aoi = report["aoi"]
    area = aoi["area"].get("value_sqkm")
    lines = [
        f"AOI {aoi['aoi_id']} revision {aoi['revision']} | "
        f"policy={aoi.get('policy')} | geometry={aoi.get('geometry_sha256')}",
        f"Area: {area} km² | parent ingestion runs: {len(report['parent_ingestion_runs'])} | "
        f"screening jobs: {len(report['screening_jobs'])}",
        "Source lifecycle:",
    ]
    for source_id in report["selected_sources"]:
        lifecycle = report["sources"][source_id]["lifecycle"]
        states = (
            ", ".join(
                state
                for state in ("acquired", "validated", "promoted", "screened")
                if lifecycle[state]["observed"]
            )
            or "none"
        )
        exceptional = []
        for state in (
            "failed",
            "incomplete",
            "unavailable",
            "rejected",
            "unknown",
            "quarantined",
            "blocked",
        ):
            if lifecycle[state]:
                exceptional.append(f"{state}={len(lifecycle[state])}")
        suffix = f"; {', '.join(exceptional)}" if exceptional else ""
        lines.append(
            f"  - {source_id}: stopped_at={lifecycle['stopped_at']}; observed={states}{suffix}"
        )
    return "\n".join(lines)
