"""Local transactional repository for source ingestion and promotion metadata.

The repository contract is backend-neutral. SQLite is only the current local
implementation; canonical spatial data and hosted persistence remain PostGIS work.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .models import Acquisition, source_version_id, utc_now


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

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None: ...

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    def list_attempts(self, run_id: str) -> list[dict[str, Any]]: ...

    def promote(self, candidate_id: str) -> dict[str, Any]: ...


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


class SQLiteSourceRepository:
    """SQLite catalog persisted under an external data directory."""

    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()
        repository_root = Path(__file__).resolve().parents[2]
        if self.data_root == repository_root or repository_root in self.data_root.parents:
            raise ValueError("Source catalog must be stored outside the project repository")
        self.path = self.data_root / "catalog" / "sources.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
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
                    decision TEXT NOT NULL CHECK(decision IN ('promoted','rejected')),
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS active_versions (
                    source_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL REFERENCES source_versions(version_id),
                    promoted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ingestion_source_time
                    ON ingestion_runs(source_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_candidate_source_status
                    ON candidates(source_id, status, created_at DESC);
                """
            )

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

    def get_active(self, source_id: str) -> dict[str, Any] | None:
        with self._database() as db:
            row = db.execute(
                """SELECT a.source_id,a.version_id,a.promoted_at,v.provider_release,v.source_url,
                          v.retrieved_at,v.media_type,v.sha256,v.byte_size,v.artifact_path,v.adapter_version
                   FROM active_versions a JOIN source_versions v USING(version_id)
                   WHERE a.source_id=?""",
                (source_id,),
            ).fetchone()
        return _decode(row)

    def promote(self, candidate_id: str) -> dict[str, Any]:
        with self._database() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                prior_decision = db.execute(
                    "SELECT * FROM promotion_decisions WHERE candidate_id=?", (candidate_id,)
                ).fetchone()
                if prior_decision is not None:
                    result = dict(prior_decision)
                    result["idempotent"] = True
                    db.commit()
                    return result

                candidate = self._candidate(candidate_id, db)
                if candidate is None:
                    raise KeyError(f"Unknown candidate: {candidate_id}")
                current = db.execute(
                    "SELECT version_id FROM active_versions WHERE source_id=?",
                    (candidate["source_id"],),
                ).fetchone()
                previous_version_id = current["version_id"] if current else None
                rejection: str | None = None
                if (
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
                    (decision_id,candidate_id,source_id,version_id,previous_version_id,decision,reason,decided_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        decision_id,
                        candidate_id,
                        candidate["source_id"],
                        candidate["version_id"],
                        previous_version_id,
                        decision,
                        reason,
                        now,
                    ),
                )
                if rejection:
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
                    if not already_active:
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
