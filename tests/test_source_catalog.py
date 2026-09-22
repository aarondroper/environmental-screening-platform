from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from environmental_screening_platform.adapters import ProviderData
from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.ingestion import ingest_source, retry_ingestion
from environmental_screening_platform.models import (
    Acquisition,
    AttemptStatus,
    Coverage,
    Maturity,
    Observation,
    SourceResult,
    source_version_id,
)


def acquired_fixture(root: Path, body: bytes, release: str = "fixture-v1") -> Acquisition:
    digest = hashlib.sha256(body).hexdigest()
    artifact = root / "raw" / "fixture" / f"{digest}.bin"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(body)
    return Acquisition(
        source_id="census_boundary",
        provider="fixture provider",
        release=release,
        source_url="https://provider.example/data?release=v1",
        acquired_at="2026-09-22T12:00:00+00:00",
        media_type="application/octet-stream",
        raw_path=str(artifact),
        size_bytes=len(body),
        sha256=digest,
        terms_url="https://provider.example/terms",
        attempts=1,
        request_parameters={"release": release},
    )


def make_candidate(
    repo: SQLiteSourceRepository,
    root: Path,
    *,
    body: bytes,
    source_id: str = "census_boundary",
    status: str = "validated",
    validation_status: str = "validated",
    coverage_status: str = "complete",
    observation_status: str = "data_observed",
    validation: dict[str, Any] | None = None,
    retry_of: str | None = None,
    release: str = "fixture-v1",
) -> dict[str, Any]:
    run = repo.begin_run(
        source_id=source_id,
        requested_url="https://provider.example/data",
        adapter_version="test-adapter-1",
        retry_of=retry_of,
    )
    acquisition = acquired_fixture(root, body, release=release)
    repo.record_attempt(
        run["run_id"],
        status="acquired",
        requested_url="https://provider.example/data",
        actual_url=acquisition.source_url,
        retrieved_at=acquisition.acquired_at,
        sha256=acquisition.sha256,
        byte_size=acquisition.size_bytes,
        transport_attempts=acquisition.attempts,
        details={"release": acquisition.release, "terms_url": acquisition.terms_url},
    )
    return repo.record_candidate(
        run["run_id"],
        acquisition=acquisition,
        adapter_version="test-adapter-1",
        status=status,
        validation_status=validation_status,
        coverage_status=coverage_status,
        observation_status=observation_status,
        validation=validation or {"geometry_count": 3, "quarantined_count": 0},
    )


def test_candidate_ingestion_records_complete_provenance_then_promotes(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)

    def acquire(source_id, root, _aoi, callback):
        artifact = acquired_fixture(root, b"validated boundary bytes")
        callback(artifact)
        result = SourceResult(
            source_id=source_id,
            validation_status=Maturity.VALIDATED,
            validation_scope="fixture scope",
            coverage_status=Coverage.COMPLETE,
            observation_status=Observation.DATA_OBSERVED,
            product_status="fixture release",
            attempt_status=AttemptStatus.VALIDATED,
            metrics={"feature_count": 3},
            provenance=artifact.to_dict(),
        )
        return ProviderData(result=result)

    output = ingest_source("census_boundary", tmp_path, repository=repo, acquirer=acquire)
    candidate = output["candidate"]
    assert output["run"]["status"] == "validated"
    assert candidate["status"] == "validated"
    assert candidate["sha256"] == hashlib.sha256(b"validated boundary bytes").hexdigest()
    assert candidate["byte_size"] == len(b"validated boundary bytes")
    assert candidate["provider_release"] == "fixture-v1"
    assert candidate["source_url"] == "https://provider.example/data?release=v1"
    assert candidate["terms_url"] == "https://provider.example/terms"
    assert candidate["adapter_version"] == "0.1.0"
    assert candidate["version_id"] == source_version_id(
        "census_boundary", "fixture-v1", hashlib.sha256(b"validated boundary bytes").hexdigest()
    )
    assert candidate["validated_at"] is not None
    assert candidate["validation"]["metrics"] == {"feature_count": 3}
    assert len(repo.list_runs("census_boundary")) == 1
    assert repo.get_active("census_boundary") is None
    assert candidate["acquisition_attempts"][0]["status"] == "acquired"
    assert candidate["acquisition_attempts"][0]["sha256"] == candidate["sha256"]
    reopened = SQLiteSourceRepository(tmp_path)
    assert reopened.get_candidate(candidate["candidate_id"])["sha256"] == candidate["sha256"]

    decision = reopened.promote(candidate["candidate_id"])
    assert decision["decision"] == "promoted"
    active = reopened.get_active("census_boundary")
    assert active is not None and active["version_id"] == candidate["version_id"]
    assert reopened.promote(candidate["candidate_id"])["idempotent"] is True


