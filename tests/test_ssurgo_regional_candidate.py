from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.models import Acquisition, source_version_id
from environmental_screening_platform.ssurgo_regional_candidate import (
    materialize_staged_ssurgo_candidate,
)
from environmental_screening_platform.store import write_json


def _digest(path: Path) -> tuple[str, int]:
    body = path.read_bytes()
    return hashlib.sha256(body).hexdigest(), len(body)


def _make_fixture(root: Path) -> Path:
    catalog = SQLiteSourceRepository(root)
    package_dir = root / "raw" / "ssurgo"
    report_dir = root / "ssurgo" / "regional-staging" / "staging-fixture" / "packages"
    package_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    package_reports: list[str] = []
    package_candidates: list[dict[str, str]] = []
    for index in range(19):
        symbol = f"T{index:03d}"
        raw = package_dir / f"{symbol}.zip"
        raw.write_bytes(f"fixture package {symbol}".encode())
        sha, size = _digest(raw)
        release = f"SSURGO {symbol} fixture release"
        acquisition = Acquisition(
            source_id="ssurgo",
            provider="USDA NRCS SSURGO",
            release=release,
            source_url=f"https://example.invalid/{symbol}.zip",
            acquired_at="2026-09-24T00:00:00+00:00",
            media_type="application/zip",
            raw_path=str(raw),
            size_bytes=size,
            sha256=sha,
            terms_url="https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
        )
        run = catalog.begin_run(
            source_id="ssurgo",
            requested_url=acquisition.source_url,
            adapter_version="fixture",
        )
        catalog.record_attempt(
            run["run_id"],
            status="acquired",
            requested_url=acquisition.source_url,
            actual_url=acquisition.source_url,
            retrieved_at=acquisition.acquired_at,
            sha256=sha,
            byte_size=size,
        )
        candidate = catalog.record_candidate(
            run["run_id"],
            acquisition=acquisition,
            adapter_version="fixture",
            status="incomplete",
            validation_status="validated",
            coverage_status="partial",
            observation_status="incomplete_source",
            validation={"archive_valid": True},
        )
        version = source_version_id("ssurgo", release, sha)
        assert candidate["version_id"] == version
        report = {
            "areasymbol": symbol,
            "areaname": f"Fixture {symbol}",
            "artifact_path": str(raw),
            "artifact_sha256": sha,
            "artifact_size_bytes": size,
            "batch_id": f"batch-{symbol}",
            "candidate_id": candidate["candidate_id"],
            "component_count": 1,
            "feature_count": 1,
            "idempotent": True,
            "ingestion_run_id": run["run_id"],
            "map_unit_count": 1,
            "original_invalid_count": 0,
            "repaired_accepted_count": 0,
            "quarantined_count": 0,
            "provider_release": release,
            "report_path": str(report_dir / f"{symbol}.json"),
            "source_snapshot_id": f"ssurgo-package:{symbol}",
            "source_version_id": version,
            "source_url": acquisition.source_url,
            "staging_status": "complete",
            "validation_status": "validated",
        }
        report_path = report_dir / f"{symbol}.json"
        write_json(report_path, report)
        package_reports.append(f"packages/{symbol}.json")
        package_candidates.append(
            {
                "candidate_id": candidate["candidate_id"],
                "ingestion_run_id": run["run_id"],
                "source_version_id": version,
            }
        )

    audit_path = root / "ssurgo" / "audit.json"
    qa_path = root / "ssurgo" / "qa.json"
    write_json(audit_path, {"package_count": 19, "geometry_diagnostics": []})
    write_json(qa_path, {"package_count": 19, "passed_package_count": 19})
    aggregate_path = report_dir.parent / "aggregate.json"
    write_json(
        aggregate_path,
        {
            "active_source_version_created": False,
            "area_crs": "EPSG:5070",
            "component_count": 7404,
            "feature_count": 123196,
            "limitations": [],
            "map_unit_count": 1878,
            "original_invalid_count": 10,
            "package_count": 19,
            "packages": package_reports,
            "postgis_staging_only": True,
            "quarantined_count": 0,
            "raw_packages_unchanged": True,
            "repaired_accepted_count": 10,
            "source_candidates_unchanged": True,
            "source_id": "ssurgo",
            "staging_run_id": "staging-fixture",
            "status": "completed",
        },
    )
    aggregate_sha, _ = _digest(aggregate_path)
    audit_sha, _ = _digest(audit_path)
    qa_sha, _ = _digest(qa_path)
    write_json(
        root / "manifest.json",
        {
            "artifacts": [],
            "ssurgo_regional_discrepancy_audit": {
                "latest_aggregate_report": str(audit_path),
                "aggregate_report_sha256": audit_sha,
            },
            "ssurgo_regional_qa": {
                "latest_aggregate_report": str(qa_path),
            },
            "ssurgo_regional_staging": {
                "latest_aggregate_report": str(aggregate_path),
                "aggregate_report_sha256": aggregate_sha,
            },
        },
    )
    return aggregate_path


def test_materialization_records_complete_lineage_without_activation(tmp_path: Path) -> None:
    _make_fixture(tmp_path)
    result = materialize_staged_ssurgo_candidate(tmp_path)

    candidate = result["candidate"]
    assert result["idempotent"] is False
    assert candidate["status"] == "incomplete"
    assert candidate["validation_status"] == "conditionally_validated"
    assert candidate["coverage_status"] == "partial"
    assert candidate["promotion_status"] == "not_promoted"
    assert candidate["validation"]["staging_metrics"]["soilmu_a_features"] == 123196
    assert len(candidate["validation"]["lineage"]["package_candidates"]) == 19
    assert len(candidate["validation"]["lineage"]["package_reports"]) == 19
    assert result["synthetic_source_snapshot_id"] == "ssurgo-regional-staging:staging-fixture"
    assert SQLiteSourceRepository(tmp_path).get_active("ssurgo") is None


def test_materialization_is_idempotent_and_checksum_protected(tmp_path: Path) -> None:
    aggregate_path = _make_fixture(tmp_path)
    first = materialize_staged_ssurgo_candidate(tmp_path)
    run_count = len(SQLiteSourceRepository(tmp_path).list_runs("ssurgo"))
    second = materialize_staged_ssurgo_candidate(tmp_path)
    assert second["idempotent"] is True
    assert second["candidate"]["candidate_id"] == first["candidate"]["candidate_id"]
    assert len(SQLiteSourceRepository(tmp_path).list_runs("ssurgo")) == run_count

    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["feature_count"] = 1
    write_json(aggregate_path, aggregate)
    with pytest.raises(ValueError, match="checksum mismatch"):
        materialize_staged_ssurgo_candidate(tmp_path)
    assert SQLiteSourceRepository(tmp_path).get_active("ssurgo") is None


def test_failed_validation_does_not_create_an_active_version(tmp_path: Path) -> None:
    aggregate_path = _make_fixture(tmp_path)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["quarantined_count"] = 1
    write_json(aggregate_path, aggregate)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["ssurgo_regional_staging"]["aggregate_report_sha256"] = _digest(aggregate_path)[0]
    write_json(tmp_path / "manifest.json", manifest)

    with pytest.raises(ValueError, match="quarantined_count"):
        materialize_staged_ssurgo_candidate(tmp_path)
    catalog = SQLiteSourceRepository(tmp_path)
    assert catalog.get_active("ssurgo") is None
    assert len(catalog.list_versions("ssurgo")) == 19
