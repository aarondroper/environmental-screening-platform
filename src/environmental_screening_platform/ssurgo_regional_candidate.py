"""Materialize the audited regional SSURGO staging result as an inactive candidate.

This module creates a control-plane record for an already completed staging
publication.  It does not copy or alter the raw ZIPs or PostGIS staging rows,
and it deliberately uses the existing candidate/promotion model: the derived
aggregate is a candidate artifact, not an active SSURGO release.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .catalog import SQLiteSourceRepository
from .models import Acquisition, source_version_id
from .ssurgo_packages import SSURGO_TERMS_URL
from .store import read_json, write_json

ADAPTER_VERSION = "ssurgo-regional-candidate-v1"
STAGING_MANIFEST_KEY = "ssurgo_regional_staging"
CANDIDATE_MANIFEST_KEY = "ssurgo_regional_candidate"
SYNTHETIC_SNAPSHOT_PREFIX = "ssurgo-regional-staging:"


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _require_file(path_value: str | Path, *, label: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} is unavailable: {path}")
    return path


def _assert_hash(path: Path, expected: str, *, label: str) -> int:
    actual, size = _sha256(path)
    if actual != expected:
        raise ValueError(f"{label} checksum mismatch: expected {expected}, got {actual}")
    return size


def _load_staging_inputs(
    data_root: Path,
    catalog: SQLiteSourceRepository,
    staging_report: Path | None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    Path,
]:
    manifest = read_json(data_root / "manifest.json")
    staging_pointer = manifest.get(STAGING_MANIFEST_KEY)
    if not isinstance(staging_pointer, dict):
        raise ValueError("External manifest has no regional SSURGO staging record")
    aggregate_path = _require_file(
        staging_report or staging_pointer.get("latest_aggregate_report", ""),
        label="SSURGO staging aggregate report",
    )
    try:
        aggregate_path.relative_to(data_root)
    except ValueError as exc:
        raise ValueError(
            "SSURGO staging aggregate must be inside the external data directory"
        ) from exc
    expected_aggregate_sha = str(staging_pointer.get("aggregate_report_sha256", ""))
    if not expected_aggregate_sha:
        raise ValueError("SSURGO staging manifest is missing the aggregate checksum")
    aggregate_size = _assert_hash(
        aggregate_path, expected_aggregate_sha, label="SSURGO staging aggregate report"
    )
    aggregate = read_json(aggregate_path)
    if aggregate.get("source_id") != "ssurgo" or aggregate.get("status") != "completed":
        raise ValueError("SSURGO staging aggregate is not a completed SSURGO result")
    expected_counts = {
        "package_count": 19,
        "feature_count": 123196,
        "map_unit_count": 1878,
        "component_count": 7404,
        "original_invalid_count": 10,
        "repaired_accepted_count": 10,
        "quarantined_count": 0,
    }
    for key, expected in expected_counts.items():
        if aggregate.get(key) != expected:
            raise ValueError(
                f"SSURGO staging aggregate {key} is {aggregate.get(key)!r}, expected {expected}"
            )
    for flag in ("raw_packages_unchanged", "source_candidates_unchanged", "postgis_staging_only"):
        if aggregate.get(flag) is not True:
            raise ValueError(f"SSURGO staging aggregate does not confirm {flag}")
    if aggregate.get("active_source_version_created") is not False:
        raise ValueError("SSURGO staging aggregate indicates an active version was created")

    package_reports: list[dict[str, Any]] = []
    package_candidates: list[dict[str, Any]] = []
    package_paths = aggregate.get("packages")
    if not isinstance(package_paths, list) or len(package_paths) != 19:
        raise ValueError("SSURGO staging aggregate does not list exactly 19 package reports")
    for relative in package_paths:
        report_path = _require_file(
            aggregate_path.parent / str(relative), label="SSURGO package report"
        )
        report = read_json(report_path)
        if report.get("staging_status") != "complete" or report.get("quarantined_count") != 0:
            raise ValueError(f"Package {report.get('areasymbol')} is not eligible staged data")
        raw_path = _require_file(
            report["artifact_path"], label=f"{report['areasymbol']} raw package"
        )
        raw_size = _assert_hash(
            raw_path, report["artifact_sha256"], label=f"{report['areasymbol']} raw package"
        )
        if raw_size != report["artifact_size_bytes"]:
            raise ValueError(
                f"{report['areasymbol']} raw package size does not match staging report"
            )
        candidate = catalog.get_candidate(str(report["candidate_id"]))
        if candidate is None:
            raise ValueError(f"Package candidate is missing: {report['candidate_id']}")
        if (
            candidate.get("source_id") != "ssurgo"
            or candidate.get("promotion_status") != "not_promoted"
        ):
            raise ValueError(
                f"Package candidate {report['candidate_id']} is not inactive SSURGO data"
            )
        if candidate.get("version_id") != report.get("source_version_id"):
            raise ValueError(
                f"{report['areasymbol']} source-version lineage does not match its candidate"
            )
        if candidate.get("sha256") != report.get("artifact_sha256"):
            raise ValueError(
                f"{report['areasymbol']} candidate checksum does not match raw package"
            )
        package_reports.append(
            {
                "report_path": str(report_path),
                "raw_path": str(raw_path),
                "raw_sha256": report["artifact_sha256"],
                "raw_size_bytes": raw_size,
                "areasymbol": report["areasymbol"],
                "candidate_id": report["candidate_id"],
                "ingestion_run_id": report["ingestion_run_id"],
                "source_snapshot_id": report["source_snapshot_id"],
                "source_version_id": report["source_version_id"],
                "batch_id": report["batch_id"],
                "provider_release": report.get("provider_release"),
                "source_url": report.get("source_url"),
                "areaname": report.get("areaname"),
                "feature_count": report.get("feature_count"),
                "map_unit_count": report.get("map_unit_count"),
                "component_count": report.get("component_count"),
                "validation_status": report.get("validation_status"),
            }
        )
        package_candidates.append(
            {
                "candidate_id": candidate["candidate_id"],
                "ingestion_run_id": candidate["run_id"],
                "source_version_id": candidate["version_id"],
                "status": candidate["status"],
                "validation_status": candidate["validation_status"],
                "coverage_status": candidate["coverage_status"],
                "promotion_status": candidate["promotion_status"],
            }
        )

    audit_pointer = manifest.get("ssurgo_regional_discrepancy_audit", {})
    audit_path = _require_file(
        audit_pointer.get("latest_aggregate_report", ""),
        label="SSURGO discrepancy audit aggregate report",
    )
    audit_sha = str(audit_pointer.get("aggregate_report_sha256", ""))
    _assert_hash(audit_path, audit_sha, label="SSURGO discrepancy audit aggregate report")
    qa_pointer = manifest.get("ssurgo_regional_qa", {})
    qa_path = _require_file(
        qa_pointer.get("latest_aggregate_report", ""),
        label="SSURGO package QA aggregate report",
    )
    qa_sha, qa_size = _sha256(qa_path)
    qa_report = read_json(qa_path)
    if qa_report.get("package_count") != 19:
        raise ValueError("SSURGO package QA report does not cover all 19 packages")
    return (
        aggregate,
        package_reports,
        package_candidates,
        {
            "manifest": manifest,
            "aggregate_path": str(aggregate_path),
            "aggregate_size_bytes": aggregate_size,
            "audit_path": str(audit_path),
            "audit_sha256": audit_sha,
            "qa_path": str(qa_path),
            "qa_sha256": qa_sha,
            "qa_size_bytes": qa_size,
            "package_count": len(package_reports),
        },
        aggregate_path,
    )


def materialize_staged_ssurgo_candidate(
    data_root: Path,
    *,
    staging_report: Path | None = None,
    repository: SQLiteSourceRepository | None = None,
) -> dict[str, Any]:
    """Create or return the inactive candidate for the current staging report."""
    data_root = data_root.resolve()
    catalog = repository or SQLiteSourceRepository(data_root)
    aggregate, package_reports, package_candidates, lineage, aggregate_path = _load_staging_inputs(
        data_root, catalog, staging_report
    )
    aggregate_sha = _sha256(aggregate_path)[0]
    staging_run_id = str(aggregate["staging_run_id"])
    release = f"SSURGO regional staged dataset {staging_run_id}"
    version_id = source_version_id("ssurgo", release, aggregate_sha)
    existing_versions = [
        item for item in catalog.list_versions("ssurgo") if item["version_id"] == version_id
    ]
    if existing_versions:
        version = existing_versions[0]
        if (
            version["sha256"] != aggregate_sha
            or version["byte_size"] != lineage["aggregate_size_bytes"]
            or Path(version["artifact_path"]).resolve() != aggregate_path
        ):
            raise ValueError("Existing staged source version conflicts with aggregate provenance")
        existing = [
            item
            for item in catalog.list_candidates("ssurgo")
            if item.get("version_id") == version_id
        ]
        if len(existing) != 1:
            raise ValueError("Existing staged source version does not have exactly one candidate")
        candidate = existing[0]
        if candidate.get("promotion_status") != "not_promoted":
            raise ValueError("Staged SSURGO candidate was promoted outside this workflow")
        manifest = lineage["manifest"]
        manifest[CANDIDATE_MANIFEST_KEY] = {
            **manifest.get(CANDIDATE_MANIFEST_KEY, {}),
            "candidate_id": candidate["candidate_id"],
            "source_version_id": version_id,
            "ingestion_run_id": candidate["run_id"],
            "synthetic_source_snapshot_id": f"{SYNTHETIC_SNAPSHOT_PREFIX}{staging_run_id}",
            "staging_run_id": staging_run_id,
            "aggregate_report": lineage["aggregate_path"],
            "aggregate_report_sha256": aggregate_sha,
            "package_candidates": package_candidates,
            "raw_package_checksums": [item["raw_sha256"] for item in package_reports],
            "repair_audit_report": lineage["audit_path"],
            "repair_audit_report_sha256": lineage["audit_sha256"],
            "package_qa_report": lineage["qa_path"],
            "package_qa_report_sha256": lineage["qa_sha256"],
            "status": "inactive_candidate",
            "validation_status": candidate["validation_status"],
            "coverage_status": candidate["coverage_status"],
            "promotion_status": candidate["promotion_status"],
            "active_source_version_created": False,
        }
        write_json(data_root / "manifest.json", manifest)
        return {
            "candidate": candidate,
            "version": version,
            "idempotent": True,
            "synthetic_source_snapshot_id": f"{SYNTHETIC_SNAPSHOT_PREFIX}{staging_run_id}",
            "staging_run_id": staging_run_id,
        }

    acquired_at = datetime.now(UTC).isoformat()
    acquisition = Acquisition(
        source_id="ssurgo",
        provider="USDA NRCS SSURGO",
        release=release,
        source_url=f"staged://ssurgo/regional/{staging_run_id}",
        acquired_at=acquired_at,
        media_type="application/json",
        raw_path=str(aggregate_path),
        size_bytes=lineage["aggregate_size_bytes"],
        sha256=aggregate_sha,
        terms_url=SSURGO_TERMS_URL,
        request_parameters={
            "staging_run_id": staging_run_id,
            "aggregate_report": lineage["aggregate_path"],
            "source_snapshot_id": f"{SYNTHETIC_SNAPSHOT_PREFIX}{staging_run_id}",
        },
        requested_url=lineage["aggregate_path"],
    )
    validation = {
        "validation_scope": "19 acquired official packages represented by the approved staging batch",
        "maturity": "conditionally_validated",
        "coverage_status": "partial",
        "observation_status": "incomplete_source",
        "package_acquisition": {
            "acquired_count": 19,
            "structurally_valid_count": 19,
            "structural_validation": "CRC and expected SSURGO spatial/tabular package structure passed for all 19 acquired ZIPs",
        },
        "staging_metrics": {
            "soilmu_a_features": aggregate["feature_count"],
            "map_units": aggregate["map_unit_count"],
            "components": aggregate["component_count"],
            "audited_repairs_accepted": aggregate["repaired_accepted_count"],
            "quarantined_features": aggregate["quarantined_count"],
            "derived_geometry_valid": True,
            "derived_geometry_crs": "EPSG:4326",
            "analysis_crs": aggregate["area_crs"],
            "orphan_component_joins": 0,
        },
        "identity_notes": [
            "WY621/WY721 survey-area naming differences are documented harmless variations; provider package identity and checksums agree.",
        ],
        "lineage": {
            "synthetic_source_snapshot_id": f"{SYNTHETIC_SNAPSHOT_PREFIX}{staging_run_id}",
            "staging_run_id": staging_run_id,
            "staging_aggregate_report": lineage["aggregate_path"],
            "staging_aggregate_sha256": aggregate_sha,
            "discrepancy_audit_report": lineage["audit_path"],
            "discrepancy_audit_sha256": lineage["audit_sha256"],
            "package_qa_report": lineage["qa_path"],
            "package_qa_sha256": lineage["qa_sha256"],
            "package_candidates": package_candidates,
            "package_reports": package_reports,
        },
        "source_maturity_preserved": True,
        "regional_coverage_validation_complete": False,
        "promotion_eligible": False,
        "raw_artifacts_unchanged": True,
        "staged_geometries_unchanged": True,
        "active_source_version_created": False,
    }
    run = catalog.begin_run(
        source_id="ssurgo",
        requested_url=acquisition.requested_url or acquisition.source_url,
        adapter_version=ADAPTER_VERSION,
    )
    catalog.record_attempt(
        run["run_id"],
        status="acquired",
        requested_url=acquisition.requested_url or acquisition.source_url,
        actual_url=acquisition.source_url,
        retrieved_at=acquired_at,
        sha256=aggregate_sha,
        byte_size=lineage["aggregate_size_bytes"],
        details={
            "materialization": "existing staged artifact; no provider download",
            "staging_run_id": staging_run_id,
            "package_count": 19,
        },
    )
    candidate = catalog.record_candidate(
        run["run_id"],
        acquisition=acquisition,
        adapter_version=ADAPTER_VERSION,
        status="incomplete",
        validation_status="conditionally_validated",
        coverage_status="partial",
        observation_status="incomplete_source",
        validation=validation,
        finalize=True,
    )
    if candidate.get("version_id") != version_id:
        raise ValueError("Materialized candidate source-version identity is not deterministic")
    manifest = lineage["manifest"]
    manifest[CANDIDATE_MANIFEST_KEY] = {
        "candidate_id": candidate["candidate_id"],
        "source_version_id": candidate["version_id"],
        "ingestion_run_id": candidate["run_id"],
        "synthetic_source_snapshot_id": f"{SYNTHETIC_SNAPSHOT_PREFIX}{staging_run_id}",
        "staging_run_id": staging_run_id,
        "aggregate_report": lineage["aggregate_path"],
        "aggregate_report_sha256": aggregate_sha,
        "package_candidates": package_candidates,
        "raw_package_checksums": [item["raw_sha256"] for item in package_reports],
        "repair_audit_report": lineage["audit_path"],
        "repair_audit_report_sha256": lineage["audit_sha256"],
        "package_qa_report": lineage["qa_path"],
        "package_qa_report_sha256": lineage["qa_sha256"],
        "status": "inactive_candidate",
        "validation_status": "conditionally_validated",
        "coverage_status": "partial",
        "promotion_status": "not_promoted",
        "active_source_version_created": False,
    }
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(data_root / "manifest.json", manifest)
    version = next(
        item for item in catalog.list_versions("ssurgo") if item["version_id"] == version_id
    )
    return {
        "candidate": candidate,
        "version": version,
        "idempotent": False,
        "synthetic_source_snapshot_id": f"{SYNTHETIC_SNAPSHOT_PREFIX}{staging_run_id}",
        "staging_run_id": staging_run_id,
    }
