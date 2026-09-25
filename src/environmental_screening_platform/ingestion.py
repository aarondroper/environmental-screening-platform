"""Candidate-first ingestion orchestration for the current source adapters."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import requests

from . import __version__
from .adapters import (
    ProviderData,
    acquire_3dep,
    acquire_boundary,
    acquire_nlcd,
    acquire_nlcd_regional,
    acquire_ssurgo,
)
from .adapters import (
    acquire_nlcd_aoi as acquire_nlcd_for_aoi,
)
from .aoi import AoiContext
from .catalog import SourceRepository, SQLiteSourceRepository
from .models import MATURITY, Acquisition
from .regression_fixtures import NORTHERN_COLORADO_REGRESSION_FIXTURE
from .ssurgo_packages import (
    SSURGO_REGIONAL_SIZING,
    SsurgoPackageSpec,
    acquire_ssurgo_package,
    load_ssurgo_package_specs,
)
from .store import read_json, write_json
from .three_dep import (
    THREEDEP_INVENTORY_URL,
    acquire_3dep_tile,
    discover_3dep_tile_plan,
)

ADAPTER_VERSION = __version__
REQUEST_URLS = {
    "census_boundary": "https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip",
    "annual_nlcd": "https://dmsdata.cr.usgs.gov/geoserver/wcs",
    "3dep": "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage",
    "ssurgo": "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest",
    "padus": "https://www.sciencebase.gov/catalog/item/5f186a5c82cef313ed8432c4",
    "fema_nfhl": "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
}
OPERATIONAL_SOURCES = {"census_boundary", "annual_nlcd", "3dep", "ssurgo"}
Acquirer = Callable[[str, Path, Any, Callable[[Acquisition], None]], ProviderData]


def _aoi_context(
    data_root: Path, project_id: str | None, aoi_id: str | None
) -> tuple[Any, dict[str, Any] | None]:
    if not project_id:
        return None, None
    projects = data_root / "workspace" / "projects"
    project = read_json(projects / project_id / "project.json")
    selected_aoi = aoi_id or project["current_aoi_id"]
    revision = read_json(projects / project_id / "aoi-revisions" / f"{selected_aoi}.json")
    if revision["project_id"] != project_id:
        raise ValueError("AOI revision belongs to a different project")
    context = AoiContext.from_revision(revision)
    return context.geometry, revision


def _default_acquirer(
    source_id: str,
    data_root: Path,
    aoi: Any,
    acquisition_callback: Callable[[Acquisition], None],
) -> ProviderData:
    session = requests.Session()
    if source_id == "census_boundary":
        return acquire_boundary(session, data_root, acquisition_callback=acquisition_callback)
    if aoi is None:
        raise ValueError(f"Source {source_id} requires a project AOI revision")
    adapters = {
        "annual_nlcd": acquire_nlcd,
        "3dep": acquire_3dep,
        "ssurgo": acquire_ssurgo,
    }
    return adapters[source_id](session, data_root, aoi, acquisition_callback=acquisition_callback)


def _candidate_status(result: dict[str, Any]) -> str:
    if result["observation_status"] == "geometry_quarantined":
        return "quarantined"
    if result["validation_status"] == "failed" or result["attempt_status"] == "failed":
        return "failed"
    if result["validation_status"] == "conditionally_validated":
        return "conditionally_validated"
    if result["attempt_status"] != "validated":
        return "failed"
    if result["coverage_status"] != "complete" or result["observation_status"] in {
        "unavailable",
        "pending_data",
        "incomplete_source",
        "not_assessed",
    }:
        return "incomplete"
    if result["validation_status"] != "validated":
        return "failed"
    return "validated"


def ingest_source(
    source_id: str,
    data_root: Path,
    *,
    project_id: str | None = None,
    aoi_id: str | None = None,
    retry_of: str | None = None,
    repository: SourceRepository | None = None,
    acquirer: Acquirer | None = None,
    requested_url: str | None = None,
    allow_missing_aoi: bool = False,
    aoi_override: Any | None = None,
    aoi_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source_id not in REQUEST_URLS:
        raise ValueError(f"Unknown selected source: {source_id}")
    repository = cast(
        SourceRepository,
        repository if repository is not None else SQLiteSourceRepository(data_root),
    )
    aoi: Any
    revision: dict[str, Any] | None
    if aoi_override is not None:
        aoi = aoi_override
        revision = dict(aoi_metadata or {})
        if not revision.get("aoi_id") or revision.get("revision") is None:
            raise ValueError("An AOI override requires explicit aoi_id and revision metadata")
    else:
        aoi, revision = _aoi_context(data_root.resolve(), project_id, aoi_id)
    if (
        source_id != "census_boundary"
        and source_id in OPERATIONAL_SOURCES
        and revision is None
        and not allow_missing_aoi
    ):
        raise ValueError(f"Source {source_id} requires --project-id and an AOI revision")
    run = repository.begin_run(
        source_id=source_id,
        requested_url=requested_url or REQUEST_URLS[source_id],
        project_id=project_id,
        aoi_id=revision["aoi_id"] if revision else None,
        aoi_revision=int(revision["revision"]) if revision else None,
        adapter_version=ADAPTER_VERSION,
        retry_of=retry_of,
    )
    acquisition: Acquisition | None = None
    candidate_id: str | None = None

    def on_acquisition(item: Acquisition) -> None:
        nonlocal acquisition, candidate_id
        acquisition = item
        repository.record_attempt(
            run["run_id"],
            status="acquired",
            requested_url=item.requested_url or requested_url or REQUEST_URLS[source_id],
            actual_url=item.source_url,
            retrieved_at=item.acquired_at,
            sha256=item.sha256,
            byte_size=item.size_bytes,
            transport_attempts=item.attempts,
            details={
                "release": item.release,
                "terms_url": item.terms_url,
                "media_type": item.media_type,
                "request_parameters": item.request_parameters,
                "provider_reported_size_bytes": item.provider_reported_size_bytes,
                "response_headers": item.response_headers,
                "http_status": item.http_status,
            },
        )
        candidate = repository.record_candidate(
            run["run_id"],
            acquisition=item,
            adapter_version=ADAPTER_VERSION,
            status="incomplete",
            validation_status="not_assessed",
            coverage_status="unknown",
            observation_status="not_assessed",
            validation={"stage": "acquired_not_yet_validated"},
            finalize=False,
        )
        candidate_id = candidate["candidate_id"]
        if candidate["status"] == "failed":
            raise ValueError(candidate["error"]["message"])

    if source_id not in OPERATIONAL_SOURCES:
        maturity, scope = MATURITY[source_id]
        status = "blocked" if source_id == "fema_nfhl" else "quarantined"
        message = (
            "Selected source; provider access blocked; technical suitability and effective/pending sample validation incomplete."
            if source_id == "fema_nfhl"
            else "PAD-US is not acquired by this slice; the available sample has owner-visible quarantined repair candidates and unverified regional coverage."
        )
        repository.record_attempt(
            run["run_id"],
            status="blocked",
            requested_url=requested_url or REQUEST_URLS[source_id],
            details={"validation_scope": scope},
            error=message,
        )
        candidate = repository.record_candidate(
            run["run_id"],
            acquisition=None,
            adapter_version=ADAPTER_VERSION,
            status=status,
            validation_status=maturity.value,
            coverage_status="unavailable" if source_id == "fema_nfhl" else "unknown",
            observation_status="unavailable" if source_id == "fema_nfhl" else "incomplete_source",
            validation={
                "validation_scope": scope,
                "quarantined_count": 3 if source_id == "padus" else 0,
            },
            error=message,
        )
        return {"run": repository.get_run(run["run_id"]), "candidate": candidate}

    try:
        acquired = (acquirer or _default_acquirer)(source_id, data_root, aoi, on_acquisition)
    except Exception as exc:
        if candidate_id is not None:
            candidate = repository.finalize_candidate(
                candidate_id,
                status="failed",
                validation_status="failed",
                coverage_status="unavailable",
                observation_status="unavailable",
                validation={"stage": "acquisition_or_validation"},
                error=f"{type(exc).__name__}: {exc}",
            )
        else:
            repository.record_attempt(
                run["run_id"],
                status="failed",
                requested_url=requested_url or REQUEST_URLS[source_id],
                details={},
                error=f"{type(exc).__name__}: {exc}",
            )
            candidate = repository.record_candidate(
                run["run_id"],
                acquisition=acquisition,
                adapter_version=ADAPTER_VERSION,
                status="failed",
                validation_status="failed",
                coverage_status="unavailable",
                observation_status="unavailable",
                validation={"stage": "acquisition_or_validation"},
                error=f"{type(exc).__name__}: {exc}",
            )
        return {"run": repository.get_run(run["run_id"]), "candidate": candidate}

    result = acquired.result.to_dict()
    if revision is not None:
        provenance = dict(result.get("provenance") or {})
        provenance.setdefault("aoi_id", revision["aoi_id"])
        provenance.setdefault("aoi_revision", int(revision["revision"]))
        if revision.get("input_sha256"):
            provenance.setdefault("aoi_input_sha256", revision["input_sha256"])
        result["provenance"] = provenance
    status = _candidate_status(result)
    validation = {
        "validation_scope": result["validation_scope"],
        "product_status": result["product_status"],
        "metrics": result["metrics"],
        "warnings": result["warnings"],
        "reason": result["reason"],
        "quarantined_count": len(result["quarantined_ids"]),
        "features": result["features"],
        "source_provenance": result["provenance"],
    }
    if candidate_id is None:
        candidate = repository.record_candidate(
            run["run_id"],
            acquisition=None,
            adapter_version=ADAPTER_VERSION,
            status="failed",
            validation_status="failed",
            coverage_status="unknown",
            observation_status="not_assessed",
            validation={"stage": "missing_acquisition_provenance", **validation},
            error="Adapter returned a result without recording acquired artifact provenance",
        )
    else:
        candidate = repository.finalize_candidate(
            candidate_id,
            status=status,
            validation_status=result["validation_status"],
            coverage_status=result["coverage_status"],
            observation_status=result["observation_status"],
            validation=validation,
            error=result["reason"],
        )
    return {"run": repository.get_run(run["run_id"]), "candidate": candidate}


def _update_nlcd_regional_manifest(
    data_root: Path, outcome: dict[str, Any], *, boundary_path: Path
) -> Path:
    """Record the regional acquisition in the external manifest only."""
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
    candidate = outcome.get("candidate") or {}
    validation = candidate.get("validation") or {}
    provenance = validation.get("source_provenance") or {}
    attempts = candidate.get("acquisition_attempts") or []
    attempt = attempts[-1] if attempts else {}
    details = attempt.get("details") or {}
    request_parameters = provenance.get("request_parameters") or details.get(
        "request_parameters", {}
    )
    artifact = {
        "source": "Annual NLCD Collection 1.2, 2025 land cover regional acquisition",
        "url": provenance.get("requested_url")
        or details.get("requested_url")
        or REQUEST_URLS["annual_nlcd"],
        "final_url": provenance.get("source_url") or candidate.get("source_url"),
        "release_version": candidate.get("provider_release"),
        "retrieval_date": provenance.get("acquired_at") or candidate.get("retrieved_at"),
        "local_path": candidate.get("artifact_path"),
        "file_size_bytes": candidate.get("byte_size"),
        "provider_reported_size_bytes": provenance.get("provider_reported_size_bytes")
        or details.get("provider_reported_size_bytes"),
        "sha256": candidate.get("sha256"),
        "license_terms_url": provenance.get("terms_url") or candidate.get("terms_url"),
        "validation_status": candidate.get("status"),
        "source_maturity": "validated (representative-sample scope unchanged)",
        "candidate_status": candidate.get("status"),
        "promotion_status": candidate.get("promotion_status"),
        "run_id": candidate.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "source_version_id": candidate.get("version_id"),
        "aoi": {
            "boundary_path": str(boundary_path),
            "geoids": list(NORTHERN_COLORADO_REGRESSION_FIXTURE.county_geoids),
            "vintage": NORTHERN_COLORADO_REGRESSION_FIXTURE.vintage,
            "aoi_id": NORTHERN_COLORADO_REGRESSION_FIXTURE.aoi_id,
            "revision": 1,
        },
        "request_parameters": request_parameters,
        "http_status": provenance.get("http_status") or details.get("http_status"),
        "http_headers": provenance.get("response_headers") or details.get("response_headers", {}),
        "raster_validation": validation.get("metrics", {}),
        "notes": (
            "Official automated WCS regional window. Raw raster remains outside Git. "
            "Candidate is inactive and validation-only; no active NLCD version was created."
        ),
    }
    artifacts: list[dict[str, Any]] = manifest.setdefault("artifacts", [])
    if candidate.get("status") != "failed":
        existing = next(
            (
                index
                for index, current in enumerate(artifacts)
                if (
                    artifact["source_version_id"]
                    and current.get("source_version_id") == artifact["source_version_id"]
                )
                or (artifact["local_path"] and current.get("local_path") == artifact["local_path"])
            ),
            None,
        )
        if existing is None:
            artifacts.append(artifact)
        else:
            artifacts[existing] = artifact
    else:
        failures: list[dict[str, Any]] = manifest.setdefault("failed_attempts", [])
        failure = {
            "source": artifact["source"],
            "attempt_date": attempt.get("attempted_at"),
            "official_url": artifact["url"],
            "final_url": artifact["final_url"],
            "run_id": artifact["run_id"],
            "candidate_id": artifact["candidate_id"],
            "artifact_path": artifact["local_path"],
            "sha256": artifact["sha256"],
            "byte_size": artifact["file_size_bytes"],
            "provider_reported_size_bytes": artifact["provider_reported_size_bytes"],
            "http_status": artifact["http_status"],
            "response_headers": artifact["http_headers"],
            "request_parameters": artifact["request_parameters"],
            "result": (candidate.get("error") or {}).get("message"),
            "classification": "Regional raster acquired but validation failed; inactive candidate retained.",
        }
        existing_failure = next(
            (
                index
                for index, current in enumerate(failures)
                if current.get("candidate_id") == failure["candidate_id"]
            ),
            None,
        )
        if existing_failure is None:
            failures.append(failure)
        else:
            failures[existing_failure] = failure
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)
    return manifest_path


def ingest_nlcd_regional(
    data_root: Path,
    *,
    repository: SourceRepository | None = None,
    session: Any | None = None,
    boundary_path: Path | None = None,
) -> dict[str, Any]:
    """Acquire the approved three-county NLCD window as an inactive candidate."""
    from .ssurgo_regional import load_approved_aoi

    repository = cast(
        SourceRepository,
        repository if repository is not None else SQLiteSourceRepository(data_root),
    )
    boundary = (
        boundary_path
        or data_root / NORTHERN_COLORADO_REGRESSION_FIXTURE.canonical_boundary_relative_path
    )
    aoi = load_approved_aoi(data_root, boundary)
    http_session = session or requests.Session()

    def acquire(
        _source_id: str,
        root: Path,
        _aoi: Any,
        callback: Callable[[Acquisition], None],
    ) -> ProviderData:
        return acquire_nlcd_regional(http_session, root, aoi, acquisition_callback=callback)

    outcome = ingest_source(
        "annual_nlcd",
        data_root,
        repository=repository,
        acquirer=acquire,
        requested_url=REQUEST_URLS["annual_nlcd"],
        aoi_override=aoi,
        aoi_metadata={
            "aoi_id": NORTHERN_COLORADO_REGRESSION_FIXTURE.aoi_id,
            "revision": 1,
            "project_id": None,
            "geometry_source": str(boundary),
            "geoids": list(NORTHERN_COLORADO_REGRESSION_FIXTURE.county_geoids),
            "vintage": NORTHERN_COLORADO_REGRESSION_FIXTURE.vintage,
        },
    )
    outcome["manifest_path"] = str(
        _update_nlcd_regional_manifest(data_root, outcome, boundary_path=boundary)
    )
    return outcome


def ingest_nlcd_aoi(
    data_root: Path,
    *,
    project_id: str,
    aoi_id: str | None = None,
    repository: SourceRepository | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Acquire Annual NLCD for the exact immutable AOI revision in a project."""
    resolved_root = data_root.resolve()
    geometry, revision = _aoi_context(resolved_root, project_id, aoi_id)
    if geometry is None or revision is None:
        raise ValueError("Generic NLCD acquisition requires a persisted AOI revision")
    context = AoiContext.from_revision(revision)
    http_session = session or requests.Session()

    def acquire(
        _source_id: str,
        root: Path,
        _aoi: Any,
        callback: Callable[[Acquisition], None],
    ) -> ProviderData:
        return acquire_nlcd_for_aoi(
            http_session,
            root,
            context.geometry,
            aoi_context=context,
            acquisition_callback=callback,
        )

    outcome = ingest_source(
        "annual_nlcd",
        resolved_root,
        project_id=project_id,
        aoi_id=context.aoi_id,
        repository=repository,
        acquirer=acquire,
        requested_url=REQUEST_URLS["annual_nlcd"],
    )
    outcome["manifest_path"] = str(
        _update_nlcd_aoi_manifest(
            resolved_root,
            outcome,
            aoi_geometry_sha256=context.geometry_sha256,
        )
    )
    return outcome


