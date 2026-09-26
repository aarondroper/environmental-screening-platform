"""Local transactional repository for source ingestion and promotion metadata.

The repository contract is backend-neutral. SQLite is only the current local
implementation; canonical spatial data and hosted persistence remain PostGIS work.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote
from uuid import uuid4

from .adapters import NLCD_CLASSES, NLCD_NATIVE_CRS, NLCD_NATIVE_NODATA, NLCD_NATIVE_RESOLUTION_M
from .aoi import AoiContext
from .models import MATURITY, Acquisition, source_version_id, utc_now
from .three_dep import THREEDEP_NATIVE_CRS, THREEDEP_NODATA, THREEDEP_NOMINAL_ARC_SECONDS


class SourceRepository(Protocol):
    """Persistence operations needed by ingestion and explicit promotion."""

    def begin_run(
        self,
        *,
        source_id: str,
        requested_url: str,
        adapter_version: str,
        project_id: str | None = None,
        aoi_id: str | None = None,
        aoi_revision: int | None = None,
        retry_of: str | None = None,
    ) -> dict[str, Any]: ...

    def record_attempt(
        self,
        run_id: str,
        *,
        status: str,
        requested_url: str,
        actual_url: str | None = None,
        retrieved_at: str | None = None,
        sha256: str | None = None,
        byte_size: int | None = None,
        transport_attempts: int = 0,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]: ...

    def record_candidate(
        self,
        run_id: str,
        *,
        acquisition: Acquisition | None,
        adapter_version: str,
        status: str,
        validation_status: str,
        coverage_status: str,
        observation_status: str,
        validation: dict[str, Any],
        error: str | None = None,
        finalize: bool = True,
    ) -> dict[str, Any]: ...

    def finalize_candidate(
        self,
        candidate_id: str,
        *,
        status: str,
        validation_status: str,
        coverage_status: str,
        observation_status: str,
        validation: dict[str, Any],
        error: str | None = None,
    ) -> dict[str, Any]: ...

    def record_coverage_validation(
        self,
        candidate_id: str,
        *,
        coverage_status: str,
        observation_status: str,
        validation: dict[str, Any],
    ) -> dict[str, Any]: ...

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None: ...

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    def list_attempts(self, run_id: str) -> list[dict[str, Any]]: ...

    def promote(
        self,
        candidate_id: str,
        *,
        project_id: str | None = None,
        aoi_id: str | None = None,
        aoi_revision: int | None = None,
    ) -> dict[str, Any]: ...

    def get_active(
        self,
        source_id: str,
        *,
        project_id: str | None = None,
        aoi_id: str | None = None,
        aoi_revision: int | None = None,
    ) -> dict[str, Any] | None: ...

    def create_job_snapshots(
        self,
        *,
        job_id: str,
        aoi_id: str,
        aoi_revision: int,
        source_ids: list[str],
        project_id: str | None = None,
        require_aoi_scoped_active: bool = False,
        aoi_geometry_sha256: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_job_snapshots(self, job_id: str) -> list[dict[str, Any]]: ...

    def create_aoi_ingestion_run(
        self,
        *,
        parent_run_id: str,
        project_id: str,
        aoi_id: str,
        aoi_revision: int,
        aoi_geometry_sha256: str,
        source_ids: list[str],
        limits: dict[str, Any],
        plan_id: str,
        plan_path: str,
        status: str,
        summary: dict[str, Any],
        retry_of: str | None = None,
    ) -> dict[str, Any]: ...

    def update_aoi_ingestion_run(
        self, parent_run_id: str, *, status: str, summary: dict[str, Any]
    ) -> dict[str, Any]: ...

    def get_aoi_ingestion_run(self, parent_run_id: str) -> dict[str, Any] | None: ...

    def list_aoi_ingestion_runs(
        self, *, project_id: str, aoi_id: str, aoi_revision: int
    ) -> list[dict[str, Any]]: ...

    def list_promotion_decisions(
        self, *, candidate_ids: list[str] | None = None
    ) -> list[dict[str, Any]]: ...

    def list_active_aoi_versions(
        self, *, project_id: str, aoi_id: str, aoi_revision: int
    ) -> list[dict[str, Any]]: ...


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


class SQLiteSourceRepository:
    """SQLite catalog persisted under an external data directory."""

    def __init__(self, data_root: Path, *, read_only: bool = False):
        self.data_root = data_root.resolve()
        repository_root = Path(__file__).resolve().parents[2]
        if self.data_root == repository_root or repository_root in self.data_root.parents:
            raise ValueError("Source catalog must be stored outside the project repository")
        self.path = self.data_root / "catalog" / "sources.sqlite3"
        self._read_only = read_only
        if read_only:
            if not self.path.exists():
                raise FileNotFoundError(f"Source catalog does not exist: {self.path}")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self._read_only:
            uri = f"file:{quote(str(self.path), safe='/')}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)
        else:
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _database(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._database() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_versions (
                    version_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_release TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL CHECK(length(sha256)=64),
                    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
                    artifact_path TEXT NOT NULL,
                    terms_url TEXT NOT NULL,
                    adapter_version TEXT NOT NULL,
                    promotion_status TEXT NOT NULL DEFAULT 'candidate'
                        CHECK(promotion_status IN ('candidate','active','superseded')),
                    created_at TEXT NOT NULL,
                    UNIQUE(source_id, provider_release, sha256)
                );
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('running','validated','incomplete','failed','blocked')),
                    requested_url TEXT NOT NULL,
                    project_id TEXT,
                    aoi_id TEXT,
                    aoi_revision INTEGER,
                    adapter_version TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL CHECK(attempt_number > 0),
                    retry_of TEXT REFERENCES ingestion_runs(run_id),
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_json TEXT
                );
                CREATE TABLE IF NOT EXISTS acquisition_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
                    status TEXT NOT NULL CHECK(status IN ('acquired','failed','blocked')),
                    requested_url TEXT NOT NULL,
                    actual_url TEXT,
                    attempted_at TEXT NOT NULL,
                    retrieved_at TEXT,
                    sha256 TEXT,
                    byte_size INTEGER,
                    transport_attempts INTEGER NOT NULL DEFAULT 0,
                    details_json TEXT NOT NULL,
                    error_json TEXT
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE REFERENCES ingestion_runs(run_id),
                    source_id TEXT NOT NULL,
                    version_id TEXT REFERENCES source_versions(version_id),
                    status TEXT NOT NULL CHECK(status IN
                        ('validated','conditionally_validated','incomplete','failed','blocked','quarantined')),
                    artifact_path TEXT,
                    sha256 TEXT,
                    byte_size INTEGER CHECK(byte_size IS NULL OR byte_size >= 0),
                    validation_status TEXT NOT NULL,
                    coverage_status TEXT NOT NULL,
                    observation_status TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    error_json TEXT,
                    validated_at TEXT,
                    promotion_status TEXT NOT NULL DEFAULT 'not_promoted'
                        CHECK(promotion_status IN ('not_promoted','promoted','superseded','rejected')),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS promotion_decisions (
                    decision_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(candidate_id),
                    source_id TEXT NOT NULL,
                    version_id TEXT,
                    previous_version_id TEXT,
                    project_id TEXT,
                    aoi_id TEXT,
                    aoi_revision INTEGER,
                    aoi_geometry_sha256 TEXT,
                    decision TEXT NOT NULL CHECK(decision IN ('promoted','rejected')),
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS active_versions (
                    source_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL REFERENCES source_versions(version_id),
                    promoted_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS active_aoi_versions (
                    source_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    aoi_id TEXT NOT NULL,
                    aoi_revision INTEGER NOT NULL,
                    aoi_geometry_sha256 TEXT NOT NULL CHECK(length(aoi_geometry_sha256)=64),
                    version_id TEXT NOT NULL REFERENCES source_versions(version_id),
                    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                    promoted_at TEXT NOT NULL,
                    PRIMARY KEY(source_id, project_id, aoi_id, aoi_revision)
                );
                CREATE INDEX IF NOT EXISTS idx_active_aoi_version_lookup
                    ON active_aoi_versions(source_id, project_id, aoi_id, aoi_revision);
                CREATE TABLE IF NOT EXISTS job_source_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    aoi_id TEXT NOT NULL,
                    aoi_revision INTEGER NOT NULL,
                    source_id TEXT NOT NULL,
                    version_id TEXT REFERENCES source_versions(version_id),
                    candidate_id TEXT REFERENCES candidates(candidate_id),
                    ingestion_run_id TEXT REFERENCES ingestion_runs(run_id),
                    source_maturity TEXT NOT NULL,
                    coverage_status TEXT NOT NULL,
                    observation_status TEXT NOT NULL,
                    snapshot_status TEXT NOT NULL CHECK(snapshot_status IN
                        ('active','unknown','unavailable','incomplete','blocked','quarantined')),
                    reason TEXT,
                    snapshot_at TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    UNIQUE(job_id, source_id)
                );
                CREATE INDEX IF NOT EXISTS idx_job_source_snapshot
                    ON job_source_snapshots(job_id, source_id);
                CREATE TRIGGER IF NOT EXISTS immutable_job_source_snapshots_update
                    BEFORE UPDATE ON job_source_snapshots
                    BEGIN SELECT RAISE(ABORT, 'job source snapshots are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_job_source_snapshots_delete
                    BEFORE DELETE ON job_source_snapshots
                    BEGIN SELECT RAISE(ABORT, 'job source snapshots are immutable'); END;
                CREATE INDEX IF NOT EXISTS idx_ingestion_source_time
                    ON ingestion_runs(source_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_candidate_source_status
                    ON candidates(source_id, status, created_at DESC);
                CREATE TABLE IF NOT EXISTS aoi_ingestion_runs (
                    parent_run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    aoi_id TEXT NOT NULL,
                    aoi_revision INTEGER NOT NULL,
                    aoi_geometry_sha256 TEXT NOT NULL CHECK(length(aoi_geometry_sha256)=64),
                    source_ids_json TEXT NOT NULL,
                    limits_json TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    plan_path TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('planned','running','completed','partial','failed','dry_run')),
                    retry_of TEXT REFERENCES aoi_ingestion_runs(parent_run_id),
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    summary_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_aoi_ingestion_runs_time
                    ON aoi_ingestion_runs(started_at DESC);
                """
            )
            promotion_columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(promotion_decisions)")
            }
            for column, column_type in (
                ("project_id", "TEXT"),
                ("aoi_id", "TEXT"),
                ("aoi_revision", "INTEGER"),
                ("aoi_geometry_sha256", "TEXT"),
            ):
                if column not in promotion_columns:
                    db.execute(f"ALTER TABLE promotion_decisions ADD COLUMN {column} {column_type}")

    def create_aoi_ingestion_run(
        self,
        *,
        parent_run_id: str,
        project_id: str,
        aoi_id: str,
        aoi_revision: int,
        aoi_geometry_sha256: str,
        source_ids: list[str],
        limits: dict[str, Any],
        plan_id: str,
        plan_path: str,
        status: str,
        summary: dict[str, Any],
        retry_of: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"planned", "running", "dry_run"}:
            raise ValueError("New AOI ingestion runs must be planned, running, or dry_run")
        with self._transaction() as db:
            db.execute(
                """INSERT INTO aoi_ingestion_runs
                (parent_run_id,project_id,aoi_id,aoi_revision,aoi_geometry_sha256,
                 source_ids_json,limits_json,plan_id,plan_path,status,retry_of,started_at,summary_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    parent_run_id,
                    project_id,
                    aoi_id,
                    aoi_revision,
                    aoi_geometry_sha256,
                    _json(source_ids),
                    _json(limits),
                    plan_id,
                    plan_path,
                    status,
                    retry_of,
                    utc_now(),
                    _json(summary),
                ),
            )
        return self.get_aoi_ingestion_run(parent_run_id) or {}

    def update_aoi_ingestion_run(
        self, parent_run_id: str, *, status: str, summary: dict[str, Any]
    ) -> dict[str, Any]:
        if status not in {"planned", "running", "completed", "partial", "failed", "dry_run"}:
            raise ValueError(f"Invalid AOI ingestion run status: {status}")
        with self._transaction() as db:
            row = db.execute(
                "SELECT status FROM aoi_ingestion_runs WHERE parent_run_id=?",
                (parent_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown AOI ingestion run: {parent_run_id}")
            db.execute(
                """UPDATE aoi_ingestion_runs
                   SET status=?, finished_at=?, summary_json=?
                   WHERE parent_run_id=?""",
                (
                    status,
                    utc_now() if status in {"completed", "partial", "failed", "dry_run"} else None,
                    _json(summary),
                    parent_run_id,
                ),
            )
        return self.get_aoi_ingestion_run(parent_run_id) or {}

    def get_aoi_ingestion_run(self, parent_run_id: str) -> dict[str, Any] | None:
        with self._database() as db:
            row = db.execute(
                "SELECT * FROM aoi_ingestion_runs WHERE parent_run_id=?",
                (parent_run_id,),
            ).fetchone()
        return self._decode_aoi_ingestion_row(row)

    @staticmethod
    def _decode_aoi_ingestion_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        result = _decode(row)
        if result is None:
            return None
        result["source_ids"] = json.loads(result.pop("source_ids_json"))
        result["limits"] = json.loads(result.pop("limits_json"))
        result["summary"] = json.loads(result.pop("summary_json"))
        return result

    def list_aoi_ingestion_runs(
        self, *, project_id: str, aoi_id: str, aoi_revision: int
    ) -> list[dict[str, Any]]:
        with self._database() as db:
            rows = db.execute(
                """SELECT * FROM aoi_ingestion_runs
                   WHERE project_id=? AND aoi_id=? AND aoi_revision=?
                   ORDER BY started_at, parent_run_id""",
                (project_id, aoi_id, aoi_revision),
            ).fetchall()
        return [decoded for row in rows if (decoded := self._decode_aoi_ingestion_row(row))]

    def begin_run(
        self,
        *,
        source_id: str,
        requested_url: str,
        adapter_version: str,
        project_id: str | None = None,
        aoi_id: str | None = None,
        aoi_revision: int | None = None,
        retry_of: str | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        with self._transaction() as db:
            parent = (
                db.execute(
                    "SELECT attempt_number, source_id, status FROM ingestion_runs WHERE run_id=?",
                    (retry_of,),
                ).fetchone()
                if retry_of
                else None
            )
            if retry_of:
                if parent is None or parent["source_id"] != source_id:
                    raise ValueError("Retry parent must be an existing run for the same source")
                if parent["status"] not in {"failed", "incomplete", "blocked"}:
                    raise ValueError("Only failed, incomplete, or blocked runs may be retried")
            attempt_number = int(parent["attempt_number"]) + 1 if parent else 1
            started_at = utc_now()
            db.execute(
                """INSERT INTO ingestion_runs
                (run_id,source_id,status,requested_url,project_id,aoi_id,aoi_revision,
                 adapter_version,attempt_number,retry_of,started_at)
                VALUES (?,?, 'running',?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    source_id,
                    requested_url,
                    project_id,
                    aoi_id,
                    aoi_revision,
                    adapter_version,
                    attempt_number,
                    retry_of,
                    started_at,
                ),
            )
        return self.get_run(run_id) or {}

    def record_attempt(
        self,
        run_id: str,
        *,
        status: str,
        requested_url: str,
        actual_url: str | None = None,
        retrieved_at: str | None = None,
        sha256: str | None = None,
        byte_size: int | None = None,
        transport_attempts: int = 0,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        attempt_id = str(uuid4())
        with self._transaction() as db:
            db.execute(
                """INSERT INTO acquisition_attempts
                (attempt_id,run_id,status,requested_url,actual_url,attempted_at,retrieved_at,sha256,
                 byte_size,transport_attempts,details_json,error_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    attempt_id,
                    run_id,
                    status,
                    requested_url,
                    actual_url,
                    utc_now(),
                    retrieved_at,
                    sha256,
                    byte_size,
                    transport_attempts,
                    _json(details or {}),
                    _json({"message": error}) if error else None,
                ),
            )
            row = db.execute(
                "SELECT * FROM acquisition_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
        result = dict(row)
        result["details"] = json.loads(result.pop("details_json"))
        error_json = result.pop("error_json")
        result["error"] = json.loads(error_json) if error_json else None
        return result

    def record_candidate(
        self,
        run_id: str,
        *,
        acquisition: Acquisition | None,
        adapter_version: str,
        status: str,
        validation_status: str,
        coverage_status: str,
        observation_status: str,
        validation: dict[str, Any],
        error: str | None = None,
        finalize: bool = True,
    ) -> dict[str, Any]:
        candidate_id = str(uuid4())
        version_id = None
        artifact_path: str | None = None
        expected_hash: str | None = None
        expected_size: int | None = None
        integrity_error: str | None = None
        with self._transaction() as db:
            run = db.execute("SELECT * FROM ingestion_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["status"] != "running":
                raise ValueError("Candidate requires a running ingestion run")
            if acquisition is not None:
                if acquisition.source_id != run["source_id"]:
                    raise ValueError("Acquisition source identifier does not match ingestion run")
                artifact = Path(acquisition.raw_path).resolve()
                artifact_path = str(artifact)
                expected_hash = acquisition.sha256
                expected_size = acquisition.size_bytes
                try:
                    artifact.relative_to(self.data_root)
                except ValueError as exc:
                    raise ValueError(
                        "Candidate artifact must be inside the external data directory"
                    ) from exc
                try:
                    actual_hash, actual_size = _hash_file(artifact)
                except OSError as exc:
                    integrity_error = f"Candidate artifact is missing or unreadable: {exc}"
                else:
                    if actual_hash != acquisition.sha256 or actual_size != acquisition.size_bytes:
                        integrity_error = "Candidate artifact checksum or size does not match acquisition provenance"
                    else:
                        version_id = source_version_id(
                            acquisition.source_id, acquisition.release, actual_hash
                        )
                        existing = db.execute(
                            "SELECT * FROM source_versions WHERE version_id=?", (version_id,)
                        ).fetchone()
                        if existing is None:
                            db.execute(
                                """INSERT INTO source_versions
                                (version_id,source_id,provider,provider_release,source_url,retrieved_at,media_type,
                                 sha256,byte_size,artifact_path,terms_url,adapter_version,promotion_status,created_at)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'candidate',?)""",
                                (
                                    version_id,
                                    acquisition.source_id,
                                    acquisition.provider,
                                    acquisition.release,
                                    acquisition.source_url,
                                    acquisition.acquired_at,
                                    acquisition.media_type,
                                    actual_hash,
                                    actual_size,
                                    str(artifact),
                                    acquisition.terms_url,
                                    adapter_version,
                                    utc_now(),
                                ),
                            )
                        elif (
                            existing["sha256"] != actual_hash
                            or existing["byte_size"] != actual_size
                            or Path(existing["artifact_path"]).resolve() != artifact
                        ):
                            integrity_error = (
                                "Immutable source-version identity conflicts with stored provenance"
                            )
            stored_status = "failed" if integrity_error else status
            stored_validation_status = "failed" if integrity_error else validation_status
            stored_coverage_status = "unknown" if integrity_error else coverage_status
            stored_observation_status = (
                "incomplete_source" if integrity_error else observation_status
            )
            stored_validation = dict(validation)
            if integrity_error:
                stored_validation["integrity_error"] = integrity_error
                error = integrity_error
            db.execute(
                """INSERT INTO candidates
                (candidate_id,run_id,source_id,version_id,status,artifact_path,sha256,byte_size,
                 validation_status,coverage_status,observation_status,validation_json,error_json,
                 validated_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    candidate_id,
                    run_id,
                    run["source_id"],
                    version_id,
                    stored_status,
                    artifact_path,
                    expected_hash,
                    expected_size,
                    stored_validation_status,
                    stored_coverage_status,
                    stored_observation_status,
                    _json(stored_validation),
                    _json({"message": error}) if error else None,
                    utc_now() if finalize else None,
                    utc_now(),
                ),
            )
            if finalize:
                self._finish_run_in_transaction(db, run_id, stored_status, error)
        return self.get_candidate(candidate_id) or {}

    def finalize_candidate(
        self,
        candidate_id: str,
        *,
        status: str,
        validation_status: str,
        coverage_status: str,
        observation_status: str,
        validation: dict[str, Any],
        error: str | None = None,
    ) -> dict[str, Any]:
        with self._transaction() as db:
            candidate = db.execute(
                """SELECT c.run_id,c.artifact_path,c.sha256,c.byte_size,r.status AS run_status
                   FROM candidates c JOIN ingestion_runs r USING(run_id)
                   WHERE c.candidate_id=?""",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise KeyError(f"Unknown candidate: {candidate_id}")
            if candidate["run_status"] != "running":
                raise ValueError("Only a candidate from a running ingestion may be finalized")
            integrity_error = None
            if candidate["artifact_path"]:
                artifact = Path(candidate["artifact_path"]).resolve()
                try:
                    artifact.relative_to(self.data_root)
                    digest, size = _hash_file(artifact)
                except (OSError, ValueError):
                    integrity_error = (
                        "Candidate artifact is missing or outside the external data directory"
                    )
                else:
                    if digest != candidate["sha256"] or size != candidate["byte_size"]:
                        integrity_error = (
                            "Candidate artifact checksum/version mismatch during validation"
                        )
            stored_status = "failed" if integrity_error else status
            stored_validation_status = "failed" if integrity_error else validation_status
            stored_coverage_status = "unknown" if integrity_error else coverage_status
            stored_observation_status = (
                "incomplete_source" if integrity_error else observation_status
            )
            stored_validation = dict(validation)
            if integrity_error:
                stored_validation["integrity_error"] = integrity_error
                error = integrity_error
            db.execute(
                """UPDATE candidates SET status=?,validation_status=?,coverage_status=?,
                   observation_status=?,validation_json=?,error_json=?,validated_at=?
                   WHERE candidate_id=?""",
                (
                    stored_status,
                    stored_validation_status,
                    stored_coverage_status,
                    stored_observation_status,
                    _json(stored_validation),
                    _json({"message": error}) if error else None,
                    utc_now(),
                    candidate_id,
                ),
            )
            self._finish_run_in_transaction(db, candidate["run_id"], stored_status, error)
        return self.get_candidate(candidate_id) or {}

    def record_coverage_validation(
        self,
        candidate_id: str,
        *,
        coverage_status: str,
        observation_status: str,
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        """Append a coverage QA result without changing candidate activation state."""
        with self._transaction() as db:
            row = db.execute(
                """SELECT c.*,r.status AS run_status
                   FROM candidates c JOIN ingestion_runs r USING(run_id)
                   WHERE c.candidate_id=?""",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown candidate: {candidate_id}")
            if row["source_id"] != "ssurgo":
                raise ValueError("Regional coverage validation is only defined for SSURGO")
            if row["promotion_status"] != "not_promoted":
                raise ValueError("Coverage validation cannot modify a promoted candidate")
            if row["status"] not in {"incomplete", "conditionally_validated"}:
                raise ValueError("Coverage validation requires an inactive incomplete candidate")
            existing = json.loads(row["validation_json"])
            existing_coverage = existing.get("regional_coverage_validation")
            if existing_coverage is not None:
                prior_checksum = existing_coverage.get("aggregate_report_sha256")
                next_checksum = validation.get("aggregate_report_sha256")
                if prior_checksum != next_checksum:
                    same_report = existing_coverage.get("analysis_version") == validation.get(
                        "analysis_version"
                    ) and existing_coverage.get("aggregate_report") == validation.get(
                        "aggregate_report"
                    )
                    if not same_report:
                        raise ValueError(
                            "Candidate already has a different regional coverage validation"
                        )
                    merged = dict(existing)
                    merged["regional_coverage_validation"] = validation
                    db.execute(
                        """UPDATE candidates
                           SET coverage_status=?,observation_status=?,validation_json=?,validated_at=?
                           WHERE candidate_id=?""",
                        (
                            coverage_status,
                            observation_status,
                            _json(merged),
                            utc_now(),
                            candidate_id,
                        ),
                    )
                    return self._candidate(candidate_id, db) or {}
                return self._candidate(candidate_id, db) or {}
            merged = dict(existing)
            merged["regional_coverage_validation"] = validation
            db.execute(
                """UPDATE candidates
                   SET coverage_status=?,observation_status=?,validation_json=?,validated_at=?
                   WHERE candidate_id=?""",
                (
                    coverage_status,
                    observation_status,
                    _json(merged),
                    utc_now(),
                    candidate_id,
                ),
            )
        return self.get_candidate(candidate_id) or {}

    @staticmethod
    def _finish_run_in_transaction(
        db: sqlite3.Connection, run_id: str, candidate_status: str, error: str | None
    ) -> None:
        run_status = (
            "validated"
            if candidate_status == "validated"
            else "blocked"
            if candidate_status == "blocked"
            else "failed"
            if candidate_status == "failed"
            else "incomplete"
        )
        db.execute(
            "UPDATE ingestion_runs SET status=?, finished_at=?, error_json=? WHERE run_id=?",
            (run_status, utc_now(), _json({"message": error}) if error else None, run_id),
        )

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None:
        if status not in {"failed", "blocked", "incomplete"}:
            raise ValueError(
                "Runs without a candidate may only finish failed, blocked, or incomplete"
            )
        with self._transaction() as db:
            db.execute(
                "UPDATE ingestion_runs SET status=?, finished_at=?, error_json=? WHERE run_id=? AND status='running'",
                (status, utc_now(), _json({"message": error}) if error else None, run_id),
            )

    def _candidate(self, candidate_id: str, db: sqlite3.Connection) -> dict[str, Any] | None:
        row = db.execute(
            """SELECT c.*, v.provider, v.provider_release, v.source_url, v.retrieved_at,v.media_type,
                      v.sha256, v.byte_size, v.artifact_path, v.terms_url, v.adapter_version,
                      r.status AS run_status, r.project_id, r.aoi_id, r.aoi_revision,
                      r.requested_url, r.retry_of, r.adapter_version AS run_adapter_version
               FROM candidates c LEFT JOIN source_versions v ON v.version_id=c.version_id
               JOIN ingestion_runs r ON r.run_id=c.run_id WHERE c.candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["validation"] = json.loads(result.pop("validation_json"))
        error = result.pop("error_json")
        result["error"] = json.loads(error) if error else None
        run_adapter_version = result.pop("run_adapter_version")
        result["adapter_version"] = result["adapter_version"] or run_adapter_version
        result["acquisition_attempts"] = self.list_attempts(result["run_id"], db)
        return result

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._database() as db:
            return self._candidate(candidate_id, db)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._database() as db:
            row = db.execute("SELECT * FROM ingestion_runs WHERE run_id=?", (run_id,)).fetchone()
        result = _decode(row)
        if result is not None and result["error_json"]:
            result["error"] = json.loads(result.pop("error_json"))
        elif result is not None:
            result.pop("error_json")
            result["error"] = None
        return result

    def list_attempts(
        self, run_id: str, db: sqlite3.Connection | None = None
    ) -> list[dict[str, Any]]:
        if db is not None:
            rows = db.execute(
                "SELECT * FROM acquisition_attempts WHERE run_id=? ORDER BY attempted_at,attempt_id",
                (run_id,),
            ).fetchall()
        else:
            with self._database() as connection:
                rows = connection.execute(
                    "SELECT * FROM acquisition_attempts WHERE run_id=? ORDER BY attempted_at,attempt_id",
                    (run_id,),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            error = item.pop("error_json")
            item["error"] = json.loads(error) if error else None
            result.append(item)
        return result

    def list_runs(self, source_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM ingestion_runs"
        params: tuple[Any, ...] = ()
        if source_id:
            query += " WHERE source_id=?"
            params = (source_id,)
        query += " ORDER BY started_at DESC, run_id"
        with self._database() as db:
            rows = db.execute(query, params).fetchall()
        return [_normalize_json_columns(dict(row), {"error_json": "error"}) for row in rows]

    def list_versions(self, source_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM source_versions"
        params: tuple[Any, ...] = ()
        if source_id:
            query += " WHERE source_id=?"
            params = (source_id,)
        query += " ORDER BY source_id, created_at DESC, version_id"
        with self._database() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def list_candidates(
        self, source_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT candidate_id FROM candidates"
        filters: list[str] = []
        params: tuple[Any, ...] = ()
        if source_id:
            filters.append("source_id=?")
            params += (source_id,)
        if status:
            filters.append("status=?")
            params += (status,)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC, candidate_id"
        with self._database() as db:
            ids = [row[0] for row in db.execute(query, params).fetchall()]
            return [candidate for item in ids if (candidate := self._candidate(item, db))]

    def list_promotion_decisions(
        self, *, candidate_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM promotion_decisions"
        params: tuple[Any, ...] = ()
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            placeholders = ",".join("?" for _ in candidate_ids)
            query += f" WHERE candidate_id IN ({placeholders})"
            params = tuple(candidate_ids)
        query += " ORDER BY decided_at, decision_id"
        with self._database() as db:
            result: list[dict[str, Any]] = []
            for row in db.execute(query, params).fetchall():
                decoded = _decode(row)
                if decoded is not None:
                    result.append(decoded)
            return result

    def list_active_aoi_versions(
        self, *, project_id: str, aoi_id: str, aoi_revision: int
    ) -> list[dict[str, Any]]:
        with self._database() as db:
            rows = db.execute(
                """SELECT a.source_id,a.project_id,a.aoi_id,a.aoi_revision,
                          a.aoi_geometry_sha256,a.candidate_id,a.version_id,a.promoted_at,
                          v.provider,v.provider_release,v.source_url,v.retrieved_at,v.media_type,
                          v.sha256,v.byte_size,v.artifact_path,v.terms_url,v.adapter_version
                   FROM active_aoi_versions a JOIN source_versions v USING(version_id)
                   WHERE a.project_id=? AND a.aoi_id=? AND a.aoi_revision=?
                   ORDER BY a.source_id""",
                (project_id, aoi_id, aoi_revision),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_active(
        self,
        source_id: str,
        *,
        project_id: str | None = None,
        aoi_id: str | None = None,
        aoi_revision: int | None = None,
    ) -> dict[str, Any] | None:
        scoped = any(value is not None for value in (project_id, aoi_id, aoi_revision))
        if scoped and not all(value is not None for value in (project_id, aoi_id, aoi_revision)):
            raise ValueError("AOI-scoped active lookup requires project, AOI, and revision")
        with self._database() as db:
            if scoped:
                row = db.execute(
                    """SELECT a.source_id,a.project_id,a.aoi_id,a.aoi_revision,
                              a.aoi_geometry_sha256,a.candidate_id,a.version_id,a.promoted_at,
                              v.provider_release,v.source_url,v.retrieved_at,v.media_type,
                              v.sha256,v.byte_size,v.artifact_path,v.adapter_version
                       FROM active_aoi_versions a JOIN source_versions v USING(version_id)
                       WHERE a.source_id=? AND a.project_id=? AND a.aoi_id=? AND a.aoi_revision=?""",
                    (source_id, project_id, aoi_id, aoi_revision),
                ).fetchone()
            else:
                row = db.execute(
                    """SELECT a.source_id,a.version_id,a.promoted_at,v.provider_release,v.source_url,
                              v.retrieved_at,v.media_type,v.sha256,v.byte_size,v.artifact_path,v.adapter_version
                       FROM active_versions a JOIN source_versions v USING(version_id)
                       WHERE a.source_id=?""",
                    (source_id,),
                ).fetchone()
        return _decode(row)

    def create_job_snapshots(
        self,
        *,
        job_id: str,
        aoi_id: str,
        aoi_revision: int,
        source_ids: list[str],
        project_id: str | None = None,
        require_aoi_scoped_active: bool = False,
        aoi_geometry_sha256: str | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve and persist one immutable active-version view for the entire job."""
        if not source_ids or len(source_ids) != len(set(source_ids)):
            raise ValueError("A job snapshot requires a nonempty unique source list")
        if require_aoi_scoped_active and project_id is None:
            raise ValueError("AOI-scoped active snapshots require a project identifier")
        if require_aoi_scoped_active and not aoi_geometry_sha256:
            raise ValueError("AOI-scoped active snapshots require the immutable AOI geometry hash")
        now = utc_now()
        with self._transaction() as db:
            existing = db.execute(
                "SELECT * FROM job_source_snapshots WHERE job_id=? ORDER BY source_id",
                (job_id,),
            ).fetchall()
            if existing:
                stored_sources = {row["source_id"] for row in existing}
                if stored_sources != set(source_ids) or any(
                    row["aoi_id"] != aoi_id or row["aoi_revision"] != aoi_revision
                    for row in existing
                ):
                    raise ValueError(
                        "An existing job cannot be rebound to a different source snapshot"
                    )
                return [self._snapshot_row(row) for row in existing]

            for source_id in source_ids:
                maturity = MATURITY.get(source_id, (None, ""))[0]
                maturity_value = maturity.value if maturity is not None else "not_acquired"
                latest = db.execute(
                    """SELECT c.*,r.run_id,r.aoi_id,r.aoi_revision,r.project_id,r.adapter_version,
                              r.status AS run_status,v.provider,v.provider_release,v.source_url,
                              v.retrieved_at,v.media_type,v.sha256 AS version_sha256,
                              v.byte_size AS version_byte_size,v.artifact_path AS version_artifact_path,
                              v.terms_url,v.adapter_version AS version_adapter_version
                       FROM candidates c JOIN ingestion_runs r USING(run_id)
                       LEFT JOIN source_versions v ON v.version_id=c.version_id
                       WHERE c.source_id=? ORDER BY c.created_at DESC,c.candidate_id LIMIT 1""",
                    (source_id,),
                ).fetchone()
                scoped_source = source_id in {"annual_nlcd", "3dep"} and project_id is not None
                if scoped_source:
                    active = db.execute(
                        """SELECT v.*,a.promoted_at,a.project_id,a.aoi_id,a.aoi_revision,
                                  a.aoi_geometry_sha256,a.candidate_id
                           FROM active_aoi_versions a JOIN source_versions v USING(version_id)
                           WHERE a.source_id=? AND a.project_id=? AND a.aoi_id=?
                             AND a.aoi_revision=?""",
                        (source_id, project_id, aoi_id, aoi_revision),
                    ).fetchone()
                    latest_validation = json.loads(latest["validation_json"]) if latest else {}
                    latest_is_aoi_scoped = bool(
                        latest_validation.get("source_provenance", {}).get("aoi_geometry_sha256")
                    )
                    if (
                        active is None
                        and not latest_is_aoi_scoped
                        and not require_aoi_scoped_active
                    ):
                        active = db.execute(
                            """SELECT v.*,a.promoted_at FROM active_versions a
                               JOIN source_versions v USING(version_id) WHERE a.source_id=?""",
                            (source_id,),
                        ).fetchone()
                        scoped_source = False
                else:
                    active = db.execute(
                        """SELECT v.*,a.promoted_at FROM active_versions a
                           JOIN source_versions v USING(version_id) WHERE a.source_id=?""",
                        (source_id,),
                    ).fetchone()
                candidate = None
                if active is not None:
                    if scoped_source:
                        candidate = db.execute(
                            """SELECT c.*,r.run_id,r.aoi_id,r.aoi_revision,r.project_id,r.adapter_version,
                                      r.status AS run_status
                               FROM candidates c JOIN ingestion_runs r USING(run_id)
                               WHERE c.source_id=? AND c.version_id=? AND c.candidate_id=?
                                 AND c.promotion_status='promoted'
                                 AND r.project_id=? AND r.aoi_id=? AND r.aoi_revision=?""",
                            (
                                source_id,
                                active["version_id"],
                                active["candidate_id"],
                                project_id,
                                aoi_id,
                                aoi_revision,
                            ),
                        ).fetchone()
                    else:
                        candidate = db.execute(
                            """SELECT c.*,r.run_id,r.aoi_id,r.aoi_revision,r.project_id,r.adapter_version,
                                      r.status AS run_status
                               FROM candidates c JOIN ingestion_runs r USING(run_id)
                               WHERE c.source_id=? AND c.version_id=? AND c.promotion_status='promoted'
                               ORDER BY c.created_at DESC LIMIT 1""",
                            (source_id, active["version_id"]),
                        ).fetchone()

                version_id = active["version_id"] if active is not None else None
                candidate_id = candidate["candidate_id"] if candidate is not None else None
                run_id = candidate["run_id"] if candidate is not None else None
                coverage = "unknown"
                observation = "not_assessed"
                snapshot_status = "unknown"
                reason: str | None = "No promoted active source version existed at job creation."
                provenance: dict[str, Any] = {
                    "snapshot_at": now,
                    "requested_source_id": source_id,
                }
                if require_aoi_scoped_active and project_id is not None:
                    provenance.update(
                        {
                            "project_id": project_id,
                            "aoi_id": aoi_id,
                            "aoi_revision": aoi_revision,
                            "aoi_geometry_sha256": aoi_geometry_sha256,
                        }
                    )

                if active is not None:
                    provenance.update(
                        {
                            "provider": active["provider"],
                            "provider_release": active["provider_release"],
                            "source_url": active["source_url"],
                            "retrieved_at": active["retrieved_at"],
                            "media_type": active["media_type"],
                            "sha256": active["sha256"],
                            "byte_size": active["byte_size"],
                            "artifact_path": active["artifact_path"],
                            "terms_url": active["terms_url"],
                            "adapter_version": active["adapter_version"],
                            "promoted_at": active["promoted_at"],
                            "active_version_id": active["version_id"],
                        }
                    )
                    if scoped_source:
                        provenance.update(
                            {
                                "project_id": active["project_id"],
                                "aoi_id": active["aoi_id"],
                                "aoi_revision": active["aoi_revision"],
                                "aoi_geometry_sha256": active["aoi_geometry_sha256"],
                            }
                        )
                    if (
                        scoped_source
                        and aoi_geometry_sha256 is not None
                        and active["aoi_geometry_sha256"] != aoi_geometry_sha256
                    ):
                        snapshot_status = "incomplete"
                        reason = (
                            "Active version geometry hash does not match the requested immutable AOI revision; "
                            "no substitute acquisition was attempted."
                        )
                        coverage = "unknown"
                        observation = "incomplete_source"
                    elif candidate is None:
                        snapshot_status = "incomplete"
                        reason = "Active version has no promoted candidate validation record."
                        maturity_value = "not_acquired"
                        coverage = "unknown"
                        observation = "incomplete_source"
                    else:
                        maturity_value = candidate["validation_status"]
                        coverage = candidate["coverage_status"]
                        observation = candidate["observation_status"]
                        validation = json.loads(candidate["validation_json"])
                        provenance["validation"] = validation
                        provenance["candidate_id"] = candidate_id
                        provenance["ingestion_run_id"] = run_id
                        provenance["ingestion_aoi_id"] = candidate["aoi_id"]
                        provenance["ingestion_aoi_revision"] = candidate["aoi_revision"]
                        regional = source_id in {"annual_nlcd", "3dep", "ssurgo"}
                        if regional and (
                            candidate["aoi_id"] != aoi_id
                            or candidate["aoi_revision"] != aoi_revision
                        ):
                            snapshot_status = "incomplete"
                            reason = (
                                "Active artifact was acquired for a different AOI revision; "
                                "no substitute acquisition was attempted."
                            )
                        elif (
                            candidate["status"] != "validated"
                            or candidate["run_status"] != "validated"
                        ):
                            snapshot_status = "incomplete"
                            reason = "Active candidate no longer has a validated ingestion record."
                        elif coverage != "complete":
                            snapshot_status = "incomplete"
                            reason = f"Active candidate coverage is {coverage}, not complete."
                        elif observation in {
                            "unavailable",
                            "incomplete_source",
                            "not_assessed",
                            "geometry_quarantined",
                        }:
                            snapshot_status = (
                                "quarantined"
                                if observation == "geometry_quarantined"
                                else "incomplete"
                            )
                            reason = f"Active candidate observation status is {observation}."
                        else:
                            artifact = Path(active["artifact_path"]).resolve()
                            try:
                                artifact.relative_to(self.data_root)
                                digest, size = _hash_file(artifact)
                            except (OSError, ValueError):
                                snapshot_status = "unavailable"
                                reason = "Active source artifact is missing or outside the data directory."
                                observation = "unavailable"
                                coverage = "unavailable"
                            else:
                                if digest != active["sha256"] or size != active["byte_size"]:
                                    snapshot_status = "unavailable"
                                    reason = "Active source artifact failed its stored checksum/size check."
                                    observation = "unavailable"
                                    coverage = "unavailable"
                                else:
                                    snapshot_status = "active"
                                    reason = None
                elif latest is not None:
                    candidate_id = latest["candidate_id"]
                    run_id = latest["run_id"]
                    maturity_value = latest["validation_status"]
                    coverage = latest["coverage_status"]
                    observation = latest["observation_status"]
                    validation = json.loads(latest["validation_json"])
                    provenance.update(
                        {
                            "latest_candidate_id": candidate_id,
                            "latest_ingestion_run_id": run_id,
                            "latest_candidate_status": latest["status"],
                            "latest_validation": validation,
                        }
                    )
                    latest_validation_provenance = validation.get("source_provenance", {})
                    if require_aoi_scoped_active and source_id in {"annual_nlcd", "3dep"}:
                        snapshot_status = "incomplete"
                        coverage = "unknown"
                        observation = "incomplete_source"
                        reason = (
                            "No AOI-scoped active version existed for the requested AOI revision; "
                            "an unpromoted or differently scoped candidate was not substituted."
                        )
                        if latest_validation_provenance:
                            provenance["latest_candidate_aoi_id"] = (
                                latest_validation_provenance.get("aoi_id")
                            )
                            provenance["latest_candidate_aoi_revision"] = (
                                latest_validation_provenance.get("aoi_revision")
                            )
                            provenance["latest_candidate_aoi_geometry_sha256"] = (
                                latest_validation_provenance.get("aoi_geometry_sha256")
                            )
                    else:
                        if latest["status"] == "blocked":
                            snapshot_status = "blocked"
                            maturity_value = "access_blocked"
                        elif latest["status"] == "quarantined":
                            snapshot_status = "quarantined"
                            maturity_value = "conditionally_validated"
                        elif latest["status"] == "incomplete":
                            snapshot_status = "incomplete"
                        else:
                            snapshot_status = "incomplete"
                            reason = (
                                "A candidate exists but is not an eligible active version; "
                                "screening did not substitute it."
                            )
                        reason = (
                            json.loads(latest["error_json"]) if latest["error_json"] else {}
                        ).get(
                            "message", "No promoted active source version existed at job creation."
                        )
                elif source_id == "padus":
                    maturity_value = "conditionally_validated"
                    coverage = "unknown"
                    observation = "geometry_quarantined"
                    snapshot_status = "quarantined"
                    provenance["validation"] = {
                        "validation_scope": "Five-feature PAD-US repair sample only",
                        "metrics": {
                            "prior_validation_sample": {"repaired_candidates_quarantined": 3}
                        },
                        "quarantined_ids": [],
                    }
                    reason = (
                        "PAD-US remains conditional: prior sample geometry candidates are quarantined "
                        "and regional coverage is unverified; no active version is available."
                    )
                elif source_id == "fema_nfhl":
                    maturity_value = "access_blocked"
                    coverage = "unavailable"
                    observation = "unavailable"
                    snapshot_status = "blocked"
                    reason = (
                        "Selected source; provider access blocked; technical suitability and "
                        "effective/pending sample validation incomplete."
                    )

                snapshot_id = str(uuid4())
                db.execute(
                    """INSERT INTO job_source_snapshots
                       (snapshot_id,job_id,aoi_id,aoi_revision,source_id,version_id,candidate_id,
                        ingestion_run_id,source_maturity,coverage_status,observation_status,
                        snapshot_status,reason,snapshot_at,provenance_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        snapshot_id,
                        job_id,
                        aoi_id,
                        aoi_revision,
                        source_id,
                        version_id,
                        candidate_id,
                        run_id,
                        maturity_value,
                        coverage,
                        observation,
                        snapshot_status,
                        reason,
                        now,
                        _json(provenance),
                    ),
                )
            rows = db.execute(
                "SELECT * FROM job_source_snapshots WHERE job_id=? ORDER BY source_id", (job_id,)
            ).fetchall()
            return [self._snapshot_row(row) for row in rows]

    @staticmethod
    def _snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["provenance"] = json.loads(item.pop("provenance_json"))
        return item

    def get_job_snapshots(self, job_id: str) -> list[dict[str, Any]]:
        with self._database() as db:
            rows = db.execute(
                "SELECT * FROM job_source_snapshots WHERE job_id=? ORDER BY source_id", (job_id,)
            ).fetchall()
        return [self._snapshot_row(row) for row in rows]

    def _persisted_aoi_geometry_hash(self, project_id: str, aoi_id: str, aoi_revision: int) -> str:
        revision_path = (
            self.data_root
            / "workspace"
            / "projects"
            / project_id
            / "aoi-revisions"
            / f"{aoi_id}.json"
        )
        try:
            revision = json.loads(revision_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Persisted AOI revision is unavailable for promotion") from exc
        try:
            revision_number = int(revision.get("revision", -1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Persisted AOI revision number is invalid") from exc
        if (
            revision.get("project_id") != project_id
            or revision.get("aoi_id") != aoi_id
            or revision_number != aoi_revision
        ):
            raise ValueError("Persisted AOI revision identity does not match promotion request")
        context = AoiContext.from_revision(revision)
        if revision.get("geometry_sha256") != context.geometry_sha256:
            raise ValueError("Persisted AOI geometry hash is inconsistent")
        return context.geometry_sha256

    @staticmethod
    def _is_generic_raster_candidate(candidate: dict[str, Any]) -> bool:
        return candidate["source_id"] in {"annual_nlcd", "3dep"} and bool(
            (candidate.get("validation") or {})
            .get("source_provenance", {})
            .get("aoi_geometry_sha256")
        )

    @staticmethod
    def _generic_raster_rejection(candidate: dict[str, Any]) -> str | None:
        validation = candidate.get("validation") or {}
        metrics = validation.get("metrics")
        if not isinstance(metrics, dict):
            return "AOI raster candidate is missing validated raster metrics"
        coverage = metrics.get("coverage") or {}
        pixels = metrics.get("pixel_accounting") or {}
        if "uncovered_aoi_percentage" not in coverage:
            return "AOI raster candidate is missing AOI coverage metrics"
        try:
            uncovered_percentage = float(coverage["uncovered_aoi_percentage"])
            covered_percentage = float(coverage["covered_aoi_percentage"])
        except (KeyError, TypeError, ValueError):
            return "AOI raster candidate is missing complete AOI coverage metrics"
        if (
            not 0.0 <= uncovered_percentage <= 100.0
            or not 0.0 <= covered_percentage <= 100.0
            or uncovered_percentage > 0.0
            or covered_percentage < 100.0
        ):
            return "AOI raster candidate has incomplete AOI footprint coverage"
        try:
            nodata_count = int(pixels.get("nodata_pixel_count", 0) or 0)
            valid_count = int(pixels.get("valid_pixel_count", 0) or 0)
        except (TypeError, ValueError):
            return "AOI raster candidate has invalid pixel accounting"
        if nodata_count > 0:
            return "AOI raster candidate contains nodata inside the AOI"
        if valid_count <= 0:
            return "AOI raster candidate contains no valid AOI observations"
        if candidate["source_id"] == "annual_nlcd":
            if metrics.get("crs") != NLCD_NATIVE_CRS:
                return f"NLCD raster CRS is not {NLCD_NATIVE_CRS}"
            try:
                nlcd_nodata = int(metrics.get("nodata", -1))
            except (TypeError, ValueError):
                return "NLCD raster nodata is invalid"
            if nlcd_nodata != NLCD_NATIVE_NODATA:
                return "NLCD raster nodata does not match the native product contract"
            resolution = metrics.get("resolution_m") or []
            try:
                valid_resolution = len(resolution) == 2 and all(
                    math.isclose(float(value), NLCD_NATIVE_RESOLUTION_M, rel_tol=0.01)
                    for value in resolution
                )
            except (TypeError, ValueError):
                valid_resolution = False
            if not valid_resolution:
                return "NLCD raster resolution is outside the native 30 m contract"
            if metrics.get("dtype") != "uint8" or not isinstance(metrics.get("transform"), list):
                return "NLCD raster metadata does not satisfy the validated schema"
            try:
                invalid_classes = set(metrics.get("observed_class_values", [])) - set(NLCD_CLASSES)
            except TypeError:
                return "NLCD raster observed class values are invalid"
            if invalid_classes:
                return f"NLCD raster contains values outside the official class domain: {sorted(invalid_classes)}"
        else:
            if metrics.get("source_crs") != THREEDEP_NATIVE_CRS:
                return f"3DEP raster CRS is not {THREEDEP_NATIVE_CRS}"
            try:
                elevation_nodata = float(metrics.get("nodata", 0))
            except (TypeError, ValueError):
                return "3DEP raster nodata is invalid"
            if elevation_nodata != float(THREEDEP_NODATA):
                return "3DEP raster nodata does not match the native product contract"
            resolution = metrics.get("resolution_arc_seconds") or []
            try:
                valid_resolution = len(resolution) == 2 and all(
                    math.isclose(float(value), THREEDEP_NOMINAL_ARC_SECONDS, rel_tol=0.001)
                    for value in resolution
                )
            except (TypeError, ValueError):
                valid_resolution = False
            if not valid_resolution:
                return "3DEP raster resolution is outside the native 1/3 arc-second contract"
            if metrics.get("dtype") not in {"int16", "float32", "float64"} or not isinstance(
                metrics.get("transform"), list
            ):
                return "3DEP raster metadata does not satisfy the validated schema"
            if not isinstance(metrics.get("elevation_m"), dict):
                return "3DEP raster is missing validated elevation metrics"
        dimensions = metrics.get("dimensions")
        if candidate["source_id"] == "annual_nlcd":
            dimensions = {"width": metrics.get("width"), "height": metrics.get("height")}
        try:
            valid_dimensions = (
                isinstance(dimensions, dict)
                and int(dimensions.get("width", 0)) > 0
                and int(dimensions.get("height", 0)) > 0
            )
        except (TypeError, ValueError):
            valid_dimensions = False
        if not valid_dimensions:
            return "AOI raster dimensions are missing or invalid"
        return None

    def promote(
        self,
        candidate_id: str,
        *,
        project_id: str | None = None,
        aoi_id: str | None = None,
        aoi_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._database() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                prior_decision = db.execute(
                    "SELECT * FROM promotion_decisions WHERE candidate_id=?", (candidate_id,)
                ).fetchone()
                if prior_decision is not None:
                    result = dict(prior_decision)
                    result["idempotent"] = True
                    if result.get("project_id") is not None:
                        result["aoi_scope"] = {
                            "project_id": result["project_id"],
                            "aoi_id": result["aoi_id"],
                            "aoi_revision": result["aoi_revision"],
                            "aoi_geometry_sha256": result["aoi_geometry_sha256"],
                        }
                    db.commit()
                    return result

                candidate = self._candidate(candidate_id, db)
                if candidate is None:
                    raise KeyError(f"Unknown candidate: {candidate_id}")
                generic_candidate = self._is_generic_raster_candidate(candidate)
                aoi_scope: dict[str, Any] | None = None
                rejection: str | None = None
                if generic_candidate:
                    if not all(value is not None for value in (project_id, aoi_id, aoi_revision)):
                        rejection = (
                            "AOI-scoped NLCD/3DEP promotion requires project_id, aoi_id, "
                            "and aoi_revision"
                        )
                    else:
                        assert (
                            project_id is not None
                            and aoi_id is not None
                            and aoi_revision is not None
                        )
                        try:
                            persisted_hash = self._persisted_aoi_geometry_hash(
                                str(project_id), str(aoi_id), int(aoi_revision)
                            )
                        except ValueError as exc:
                            rejection = str(exc)
                        else:
                            provenance = (candidate.get("validation") or {}).get(
                                "source_provenance", {}
                            )
                            if (
                                candidate.get("project_id") != project_id
                                or candidate.get("aoi_id") != aoi_id
                                or int(candidate.get("aoi_revision", -1)) != int(aoi_revision)
                            ):
                                rejection = "Candidate ingestion run does not match the requested AOI lineage"
                            elif provenance.get("aoi_id") != aoi_id or int(
                                provenance.get("aoi_revision", -1)
                            ) != int(aoi_revision):
                                rejection = (
                                    "Candidate provenance does not match the requested AOI revision"
                                )
                            elif provenance.get("aoi_geometry_sha256") != persisted_hash:
                                rejection = "Candidate geometry hash does not match the persisted AOI revision"
                            else:
                                aoi_scope = {
                                    "project_id": str(project_id),
                                    "aoi_id": str(aoi_id),
                                    "aoi_revision": int(aoi_revision),
                                    "aoi_geometry_sha256": persisted_hash,
                                }
                    if aoi_scope is not None:
                        current = db.execute(
                            """SELECT version_id,candidate_id FROM active_aoi_versions
                               WHERE source_id=? AND project_id=? AND aoi_id=? AND aoi_revision=?""",
                            (
                                candidate["source_id"],
                                aoi_scope["project_id"],
                                aoi_scope["aoi_id"],
                                aoi_scope["aoi_revision"],
                            ),
                        ).fetchone()
                    else:
                        current = None
                else:
                    current = db.execute(
                        "SELECT version_id FROM active_versions WHERE source_id=?",
                        (candidate["source_id"],),
                    ).fetchone()
                previous_version_id = current["version_id"] if current else None
                regional_coverage = candidate["validation"].get("regional_coverage_validation")
                preserve_inactive_disposition = (
                    candidate["source_id"] == "ssurgo"
                    and regional_coverage is not None
                    and candidate["promotion_status"] == "not_promoted"
                )
                if rejection is not None:
                    pass
                elif preserve_inactive_disposition:
                    coverage = regional_coverage.get("coverage", {})
                    rejection = (
                        "SSURGO regional candidate rejected for promotion: "
                        f"{float(coverage.get('uncovered_area_sqm', 0.0)):.1f} m² "
                        "uncovered residual across "
                        f"{int(coverage.get('gap_geometry_component_count', coverage.get('gap_component_count', 0)))} "
                        "gap components, including "
                        f"{int(coverage.get('interior_gap_count', 0))} interior residuals; "
                        f"{float(coverage.get('overlap_area_sqm', 0.0)):.1f} m² of cross-package overlap. "
                        "Residual areas remain unknown; no fill, repair, clipping, or promotion is permitted."
                    )
                elif (
                    candidate["status"] != "validated"
                    or candidate["validation_status"] != "validated"
                ):
                    rejection = f"Candidate status is {candidate['status']}/{candidate['validation_status']}, not validated"
                elif candidate["coverage_status"] != "complete":
                    rejection = (
                        f"Candidate coverage is {candidate['coverage_status']}, not complete"
                    )
                elif candidate["run_status"] != "validated":
                    rejection = f"Ingestion run is {candidate['run_status']}, not validated"
                elif not candidate["version_id"] or not candidate["artifact_path"]:
                    rejection = "Candidate has no acquired artifact/version"
                elif candidate["observation_status"] not in {
                    "data_observed",
                    "constraint_observed",
                    "no_constraint_observed",
                }:
                    rejection = f"Candidate observation is not promotable: {candidate['observation_status']}"
                elif int(candidate["validation"].get("quarantined_count", 0)) > 0:
                    rejection = "Candidate validation reports quarantined geometry"
                elif generic_candidate:
                    rejection = self._generic_raster_rejection(candidate)

                if rejection is None:
                    version = (
                        db.execute(
                            "SELECT source_id,sha256,byte_size,artifact_path FROM source_versions WHERE version_id=?",
                            (candidate["version_id"],),
                        ).fetchone()
                        if candidate["version_id"]
                        else None
                    )
                    if version is None:
                        rejection = "Candidate source-version record is missing"
                    elif (
                        version["source_id"] != candidate["source_id"]
                        or version["sha256"] != candidate["sha256"]
                        or int(version["byte_size"]) != int(candidate["byte_size"])
                        or Path(version["artifact_path"]).resolve()
                        != Path(candidate["artifact_path"]).resolve()
                    ):
                        rejection = "Candidate/source-version lineage or checksum metadata mismatch"

                if rejection is None:
                    artifact = Path(candidate["artifact_path"]).resolve()
                    try:
                        artifact.relative_to(self.data_root)
                        digest, size = _hash_file(artifact)
                    except (OSError, ValueError):
                        rejection = (
                            "Candidate artifact is missing or outside the external data directory"
                        )
                    else:
                        if digest != candidate["sha256"] or size != candidate["byte_size"]:
                            rejection = "Candidate artifact checksum/version mismatch"

                decision = "rejected" if rejection else "promoted"
                already_active = previous_version_id == candidate["version_id"]
                reason = rejection or (
                    "This source version is already active; the active pointer is unchanged"
                    if already_active
                    else "Candidate passed validation and artifact integrity checks"
                )
                now = utc_now()
                decision_id = str(uuid4())
                db.execute(
                    """INSERT INTO promotion_decisions
                    (decision_id,candidate_id,source_id,version_id,previous_version_id,
                     project_id,aoi_id,aoi_revision,aoi_geometry_sha256,decision,reason,decided_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        decision_id,
                        candidate_id,
                        candidate["source_id"],
                        candidate["version_id"],
                        previous_version_id,
                        aoi_scope["project_id"] if aoi_scope else None,
                        aoi_scope["aoi_id"] if aoi_scope else None,
                        aoi_scope["aoi_revision"] if aoi_scope else None,
                        aoi_scope["aoi_geometry_sha256"] if aoi_scope else None,
                        decision,
                        reason,
                        now,
                    ),
                )
                if rejection:
                    if not preserve_inactive_disposition:
                        db.execute(
                            "UPDATE candidates SET promotion_status='rejected' WHERE candidate_id=?",
                            (candidate_id,),
                        )
                else:
                    if previous_version_id and not already_active:
                        db.execute(
                            "UPDATE source_versions SET promotion_status='superseded' WHERE version_id=?",
                            (previous_version_id,),
                        )
                        if generic_candidate and current is not None:
                            db.execute(
                                "UPDATE candidates SET promotion_status='superseded' WHERE candidate_id=?",
                                (current["candidate_id"],),
                            )
                        else:
                            db.execute(
                                "UPDATE candidates SET promotion_status='superseded' WHERE version_id=? AND promotion_status='promoted'",
                                (previous_version_id,),
                            )
                    db.execute(
                        "UPDATE source_versions SET promotion_status='active' WHERE version_id=?",
                        (candidate["version_id"],),
                    )
                    db.execute(
                        "UPDATE candidates SET promotion_status='promoted' WHERE candidate_id=?",
                        (candidate_id,),
                    )
                    if generic_candidate:
                        if aoi_scope is None:
                            raise RuntimeError("AOI-scoped promotion has no validated AOI scope")
                        db.execute(
                            """INSERT INTO active_aoi_versions
                               (source_id,project_id,aoi_id,aoi_revision,aoi_geometry_sha256,
                                version_id,candidate_id,promoted_at)
                               VALUES (?,?,?,?,?,?,?,?)
                               ON CONFLICT(source_id,project_id,aoi_id,aoi_revision) DO UPDATE SET
                                  aoi_geometry_sha256=excluded.aoi_geometry_sha256,
                                  version_id=excluded.version_id,
                                  candidate_id=excluded.candidate_id,
                                  promoted_at=excluded.promoted_at""",
                            (
                                candidate["source_id"],
                                aoi_scope["project_id"],
                                aoi_scope["aoi_id"],
                                aoi_scope["aoi_revision"],
                                aoi_scope["aoi_geometry_sha256"],
                                candidate["version_id"],
                                candidate_id,
                                now,
                            ),
                        )
                    elif not already_active:
                        db.execute(
                            """INSERT INTO active_versions(source_id,version_id,promoted_at)
                               VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                               version_id=excluded.version_id,promoted_at=excluded.promoted_at""",
                            (candidate["source_id"], candidate["version_id"], now),
                        )
                db.commit()
                return {
                    "decision_id": decision_id,
                    "candidate_id": candidate_id,
                    "source_id": candidate["source_id"],
                    "version_id": candidate["version_id"],
                    "previous_version_id": previous_version_id,
                    "decision": decision,
                    "reason": reason,
                    "decided_at": now,
                    "idempotent": False,
                    "aoi_scope": aoi_scope,
                }
            except Exception:
                db.rollback()
                raise


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _normalize_json_columns(value: dict[str, Any], columns: dict[str, str]) -> dict[str, Any]:
    for raw, target in columns.items():
        item = value.pop(raw)
        value[target] = json.loads(item) if item else None
    return value
