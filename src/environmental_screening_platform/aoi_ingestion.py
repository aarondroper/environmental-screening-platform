"""AOI-scoped orchestration across the currently supported source adapters.

This module deliberately coordinates the existing adapters; it does not own
provider acquisition or source-specific validation.  The parent record is a
control-plane summary and every source continues to create its normal child
run, attempt, candidate, and external artifact records.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from .catalog import SourceRepository, SQLiteSourceRepository
from .ingestion import REQUEST_URLS, _aoi_context, ingest_3dep, ingest_nlcd_aoi
from .models import MATURITY
from .ssurgo_aoi import SSURGO_SDA_URL, ingest_ssurgo_aoi
from .store import read_json, write_json
from .three_dep import THREEDEP_INVENTORY_URL

SOURCE_ORDER = ("nlcd", "3dep", "ssurgo")
SOURCE_IDS = {"nlcd": "annual_nlcd", "3dep": "3dep", "ssurgo": "ssurgo"}
DEFAULT_LIMITS: dict[str, dict[str, int]] = {
    "nlcd": {"max_bytes": 256_000_000, "max_artifacts": 1},
    "3dep": {"max_bytes": 600_000_000, "max_artifacts": 16},
    "ssurgo": {"max_bytes": 500_000_000, "max_artifacts": 16},
}
DEFAULT_MAX_TOTAL_BYTES = 1_000_000_000


def _canonical_sources(sources: Sequence[str]) -> list[str]:
    selected = list(sources)
    unknown = sorted(set(selected) - set(SOURCE_ORDER))
    if unknown:
        raise ValueError(f"Unsupported AOI ingestion source(s): {', '.join(unknown)}")
    if not selected:
        raise ValueError("At least one AOI ingestion source is required")
    if len(set(selected)) != len(selected):
        raise ValueError("AOI ingestion sources must be unique")
    return [source for source in SOURCE_ORDER if source in selected]


def normalize_limits(
    sources: Sequence[str],
    per_source_limits: dict[str, dict[str, int]] | None,
    max_total_bytes: int,
) -> dict[str, Any]:
    if max_total_bytes <= 0:
        raise ValueError("The total acquisition limit must be positive")
    supplied = per_source_limits or {}
    unknown = sorted(set(supplied) - set(SOURCE_ORDER))
    if unknown:
        raise ValueError(
            f"Limits supplied for unselected or unknown source(s): {', '.join(unknown)}"
        )
    normalized: dict[str, dict[str, int]] = {}
    for source in sources:
        values = dict(DEFAULT_LIMITS[source])
        values.update(supplied.get(source, {}))
        if values["max_bytes"] <= 0 or values["max_artifacts"] <= 0:
            raise ValueError(f"Limits for {source} must be positive")
        normalized[source] = values
    return {"per_source": normalized, "max_total_bytes": max_total_bytes}


def _plan_for(
    *,
    project_id: str,
    aoi_id: str,
    revision: dict[str, Any],
    context_geometry: Any,
    sources: list[str],
    limits: dict[str, Any],
) -> dict[str, Any]:
    geometry_hash = revision.get("geometry_sha256")
    if not geometry_hash:
        raise ValueError("AOI revision is missing its immutable geometry hash")
    source_plans: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {
        "nlcd": {
            "source_id": "annual_nlcd",
            "adapter": "ingest_nlcd_aoi",
            "official_url": REQUEST_URLS["annual_nlcd"],
            "planning_mode": "bounded_single_raster_window",
            "planned_artifact_count": 1,
            "network_discovery": False,
        },
        "3dep": {
            "source_id": "3dep",
            "adapter": "ingest_3dep",
            "official_url": THREEDEP_INVENTORY_URL,
            "planning_mode": "dynamic_inventory_then_tile_acquisition",
            "planned_artifact_count": None,
            "network_discovery": True,
        },
        "ssurgo": {
            "source_id": "ssurgo",
            "adapter": "ingest_ssurgo_aoi",
            "official_url": SSURGO_SDA_URL,
            "planning_mode": "dynamic_SDA_survey_area_discovery_then_WSS_packages",
            "planned_artifact_count": None,
            "network_discovery": True,
        },
    }
    for source in sources:
        source_plans.append(
            {
                "source": source,
                **metadata[source],
                "source_maturity": MATURITY[SOURCE_IDS[source]][0].value,
                "validation_scope": MATURITY[SOURCE_IDS[source]][1],
                "limits": limits["per_source"][source],
            }
        )
    plan = {
        "plan_version": 1,
        "project_id": project_id,
        "aoi_id": aoi_id,
        "aoi_revision": int(revision["revision"]),
        "aoi_geometry_sha256": geometry_hash,
        "aoi": {
            "crs": "EPSG:4326",
            "bounds": [float(value) for value in context_geometry.bounds],
        },
        "sources": source_plans,
        "limits": limits,
    }
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    plan["plan_id"] = f"aoi-ingestion:{hashlib.sha256(encoded.encode()).hexdigest()}"
    return plan


def _write_plan(data_root: Path, plan: dict[str, Any]) -> Path:
    path = data_root / "aoi-ingestion" / "plans" / f"{plan['plan_id'].split(':', 1)[1]}.json"
    write_json(path, plan)
    return path


def _initial_summary(
    *, parent_run_id: str, plan: dict[str, Any], plan_path: Path, dry_run: bool
) -> dict[str, Any]:
    plan_bytes = plan_path.read_bytes()
    return {
        "parent_run_id": parent_run_id,
        "status": "dry_run" if dry_run else "running",
        "project_id": plan["project_id"],
        "aoi_id": plan["aoi_id"],
        "aoi_revision": plan["aoi_revision"],
        "aoi_geometry_sha256": plan["aoi_geometry_sha256"],
        "plan_id": plan["plan_id"],
        "plan_path": str(plan_path),
        "plan_size_bytes": len(plan_bytes),
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "sources": {
            item["source"]: {
                "source": item["source"],
                "source_id": item["source_id"],
                "source_maturity": item["source_maturity"],
                "validation_scope": item["validation_scope"],
                "status": "planned",
                "availability_status": "planned",
                "coverage_statuses": [],
                "observation_statuses": [],
                "planned_artifact_count": item["planned_artifact_count"],
                "planned": True,
                "attempts": [],
                "warnings": [],
                "unknown_coverage": [],
            }
            for item in plan["sources"]
        },
        "warnings": [
            "Candidates remain inactive and unpromoted; this run performs acquisition and validation only.",
            "Missing, unavailable, incomplete, or unknown source coverage is never interpreted as no constraint.",
        ],
        "unknown_coverage": [],
        "retry": None,
    }


def _candidate_items(source: str, outcome: dict[str, Any]) -> list[dict[str, Any]]:
    if source == "nlcd":
        candidate = outcome.get("candidate")
        return [candidate] if candidate else []
    key = "tiles" if source == "3dep" else "packages"
    return [item.get("candidate") for item in outcome.get(key, []) if item.get("candidate")]


def _source_summary(source: str, outcome: dict[str, Any]) -> dict[str, Any]:
    candidates = _candidate_items(source, outcome)
    statuses = [str(item.get("status")) for item in candidates]
    failed = [
        item for item in candidates if item.get("status") in {"failed", "blocked", "quarantined"}
    ]
    incomplete = [
        item
        for item in candidates
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
    acquired = [item for item in candidates if item.get("artifact_path")]
    bytes_downloaded = sum(int(item.get("byte_size") or 0) for item in acquired)
    if failed and acquired:
        status = "partial"
    elif failed:
        status = "failed"
    elif incomplete:
        status = "incomplete"
    else:
        status = "completed"
    unknown = [
        {
            "candidate_id": item.get("candidate_id"),
            "coverage_status": item.get("coverage_status"),
            "observation_status": item.get("observation_status"),
            "reason": (item.get("error") or {}).get("message"),
        }
        for item in candidates
        if item.get("coverage_status") not in {None, "complete"}
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
    validation_status = [item.get("validation_status") for item in candidates]
    coverage_statuses = [item.get("coverage_status") for item in candidates]
    observation_statuses = [item.get("observation_status") for item in candidates]
    if any(item.get("status") == "blocked" for item in candidates):
        availability_status = "blocked"
    elif any(item.get("coverage_status") == "unavailable" for item in candidates):
        availability_status = "unavailable"
    elif failed:
        availability_status = "failed"
    elif incomplete:
        availability_status = "incomplete"
    else:
        availability_status = "available"
    attempts = [
        {
            "run_id": item.get("run_id"),
            "candidate_id": item.get("candidate_id"),
            "status": item.get("status"),
            "artifact_path": item.get("artifact_path"),
            "byte_size": item.get("byte_size"),
            "sha256": item.get("sha256"),
            "validation_status": item.get("validation_status"),
            "coverage_status": item.get("coverage_status"),
            "observation_status": item.get("observation_status"),
            "provenance": (item.get("validation") or {}).get("source_provenance", {}),
            "request_parameters": (
                (item.get("validation") or {})
                .get("source_provenance", {})
                .get("request_parameters")
                or ((item.get("acquisition_attempts") or [{}])[-1].get("details") or {}).get(
                    "request_parameters", {}
                )
            ),
            "validation": item.get("validation") or {},
            "error": item.get("error"),
        }
        for item in candidates
    ]
    warnings: list[str] = []
    for item in candidates:
        warnings.extend((item.get("validation") or {}).get("warnings", []))
    return {
        "source": source,
        "source_id": SOURCE_IDS[source],
        "source_maturity": MATURITY[SOURCE_IDS[source]][0].value,
        "validation_scope": MATURITY[SOURCE_IDS[source]][1],
        "status": status,
        "availability_status": availability_status,
        "coverage_statuses": coverage_statuses,
        "observation_statuses": observation_statuses,
        "child_run_ids": [item.get("run_id") for item in candidates if item.get("run_id")],
        "candidate_ids": [
            item.get("candidate_id") for item in candidates if item.get("candidate_id")
        ],
        "planned_artifact_count": (
            outcome.get("selected_tile_count")
            if source == "3dep"
            else len(outcome.get("packages", []))
            if source == "ssurgo"
            else 1
        ),
        "acquired_artifact_count": len(acquired),
        "bytes_downloaded": bytes_downloaded,
        "validation_statuses": validation_status,
        "candidate_statuses": statuses,
        "attempts": attempts,
        "warnings": warnings,
        "unknown_coverage": unknown,
        "provenance": [attempt["provenance"] for attempt in attempts],
        "outcome_record_path": outcome.get("batch_record_path") or outcome.get("manifest_path"),
        "provider_plan_id": outcome.get("plan_id") or (outcome.get("plan") or {}).get("plan_id"),
        "promotion_status": "not_promoted",
    }


def _parent_status(source_results: dict[str, dict[str, Any]]) -> str:
    statuses = [item["status"] for item in source_results.values()]
    if all(status in {"failed", "partial", "rejected"} for status in statuses):
        return "failed"
    if any(status in {"failed", "partial", "rejected", "incomplete"} for status in statuses):
        return "partial"
    return "completed"


def _write_run_record(data_root: Path, summary: dict[str, Any]) -> Path:
    path = data_root / "aoi-ingestion" / "runs" / f"{summary['parent_run_id']}.json"
    write_json(path, summary)
    manifest_path = data_root / "manifest.json"
    manifest: dict[str, Any] = (
        read_json(manifest_path)
        if manifest_path.exists()
        else {
            "manifest_version": 1,
            "retrieved_on": datetime.now(UTC).date().isoformat(),
            "scope": "External source artifacts and validation records",
            "artifacts": [],
            "failed_attempts": [],
        }
    )
    runs = manifest.setdefault("aoi_ingestion_runs", [])
    record = {
        "parent_run_id": summary["parent_run_id"],
        "plan_id": summary["plan_id"],
        "plan_path": summary["plan_path"],
        "plan_size_bytes": summary["plan_size_bytes"],
        "plan_sha256": summary["plan_sha256"],
        "run_record_path": str(path),
        "project_id": summary["project_id"],
        "aoi_id": summary["aoi_id"],
        "aoi_revision": summary["aoi_revision"],
        "aoi_geometry_sha256": summary["aoi_geometry_sha256"],
        "status": summary["status"],
        "source_statuses": {source: item["status"] for source, item in summary["sources"].items()},
    }
    existing = next(
        (
            index
            for index, item in enumerate(runs)
            if item.get("parent_run_id") == summary["parent_run_id"]
        ),
        None,
    )
    if existing is None:
        runs.append(record)
    else:
        runs[existing] = record
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)
    return path


def _execute_source(
    source: str,
    *,
    data_root: Path,
    project_id: str,
    aoi_id: str,
    repository: SourceRepository,
    session: Any,
    limits: dict[str, int],
    remaining_total: int,
) -> dict[str, Any]:
    if source == "nlcd":
        return ingest_nlcd_aoi(
            data_root,
            project_id=project_id,
            aoi_id=aoi_id,
            repository=repository,
            session=session,
            max_bytes=min(limits["max_bytes"], remaining_total),
        )
    if source == "3dep":
        return ingest_3dep(
            data_root,
            project_id=project_id,
            aoi_id=aoi_id,
            repository=repository,
            session=session,
            max_tiles=limits["max_artifacts"],
            max_total_bytes=min(limits["max_bytes"], remaining_total),
            max_tile_bytes=limits["max_bytes"],
        )
    return ingest_ssurgo_aoi(
        data_root,
        project_id=project_id,
        aoi_id=aoi_id,
        repository=repository,
        session=session,
        max_survey_areas=limits["max_artifacts"],
        max_total_bytes=min(limits["max_bytes"], remaining_total),
    )


def ingest_aoi(
    data_root: Path,
    *,
    project_id: str,
    aoi_id: str,
    sources: Sequence[str],
    per_source_limits: dict[str, dict[str, int]] | None = None,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    dry_run: bool = False,
    retry_parent_run_id: str | None = None,
    retry_sources: Sequence[str] | None = None,
    repository: SourceRepository | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Plan and execute independent bounded source acquisitions for one AOI."""
    root = data_root.resolve()
    repository = repository or SQLiteSourceRepository(root)
    geometry, revision = _aoi_context(root, project_id, aoi_id)
    if geometry is None or revision is None:
        raise ValueError("AOI ingestion requires a persisted immutable AOI revision")
    context_sources = _canonical_sources(sources)

    if retry_parent_run_id:
        if dry_run:
            raise ValueError("A retry cannot be a dry run")
        existing = repository.get_aoi_ingestion_run(retry_parent_run_id)
        if existing is None:
            raise KeyError(f"Unknown AOI ingestion parent run: {retry_parent_run_id}")
        if existing["project_id"] != project_id or existing["aoi_id"] != aoi_id:
            raise ValueError("Retry parent belongs to a different project or AOI revision")
        if existing["aoi_geometry_sha256"] != revision.get("geometry_sha256"):
            raise ValueError("Retry parent geometry hash does not match the immutable AOI revision")
        plan = read_json(Path(existing["plan_path"]))
        plan_path = Path(existing["plan_path"])
        summary = existing["summary"]
        selected = list(retry_sources or [])
        if selected:
            selected = _canonical_sources(selected)
        else:
            selected = [
                source
                for source, result in summary["sources"].items()
                if result.get("status") in {"failed", "partial", "incomplete", "rejected"}
            ]
        planned_sources = set(existing["source_ids"])
        if any(SOURCE_IDS[source] not in planned_sources for source in selected):
            raise ValueError("Retry sources must be selected in the original parent plan")
        retry_key = hashlib.sha256(
            f"{retry_parent_run_id}|{','.join(selected)}".encode()
        ).hexdigest()
        if any(item.get("retry_key") == retry_key for item in summary.get("retry_history", [])):
            return summary
        completed = [
            source
            for source in selected
            if summary["sources"].get(source, {}).get("status") == "completed"
        ]
        if completed:
            raise ValueError(
                "Only failed, incomplete, partial, or rejected source attempts may be retried: "
                + ", ".join(completed)
            )
        if not selected:
            return summary
        limits = plan["limits"]
        retry_info: dict[str, Any] | None = {
            "retry_key": retry_key,
            "retry_of": retry_parent_run_id,
            "sources": selected,
            "reused": False,
            "new_child_run_ids": [],
        }
    else:
        limits = normalize_limits(context_sources, per_source_limits, max_total_bytes)
        plan = _plan_for(
            project_id=project_id,
            aoi_id=aoi_id,
            revision=revision,
            context_geometry=geometry,
            sources=context_sources,
            limits=limits,
        )
        plan_path = _write_plan(root, plan)
        parent_run_id = str(uuid4())
        summary = _initial_summary(
            parent_run_id=parent_run_id, plan=plan, plan_path=plan_path, dry_run=dry_run
        )
        if dry_run:
            summary["status"] = "dry_run"
            repository.create_aoi_ingestion_run(
                parent_run_id=parent_run_id,
                project_id=project_id,
                aoi_id=aoi_id,
                aoi_revision=int(revision["revision"]),
                aoi_geometry_sha256=str(revision["geometry_sha256"]),
                source_ids=[SOURCE_IDS[source] for source in context_sources],
                limits=limits,
                plan_id=plan["plan_id"],
                plan_path=str(plan_path),
                status="dry_run",
                summary=summary,
            )
            _write_run_record(root, summary)
            return summary
        repository.create_aoi_ingestion_run(
            parent_run_id=parent_run_id,
            project_id=project_id,
            aoi_id=aoi_id,
            aoi_revision=int(revision["revision"]),
            aoi_geometry_sha256=str(revision["geometry_sha256"]),
            source_ids=[SOURCE_IDS[source] for source in context_sources],
            limits=limits,
            plan_id=plan["plan_id"],
            plan_path=str(plan_path),
            status="running",
            summary=summary,
        )
        selected = context_sources
        retry_info = None

    if retry_parent_run_id:
        summary["status"] = "running"
        summary["retry"] = retry_info
        repository.update_aoi_ingestion_run(retry_parent_run_id, status="running", summary=summary)

    http_session = session or requests.Session()
    total_downloaded = sum(
        int(result.get("bytes_downloaded") or 0)
        for source, result in summary["sources"].items()
        if source not in selected
    )
    for source in selected:
        source_limits = limits["per_source"][source]
        try:
            outcome = _execute_source(
                source,
                data_root=root,
                project_id=project_id,
                aoi_id=aoi_id,
                repository=repository,
                session=http_session,
                limits=source_limits,
                remaining_total=max(1, int(limits["max_total_bytes"]) - total_downloaded),
            )
            source_result = _source_summary(source, outcome)
        except Exception as exc:
            source_result = {
                "source": source,
                "source_id": SOURCE_IDS[source],
                "source_maturity": MATURITY[SOURCE_IDS[source]][0].value,
                "validation_scope": MATURITY[SOURCE_IDS[source]][1],
                "status": "rejected" if "limit" in str(exc).lower() else "failed",
                "availability_status": "failed",
                "coverage_statuses": ["unavailable"],
                "observation_statuses": ["unavailable"],
                "child_run_ids": [],
                "candidate_ids": [],
                "planned_artifact_count": None,
                "acquired_artifact_count": 0,
                "bytes_downloaded": 0,
                "validation_statuses": [],
                "candidate_statuses": [],
                "attempts": [],
                "warnings": [f"{type(exc).__name__}: {exc}"],
                "unknown_coverage": [{"reason": f"{type(exc).__name__}: {exc}"}],
                "provenance": [],
                "promotion_status": "not_promoted",
            }
        prior_attempts = summary["sources"].get(source, {}).get("attempts", [])
        attempt = {
            "attempt_number": len(prior_attempts) + 1,
            "status": source_result["status"],
            "child_run_ids": source_result.get("child_run_ids", []),
            "candidate_ids": source_result.get("candidate_ids", []),
            "bytes_downloaded": source_result.get("bytes_downloaded", 0),
            "warnings": source_result.get("warnings", []),
            "artifacts": source_result.get("attempts", []),
        }
        source_result["attempts"] = [*prior_attempts, attempt]
        summary["sources"][source] = source_result
        total_downloaded += int(source_result.get("bytes_downloaded") or 0)
        summary["unknown_coverage"] = [
            {"source": name, **item}
            for name, result in summary["sources"].items()
            for item in result.get("unknown_coverage", [])
        ]
        summary["retry"] = retry_info
        if retry_info is not None:
            retry_info["new_child_run_ids"].extend(source_result.get("child_run_ids", []))
        repository.update_aoi_ingestion_run(
            summary["parent_run_id"], status="running", summary=summary
        )

    summary["status"] = _parent_status(summary["sources"])
    summary["bytes_downloaded"] = total_downloaded
    summary["planned_artifact_count"] = sum(
        int(result["planned_artifact_count"] or 0) for result in summary["sources"].values()
    )
    summary["acquired_artifact_count"] = sum(
        int(result.get("acquired_artifact_count") or 0) for result in summary["sources"].values()
    )
    if retry_info is not None:
        history = list(summary.get("retry_history", []))
        history.append(retry_info)
        summary["retry_history"] = history
        summary["retry"] = retry_info
    repository.update_aoi_ingestion_run(
        summary["parent_run_id"], status=summary["status"], summary=summary
    )
    _write_run_record(root, summary)
    return summary