def _update_nlcd_aoi_manifest(
    data_root: Path,
    outcome: dict[str, Any],
    *,
    aoi_geometry_sha256: str | None = None,
) -> Path:
    """Record a generic AOI NLCD acquisition in the external manifest."""
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
    candidate = outcome.get("candidate") or {}
    validation = candidate.get("validation") or {}
    provenance = validation.get("source_provenance") or {}
    attempts = candidate.get("acquisition_attempts") or []
    attempt = attempts[-1] if attempts else {}
    details = attempt.get("details") or {}
    artifact = {
        "source": "Annual NLCD Collection 1.2, 2025 land cover generic AOI acquisition",
        "url": provenance.get("requested_url")
        or details.get("requested_url")
        or REQUEST_URLS["annual_nlcd"],
        "final_url": provenance.get("source_url") or candidate.get("source_url"),
        "release_version": candidate.get("provider_release"),
        "retrieval_date": provenance.get("acquired_at") or candidate.get("retrieved_at"),
        "local_path": candidate.get("artifact_path"),
        "file_size_bytes": candidate.get("byte_size"),
        "provider_reported_size_bytes": provenance.get("provider_reported_size_bytes")
        or details.get("provider_reported_size_bytes"),
        "sha256": candidate.get("sha256"),
        "license_terms_url": provenance.get("terms_url") or candidate.get("terms_url"),
        "validation_status": candidate.get("status"),
        "source_maturity": "validated (generic AOI smoke scope; static maturity unchanged)",
        "candidate_status": candidate.get("status"),
        "promotion_status": candidate.get("promotion_status"),
        "run_id": candidate.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "source_version_id": candidate.get("version_id"),
        "project_id": outcome.get("run", {}).get("project_id"),
        "aoi_id": outcome.get("run", {}).get("aoi_id"),
        "aoi_revision": outcome.get("run", {}).get("aoi_revision"),
        "aoi_geometry_sha256": provenance.get("aoi_geometry_sha256") or aoi_geometry_sha256,
        "request_parameters": provenance.get("request_parameters")
        or details.get("request_parameters", {}),
        "http_status": provenance.get("http_status") or details.get("http_status"),
        "http_headers": provenance.get("response_headers") or details.get("response_headers", {}),
        "raster_validation": validation.get("metrics", {}),
        "notes": (
            "Generic persisted-AOI WCS acquisition; raw raster remains outside Git. "
            "Candidate is inactive and validation-only; outside-AOI pixels and nodata "
            "remain explicit non-observation/unknown states."
        ),
    }
    artifacts: list[dict[str, Any]] = manifest.setdefault("artifacts", [])
    existing = next(
        (
            index
            for index, current in enumerate(artifacts)
            if current.get("candidate_id") == artifact["candidate_id"]
        ),
        None,
    )
    if existing is None:
        artifacts.append(artifact)
    else:
        artifacts[existing] = artifact
    if candidate.get("error"):
        failures: list[dict[str, Any]] = manifest.setdefault("failed_attempts", [])
        failure = {
            "source": artifact["source"],
            "attempt_date": attempt.get("attempted_at"),
            "official_url": artifact["url"],
            "final_url": artifact["final_url"],
            "run_id": artifact["run_id"],
            "candidate_id": artifact["candidate_id"],
            "artifact_path": artifact["local_path"],
            "sha256": artifact["sha256"],
            "byte_size": artifact["file_size_bytes"],
            "provider_reported_size_bytes": artifact["provider_reported_size_bytes"],
            "http_status": artifact["http_status"],
            "response_headers": artifact["http_headers"],
            "request_parameters": artifact["request_parameters"],
            "result": (candidate.get("error") or {}).get("message"),
            "classification": "Generic AOI NLCD acquisition or validation failure; inactive candidate retained.",
        }
        existing_failure = next(
            (
                index
                for index, current in enumerate(failures)
                if current.get("candidate_id") == failure["candidate_id"]
            ),
            None,
        )
        if existing_failure is None:
            failures.append(failure)
        else:
            failures[existing_failure] = failure
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)
    return manifest_path


