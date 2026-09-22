"""Candidate-first ingestion orchestration for the current source adapters."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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
from .store import read_json

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
) -> dict[str, Any]:
    if source_id not in REQUEST_URLS:
        raise ValueError(f"Unknown selected source: {source_id}")
    repository = cast(
        SourceRepository,
        repository if repository is not None else SQLiteSourceRepository(data_root),
    )
    aoi, revision = _aoi_context(data_root.resolve(), project_id, aoi_id)
    if source_id != "census_boundary" and source_id in OPERATIONAL_SOURCES and revision is None:
        raise ValueError(f"Source {source_id} requires --project-id and an AOI revision")
    run = repository.begin_run(
        source_id=source_id,
        requested_url=REQUEST_URLS[source_id],
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
            requested_url=REQUEST_URLS[source_id],
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
            requested_url=REQUEST_URLS[source_id],
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
                requested_url=REQUEST_URLS[source_id],
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
        "metrics": result["metrics"],
        "warnings": result["warnings"],
        "reason": result["reason"],
        "quarantined_count": len(result["quarantined_ids"]),
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
