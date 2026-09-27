"""Ingestion runs: acquire → raw snapshot → load → validate → (promote).

Every run is recorded in `ingestion_runs`. A failed load or validation marks the new
version `failed` and leaves the active version untouched.
"""

import hashlib
import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from esp import catalog
from esp.models import DatasetVersion, DatasetVersionSnapshot, IngestionRun
from esp.raw import record_snapshot, store_file
from esp.sources import ssurgo

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunOutcome:
    run_id: uuid.UUID
    status: str
    version_id: uuid.UUID | None
    promoted: bool = False


def _finish(
    session: Session,
    run_id: uuid.UUID,
    status: str,
    version_id: uuid.UUID | None = None,
    error: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    run = session.get(IngestionRun, run_id)
    assert run is not None
    run.status, run.version_id, run.error = status, version_id, error
    run.details = details
    run.finished_at = func.now()
    session.commit()


def ingest_ssurgo(
    sessions: sessionmaker[Session],
    source: ssurgo.PackageSource,
    areas: list[str],
    raw_dir: Path,
    promote: bool = True,
) -> RunOutcome:
    areas = sorted({a.upper() for a in areas})
    with sessions() as session:
        catalog.ensure_dataset(session, ssurgo.INFO)
        run = IngestionRun(dataset_id=ssurgo.INFO.id, details={"areas": areas})
        session.add(run)
        session.commit()
        run_id = run.id
    log.info("ingestion started", extra={"dataset": "ssurgo", "run_id": str(run_id)})

    try:
        releases = source.releases(areas)
        with sessions() as session:
            active = catalog.active_version(session, ssurgo.INFO.id)
            if active is not None and active.provider_release == releases:
                _finish(session, run_id, "unchanged", active.id, details={"releases": releases})
                log.info("ssurgo unchanged at provider", extra={"run_id": str(run_id)})
                return RunOutcome(run_id, "unchanged", active.id)

        # Acquire: immutable, checksummed raw snapshots.
        packages: list[ssurgo.Package] = []
        snapshot_ids: list[uuid.UUID] = []
        content = hashlib.sha256()
        with tempfile.TemporaryDirectory() as tmp, sessions() as session:
            for area in areas:
                url, downloaded = source.download(area, releases[area], Path(tmp))
                stored = store_file(downloaded, raw_dir, ssurgo.INFO.id)
                snapshot = record_snapshot(
                    session, ssurgo.INFO.id, url, f"{area} saverest {releases[area]}", stored
                )
                snapshot_ids.append(snapshot.id)
                packages.append(ssurgo.Package(area=area, path=stored.path))
                content.update(f"{area}:{stored.sha256}\n".encode())
            session.commit()
        content_sha256 = content.hexdigest()

        with sessions() as session:
            existing = catalog.find_loaded_version(session, ssurgo.INFO.id, content_sha256)
            if existing is not None:
                _finish(session, run_id, "unchanged", existing.id, details={"releases": releases})
                return RunOutcome(run_id, "unchanged", existing.id)
            version = DatasetVersion(
                dataset_id=ssurgo.INFO.id,
                status="loading",
                content_sha256=content_sha256,
                provider_release=releases,
            )
            session.add(version)
            session.flush()
            session.add_all(
                DatasetVersionSnapshot(version_id=version.id, snapshot_id=s) for s in snapshot_ids
            )
            session.commit()
            version_id = version.id
    except Exception as exc:
        with sessions() as session:
            _finish(session, run_id, "failed", error=f"acquisition failed: {exc}")
        log.exception("ssurgo acquisition failed", extra={"run_id": str(run_id)})
        raise

    try:
        with sessions() as session:
            for package in packages:
                package.mapunits = ssurgo.read_package(package.area, package.path).mapunits
            load_stats = ssurgo.load(session, version_id, packages)
            previous = catalog.active_version(session, ssurgo.INFO.id)
            report = ssurgo.validate(session, version_id, previous.id if previous else None)
            if not report["passed"]:
                session.rollback()  # discard the rejected rows; keep the report
                catalog.mark_failed(session, version_id, report)
                _finish(session, run_id, "failed", version_id, "validation failed", report)
                log.warning("ssurgo version failed validation", extra={"run_id": str(run_id)})
                return RunOutcome(run_id, "failed", version_id)
            loaded = session.get(DatasetVersion, version_id)
            assert loaded is not None
            loaded.stats = {**report["stats"], **load_stats}
            catalog.mark_validated(session, loaded, report)
            if promote:
                catalog.promote(session, version_id)
            session.commit()
            _finish(session, run_id, "succeeded", version_id, details=report["stats"])
    except Exception as exc:
        with sessions() as session:
            catalog.mark_failed(session, version_id, {"passed": False, "error": str(exc)})
            _finish(session, run_id, "failed", version_id, f"load failed: {exc}")
        log.exception("ssurgo load failed", extra={"run_id": str(run_id)})
        raise
    log.info(
        "ssurgo version loaded",
        extra={"run_id": str(run_id), "version_id": str(version_id), "promoted": promote},
    )
    return RunOutcome(run_id, "succeeded", version_id, promoted=promote)