def _update_3dep_manifest(
    data_root: Path,
    *,
    batch: dict[str, Any],
    plan_path: Path,
) -> Path:
    """Record 3DEP tile-plan and per-candidate evidence outside Git."""
    import hashlib

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
    plan = batch["plan"]
    plan_record = {
        "source": "USGS 3DEP TNM Access tile plan",
        "plan_id": batch["plan_id"],
        "official_url": THREEDEP_INVENTORY_URL,
        "retrieval_date": plan["inventory_retrieved_at"],
        "local_path": str(plan_path),
        "file_size_bytes": plan_path.stat().st_size,
        "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "aoi_id": plan["aoi_id"],
        "aoi_revision": plan["aoi_revision"],
        "aoi_geometry_sha256": plan["aoi_geometry_sha256"],
        "selected_tile_count": len(plan["selected_tiles"]),
        "inventory_total": plan["inventory_total"],
        "status": batch["status"],
    }
    plans: list[dict[str, Any]] = manifest.setdefault("3dep_tile_plans", [])
    existing_plan = next(
        (index for index, item in enumerate(plans) if item.get("plan_id") == batch["plan_id"]),
        None,
    )
    if existing_plan is None:
        plans.append(plan_record)
    else:
        plans[existing_plan] = plan_record

    artifacts: list[dict[str, Any]] = manifest.setdefault("artifacts", [])
    failures: list[dict[str, Any]] = manifest.setdefault("failed_attempts", [])
    for tile_outcome in batch["tiles"]:
        candidate = tile_outcome["candidate"]
        validation = candidate.get("validation") or {}
        provenance = validation.get("source_provenance") or {}
        attempts = candidate.get("acquisition_attempts") or []
        attempt = attempts[-1] if attempts else {}
        details = attempt.get("details") or {}
        artifact = {
            "source": f"USGS 3DEP 1/3 arc-second tile {tile_outcome['tile_id']}",
            "url": provenance.get("requested_url") or tile_outcome["download_url"],
            "final_url": provenance.get("source_url") or candidate.get("source_url"),
            "release_version": candidate.get("provider_release"),
            "retrieval_date": provenance.get("acquired_at") or candidate.get("retrieved_at"),
            "local_path": candidate.get("artifact_path"),
            "file_size_bytes": candidate.get("byte_size"),
            "provider_reported_size_bytes": provenance.get("provider_reported_size_bytes")
            or tile_outcome.get("provider_reported_size_bytes")
            or details.get("provider_reported_size_bytes"),
            "sha256": candidate.get("sha256"),
            "license_terms_url": provenance.get("terms_url") or candidate.get("terms_url"),
            "validation_status": candidate.get("status"),
            "source_maturity": "validated (tile validation scope; static maturity unchanged)",
            "candidate_status": candidate.get("status"),
            "promotion_status": candidate.get("promotion_status"),
            "run_id": candidate.get("run_id"),
            "candidate_id": candidate.get("candidate_id"),
            "source_version_id": candidate.get("version_id"),
            "plan_id": batch["plan_id"],
            "tile_id": tile_outcome["tile_id"],
            "aoi_id": plan["aoi_id"],
            "aoi_revision": plan["aoi_revision"],
            "aoi_geometry_sha256": plan["aoi_geometry_sha256"],
            "request_parameters": provenance.get("request_parameters")
            or details.get("request_parameters", {}),
            "http_status": provenance.get("http_status") or details.get("http_status"),
            "http_headers": provenance.get("response_headers")
            or details.get("response_headers", {}),
            "raster_validation": validation.get("metrics", {}),
            "notes": (
                "Native official 3DEP tile retained outside Git; no clipping, resampling, "
                "mosaicking, or activation performed."
            ),
        }
        existing = next(
            (
                index
                for index, current in enumerate(artifacts)
                if current.get("candidate_id") == artifact["candidate_id"]
                or (
                    artifact["sha256"]
                    and current.get("source") == artifact["source"]
                    and current.get("sha256") == artifact["sha256"]
                )
            ),
            None,
        )
        if existing is None:
            artifacts.append(artifact)
        else:
            artifacts[existing] = artifact
        if candidate.get("error"):
            failure = {
                "source": artifact["source"],
                "tile_id": artifact["tile_id"],
                "attempt_date": attempt.get("attempted_at"),
                "official_url": artifact["url"],
                "final_url": artifact["final_url"],
                "run_id": artifact["run_id"],
                "candidate_id": artifact["candidate_id"],
                "artifact_path": artifact["local_path"],
                "sha256": artifact["sha256"],
                "byte_size": artifact["file_size_bytes"],
                "provider_reported_size_bytes": artifact["provider_reported_size_bytes"],
                "http_status": artifact["http_status"],
                "response_headers": artifact["http_headers"],
                "request_parameters": artifact["request_parameters"],
                "result": (candidate.get("error") or {}).get("message"),
                "classification": "3DEP tile acquisition or validation failure; inactive candidate retained.",
            }
            existing_failure = next(
                (
                    index
                    for index, current in enumerate(failures)
                    if current.get("candidate_id") == failure["candidate_id"]
                ),
                None,
            )
            if existing_failure is None:
                failures.append(failure)
            else:
                failures[existing_failure] = failure
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)
    return manifest_path