def test_failed_validation_and_failed_retry_preserve_prior_active(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    active = make_candidate(repo, tmp_path, body=b"known good")
    repo.promote(active["candidate_id"])
    active_version = repo.get_active("census_boundary")
    assert active_version is not None
    original_version = active_version["version_id"]

    failed = make_candidate(
        repo,
        tmp_path,
        body=b"invalid candidate",
        status="failed",
        validation_status="failed",
        coverage_status="unavailable",
        observation_status="unavailable",
        validation={"stage": "schema", "quarantined_count": 0},
    )
    assert failed["status"] == "failed"
    rejected = repo.promote(failed["candidate_id"])
    assert rejected["decision"] == "rejected"
    current_version = repo.get_active("census_boundary")
    assert current_version is not None and current_version["version_id"] == original_version

    retry_run = repo.begin_run(
        source_id="census_boundary",
        requested_url="https://provider.example/data",
        adapter_version="test-adapter-1",
        retry_of=failed["run_id"],
    )
    repo.finish_run(retry_run["run_id"], "failed", "provider timeout")
    assert repo.get_run(failed["run_id"])["status"] == "failed"
    assert repo.get_run(retry_run["run_id"])["attempt_number"] == 2
    current_version = repo.get_active("census_boundary")
    assert current_version is not None and current_version["version_id"] == original_version


def test_acquired_but_invalid_payload_remains_a_failed_candidate(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)

    def fails_validation(source_id, root, _aoi, callback):
        acquired = acquired_fixture(root, b"downloaded but malformed")
        callback(acquired)
        staged = repo.list_candidates("census_boundary")[0]
        assert staged["status"] == "incomplete"
        assert staged["validation_status"] == "not_assessed"
        assert staged["run_status"] == "running"
        raise ValueError("fixture parser rejected schema")

    outcome = ingest_source("census_boundary", tmp_path, repository=repo, acquirer=fails_validation)
    candidate = outcome["candidate"]
    assert outcome["run"]["status"] == "failed"
    assert candidate["status"] == "failed"
    assert candidate["artifact_path"] is not None
    assert candidate["sha256"] == hashlib.sha256(b"downloaded but malformed").hexdigest()
    assert candidate["acquisition_attempts"][0]["status"] == "acquired"
    assert candidate["error"]["message"] == "ValueError: fixture parser rejected schema"
    assert repo.promote(candidate["candidate_id"])["decision"] == "rejected"


def test_duplicate_ingestion_reuses_checksum_version_but_keeps_run_history(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    one = make_candidate(repo, tmp_path, body=b"same provider bytes")
    two = make_candidate(repo, tmp_path, body=b"same provider bytes")
    assert one["version_id"] == two["version_id"]
    assert len(repo.list_versions("census_boundary")) == 1
    assert len(repo.list_runs("census_boundary")) == 2
    assert one["candidate_id"] != two["candidate_id"]
    first_decision = repo.promote(one["candidate_id"])
    active_before_duplicate_promotion = repo.get_active("census_boundary")
    duplicate_decision = repo.promote(two["candidate_id"])
    active_after_duplicate_promotion = repo.get_active("census_boundary")
    assert first_decision["decision"] == duplicate_decision["decision"] == "promoted"
    assert (
        active_before_duplicate_promotion["promoted_at"]
        == active_after_duplicate_promotion["promoted_at"]
    )


def test_same_bytes_under_a_new_release_are_a_distinct_source_version(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    old_release = make_candidate(repo, tmp_path, body=b"release payload", release="2025")
    new_release = make_candidate(repo, tmp_path, body=b"release payload", release="2026")
    assert old_release["sha256"] == new_release["sha256"]
    assert old_release["version_id"] != new_release["version_id"]
    assert len(repo.list_versions("census_boundary")) == 2


@pytest.mark.parametrize(
    ("status", "validation_status", "coverage", "observation", "quarantines"),
    [
        ("quarantined", "conditionally_validated", "unknown", "geometry_quarantined", 2),
        ("blocked", "access_blocked", "unavailable", "unavailable", 0),
        ("incomplete", "validated", "partial", "incomplete_source", 0),
    ],
)
def test_quarantined_blocked_and_incomplete_candidates_are_queryable_not_promotable(
    tmp_path: Path,
    status: str,
    validation_status: str,
    coverage: str,
    observation: str,
    quarantines: int,
) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    candidate = make_candidate(
        repo,
        tmp_path,
        body=f"{status} bytes".encode(),
        status=status,
        validation_status=validation_status,
        coverage_status=coverage,
        observation_status=observation,
        validation={"quarantined_count": quarantines},
    )
    decision = repo.promote(candidate["candidate_id"])
    assert decision["decision"] == "rejected"
    stored_candidate = repo.get_candidate(candidate["candidate_id"])
    assert stored_candidate is not None and stored_candidate["status"] == status
    assert repo.get_active("census_boundary") is None


def test_checksum_mismatch_is_rejected_before_version_recording(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    run = repo.begin_run(
        source_id="census_boundary",
        requested_url="https://provider.example/data",
        adapter_version="test-adapter-1",
    )
    artifact = acquired_fixture(tmp_path, b"original")
    Path(artifact.raw_path).write_bytes(b"tampered")
    candidate = repo.record_candidate(
        run["run_id"],
        acquisition=artifact,
        adapter_version="test-adapter-1",
        status="validated",
        validation_status="validated",
        coverage_status="complete",
        observation_status="data_observed",
        validation={},
    )
    assert candidate["status"] == "failed"
    assert candidate["artifact_path"] == artifact.raw_path
    assert candidate["sha256"] == artifact.sha256
    assert "checksum or size" in candidate["error"]["message"]
    assert repo.list_versions("census_boundary") == []
    assert repo.get_run(run["run_id"])["status"] == "failed"


def test_promotion_rechecks_artifact_checksum_and_keeps_prior_active(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    first = make_candidate(repo, tmp_path, body=b"active source bytes")
    repo.promote(first["candidate_id"])
    active = repo.get_active("census_boundary")
    assert active is not None
    prior = active["version_id"]
    second = make_candidate(repo, tmp_path, body=b"next source bytes")
    Path(second["artifact_path"]).write_bytes(b"tampered bytes")
    rejected = repo.promote(second["candidate_id"])
    assert rejected["decision"] == "rejected"
    assert "checksum/version mismatch" in rejected["reason"]
    active = repo.get_active("census_boundary")
    assert active is not None and active["version_id"] == prior


def test_retry_command_creates_new_attempt_and_keeps_failed_candidate(tmp_path: Path) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    failed = make_candidate(
        repo,
        tmp_path,
        body=b"first attempt",
        status="failed",
        validation_status="failed",
        coverage_status="unavailable",
        observation_status="unavailable",
    )

    def still_fails(_source_id, _root, _aoi, _callback):
        raise RuntimeError("offline fixture")

    retried = retry_ingestion(failed["run_id"], tmp_path, repository=repo, acquirer=still_fails)
    assert retried["run"]["retry_of"] == failed["run_id"]
    assert retried["run"]["attempt_number"] == 2
    assert retried["candidate"]["status"] == "failed"
    stored_candidate = repo.get_candidate(failed["candidate_id"])
    assert stored_candidate is not None and stored_candidate["status"] == "failed"


def test_selected_padus_and_fema_ingestion_outcomes_are_explicit_and_inactive(
    tmp_path: Path,
) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    padus = ingest_source("padus", tmp_path, repository=repo)
    fema = ingest_source("fema_nfhl", tmp_path, repository=repo)
    assert padus["candidate"]["status"] == "quarantined"
    assert padus["candidate"]["validation_status"] == "conditionally_validated"
    assert padus["candidate"]["validation"]["quarantined_count"] == 3
    assert fema["candidate"]["status"] == "blocked"
    assert fema["candidate"]["validation_status"] == "access_blocked"
    assert fema["candidate"]["error"]["message"] == (
        "Selected source; provider access blocked; technical suitability and effective/pending sample validation incomplete."
    )
    padus_decision = repo.promote(padus["candidate"]["candidate_id"])
    assert padus_decision["decision"] == "rejected"
    assert repo.promote(padus["candidate"]["candidate_id"])["idempotent"] is True
    assert repo.promote(fema["candidate"]["candidate_id"])["decision"] == "rejected"
    assert repo.get_active("padus") is None
    assert repo.get_active("fema_nfhl") is None
