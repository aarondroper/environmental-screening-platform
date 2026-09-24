"""Candidate-first ingestion orchestration for the current source adapters."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import requests
from shapely.geometry import shape

from . import __version__
from .adapters import (
    ProviderData,
    acquire_3dep,
    acquire_boundary,
    acquire_nlcd,
    acquire_ssurgo,
)
from .catalog import SourceRepository, SQLiteSourceRepository
from .models import MATURITY, Acquisition
from .ssurgo_packages import (
    SSURGO_REGIONAL_SIZING,
    SsurgoPackageSpec,
    acquire_ssurgo_package,
    load_ssurgo_package_specs,
)
from .store import read_json, write_json

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
    return shape(revision["geometry"]), revision


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
) -> dict[str, Any]:
    if source_id not in REQUEST_URLS:
        raise ValueError(f"Unknown selected source: {source_id}")
    repository = cast(
        SourceRepository,
        repository if repository is not None else SQLiteSourceRepository(data_root),
    )
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
                entry["validation_status"] = "FAILED: acquisition or archive validation failed; retained inactive candidate."
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
                    "response_headers": (attempt.get("details") or {}).get(
                        "response_headers", {}
                    ),
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
            "geoids": sorted({"08013", "08069", "08123"}),
            "vintage": 2025,
            "survey_area_count": len(specs_tuple),
        },
        "started_at": area_results[0]["run"]["started_at"] if area_results else None,
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "failed" if failures else "completed_validation_only",
        "promotion_status": "not_promoted",
        "production_ready": False,
        "acquired_count": sum(1 for item in area_results if item["candidate"].get("artifact_path")),
        "validated_archive_count": sum(
            1
            for item in area_results
            if item["candidate"].get("validation_status") == "validated"
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