def ingest_3dep(
    data_root: Path,
    *,
    project_id: str,
    aoi_id: str | None = None,
    repository: SourceRepository | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Plan and acquire official 3DEP tiles for one immutable project AOI."""
    resolved_root = data_root.resolve()
    geometry, revision = _aoi_context(resolved_root, project_id, aoi_id)
    if geometry is None or revision is None:
        raise ValueError("Generic 3DEP acquisition requires a persisted AOI revision")
    context = AoiContext.from_revision(revision)
    repository = cast(
        SourceRepository,
        repository if repository is not None else SQLiteSourceRepository(resolved_root),
    )
    http_session = session or requests.Session()
    plan = discover_3dep_tile_plan(http_session, context)
    plan_id = str(uuid4())
    plan["plan_id"] = plan_id
    plan_path = resolved_root / "3dep" / "tile-plans" / f"{plan_id}.json"
    write_json(plan_path, plan)
    tile_results: list[dict[str, Any]] = []
    for tile in plan["selected_tiles"]:

        def acquire(
            _source_id: str,
            root: Path,
            _aoi: Any,
            callback: Callable[[Acquisition], None],
            *,
            selected_tile: dict[str, Any] = tile,
        ) -> ProviderData:
            return acquire_3dep_tile(
                http_session,
                root,
                context,
                selected_tile,
                plan_id=plan_id,
                inventory_parameters=plan["inventory_parameters"],
                acquisition_callback=callback,
            )

        outcome = ingest_source(
            "3dep",
            resolved_root,
            project_id=project_id,
            aoi_id=context.aoi_id,
            repository=repository,
            acquirer=acquire,
            requested_url=tile["download_url"],
        )
        tile_results.append(
            {
                "tile_id": tile["tile_id"],
                "product_id": tile.get("product_id"),
                "title": tile.get("title"),
                "download_url": tile["download_url"],
                "provider_reported_size_bytes": tile.get("provider_reported_size_bytes"),
                "run": outcome["run"],
                "candidate": outcome["candidate"],
            }
        )
    failures = [item for item in tile_results if item["candidate"].get("status") == "failed"]
    batch = {
        "plan_id": plan_id,
        "plan_path": str(plan_path),
        "source_id": "3dep",
        "inventory_url": THREEDEP_INVENTORY_URL,
        "project_id": context.project_id,
        "aoi_id": context.aoi_id,
        "aoi_revision": context.revision,
        "aoi_geometry_sha256": context.geometry_sha256,
        "status": "failed" if failures else "completed_validation_only",
        "promotion_status": "not_promoted",
        "production_ready": False,
        "selected_tile_count": len(tile_results),
        "acquired_tile_count": sum(
            1 for item in tile_results if item["candidate"].get("artifact_path")
        ),
        "validated_tile_count": sum(
            1 for item in tile_results if item["candidate"].get("validation_status") == "validated"
        ),
        "failed_tile_count": len(failures),
        "plan": plan,
        "tiles": tile_results,
        "limitations": [
            "Each selected 1/3-arc-second tile remains an independent inactive candidate; no clipping, mosaicking, resampling, or regional promotion is performed.",
            "Nodata and uncovered AOI areas remain unknown, not absence of a constraint.",
            "A tile-level validation pass does not establish complete regional source maturity or production readiness.",
        ],
    }
    batch_path = resolved_root / "3dep" / "tile-acquisition" / f"{plan_id}.json"
    write_json(batch_path, batch)
    batch["batch_record_path"] = str(batch_path)
    batch["manifest_path"] = str(
        _update_3dep_manifest(resolved_root, batch=batch, plan_path=plan_path)
    )
    return batch


def retry_ingestion(
    run_id: str,
    data_root: Path,
    repository: SourceRepository | None = None,
    acquirer: Acquirer | None = None,
) -> dict[str, Any]:
    repository = cast(
        SourceRepository,
        repository if repository is not None else SQLiteSourceRepository(data_root),
    )
    run = repository.get_run(run_id)
    if run is None:
        raise KeyError(f"Unknown ingestion run: {run_id}")
    if run["status"] not in {"failed", "incomplete", "blocked"}:
        raise ValueError("Only failed, incomplete, or blocked ingestion runs may be retried")
    return ingest_source(
        run["source_id"],
        data_root,
        project_id=run["project_id"],
        aoi_id=run["aoi_id"],
        retry_of=run_id,
        repository=repository,
        acquirer=acquirer,
    )


def _regional_manifest_entry(
    spec: SsurgoPackageSpec, outcome: dict[str, Any]
) -> dict[str, Any] | None:
    candidate = outcome.get("candidate") or {}
    artifact_path = candidate.get("artifact_path")
    if not artifact_path or not candidate.get("sha256"):
        return None
    validation = candidate.get("validation") or {}
    provenance = validation.get("source_provenance") or {}
    metrics = validation.get("metrics") or {}
    attempts = candidate.get("acquisition_attempts") or []
    attempt = attempts[-1] if attempts else {}
    attempt_details = attempt.get("details") or {}
    source_url = candidate.get("source_url") or spec.package_url
    retrieved_at = (
        provenance.get("acquired_at")
        or provenance.get("retrieved_at")
        or candidate.get("retrieved_at")
    )
    response_headers = provenance.get("response_headers") or attempt_details.get(
        "response_headers", {}
    )
    return {
        "source": f"NRCS SSURGO survey-area package {spec.areasymbol}",
        "url": spec.package_url,
        "final_url": provenance.get("source_url", source_url),
        "release_version": candidate.get("provider_release") or spec.provider_release,
        "retrieval_date": retrieved_at,
        "local_path": artifact_path,
        "file_size_bytes": candidate.get("byte_size"),
        "sha256": candidate.get("sha256"),
        "license_terms_url": provenance.get("terms_url") or candidate.get("terms_url"),
        "validation_status": "PASS: ZIP CRC and spatial/tabular package structure validated; inactive validation-only candidate.",
        "provider_reported_size_bytes": spec.provider_reported_size_bytes,
        "actual_size_bytes": candidate.get("byte_size"),
        "http_status": provenance.get("http_status") or attempt_details.get("http_status"),
        "http_headers": response_headers,
        "run_id": candidate.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "source_version_id": candidate.get("version_id"),
        "notes": (
            f"Provider-reported compressed size {spec.provider_reported_size_bytes} bytes; "
            f"measured local size {candidate.get('byte_size')} bytes. "
            f"Archive metrics: {json.dumps(metrics.get('archive_validation', {}), sort_keys=True)}. "
            "Not promoted; full regional canonical coverage and production readiness are not established."
        ),
    }


def _update_ssurgo_external_manifest(
    data_root: Path,
    *,
    batch: dict[str, Any],
    specs: dict[str, SsurgoPackageSpec],
) -> None:
    """Append package evidence to the external manifest without touching Git."""
    manifest_path = data_root / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
    else:
        manifest = {
            "manifest_version": 1,
            "retrieved_on": datetime.now(UTC).date().isoformat(),
            "scope": "External source artifacts and validation records",
            "artifacts": [],
            "failed_attempts": [],
        }
    artifacts = manifest.setdefault("artifacts", [])
    failures = manifest.setdefault("failed_attempts", [])
    for item in batch["areas"]:
        spec = specs[item["areasymbol"]]
        entry = _regional_manifest_entry(spec, item)
        if entry is not None:
            if item["candidate"].get("status") == "failed":
                entry["validation_status"] = (
                    "FAILED: acquisition or archive validation failed; retained inactive candidate."
                )
            existing = next(
                (
                    index
                    for index, current in enumerate(artifacts)
                    if current.get("local_path") == entry["local_path"]
                    or (
                        current.get("source") == entry["source"]
                        and current.get("sha256") == entry["sha256"]
                    )
                ),
                None,
            )
            if existing is None:
                artifacts.append(entry)
            else:
                artifacts[existing] = entry
        if item.get("candidate", {}).get("error"):
            attempts = item["candidate"].get("acquisition_attempts") or []
            attempt = attempts[-1] if attempts else {}
            failures.append(
                {
                    "source": f"NRCS SSURGO survey-area package {spec.areasymbol}",
                    "attempt_date": attempt.get("attempted_at"),
                    "official_url": spec.package_url,
                    "run_id": item.get("run", {}).get("run_id"),
                    "candidate_id": item.get("candidate", {}).get("candidate_id"),
                    "artifact_path": item["candidate"].get("artifact_path"),
                    "sha256": item["candidate"].get("sha256"),
                    "byte_size": item["candidate"].get("byte_size"),
                    "http_status": (attempt.get("details") or {}).get("http_status"),
                    "response_headers": (attempt.get("details") or {}).get("response_headers", {}),
                    "result": item["candidate"]["error"],
                    "classification": "Acquisition or archive-validation failure; no package was promoted.",
                }
            )
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)


def ingest_ssurgo_regional_packages(
    data_root: Path,
    *,
    sizing_record: Path | None = None,
    repository: SourceRepository | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Acquire all 19 official SSURGO packages as inactive candidates."""
    repository = cast(
        SourceRepository,
        repository if repository is not None else SQLiteSourceRepository(data_root),
    )
    sizing_path = sizing_record or data_root / SSURGO_REGIONAL_SIZING
    specs_tuple = load_ssurgo_package_specs(sizing_path)
    specs = {spec.areasymbol: spec for spec in specs_tuple}
    http_session = session or requests.Session()
    batch_id = str(uuid4())
    area_results: list[dict[str, Any]] = []
    for spec in specs_tuple:

        def acquire(
            _source_id: str,
            root: Path,
            _aoi: Any,
            callback: Callable[[Acquisition], None],
            *,
            package_spec: SsurgoPackageSpec = spec,
        ) -> ProviderData:
            return acquire_ssurgo_package(
                http_session, root, package_spec, acquisition_callback=callback
            )

        outcome = ingest_source(
            "ssurgo",
            data_root,
            repository=repository,
            acquirer=acquire,
            requested_url=spec.package_url,
            allow_missing_aoi=True,
        )
        area_results.append(
            {
                "areasymbol": spec.areasymbol,
                "areaname": spec.areaname,
                "provider_package_identifier": spec.provider_package_identifier,
                "provider_reported_size_bytes": spec.provider_reported_size_bytes,
                "run": outcome["run"],
                "candidate": outcome["candidate"],
            }
        )
    failures = [item for item in area_results if item["candidate"]["status"] == "failed"]
    batch = {
        "batch_id": batch_id,
        "source_id": "ssurgo",
        "sizing_record": str(sizing_path),
        "approved_boundary": {
            "geoids": sorted(NORTHERN_COLORADO_REGRESSION_FIXTURE.county_geoids),
            "vintage": NORTHERN_COLORADO_REGRESSION_FIXTURE.vintage,
            "survey_area_count": len(specs_tuple),
        },
        "started_at": area_results[0]["run"]["started_at"] if area_results else None,
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "failed" if failures else "completed_validation_only",
        "promotion_status": "not_promoted",
        "production_ready": False,
        "acquired_count": sum(1 for item in area_results if item["candidate"].get("artifact_path")),
        "validated_archive_count": sum(
            1 for item in area_results if item["candidate"].get("validation_status") == "validated"
        ),
        "failed_count": len(failures),
        "areas": area_results,
        "limitations": [
            "This workflow validates ZIP containers and package structure only; it does not parse or promote regional map-unit data.",
            "Every package candidate remains inactive because survey-area packages do not establish complete AOI coverage.",
            "Hydric-soil information remains soil information, not a wetlands inventory or regulatory determination.",
        ],
    }
    batch_path = data_root / "ssurgo" / "regional-package-acquisition" / f"{batch_id}.json"
    write_json(batch_path, batch)
    batch["batch_record_path"] = str(batch_path)
    _update_ssurgo_external_manifest(data_root, batch=batch, specs=specs)
    return batch
