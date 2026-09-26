"""Project/AOI records and a local job-oriented screening coordinator."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import requests
from rasterio.errors import RasterioError
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape

from . import __version__
from .adapters import acquire_boundary
from .aoi import (
    AoiValidationPolicy,
    policy_by_id,
)
from .catalog import SQLiteSourceRepository
from .models import (
    AttemptStatus,
    Coverage,
    JobStatus,
    Maturity,
    Observation,
    SourceResult,
    utc_now,
)
from .raster import screen_3dep_raster, screen_nlcd_raster
from .regression_fixtures import NORTHERN_COLORADO_REGRESSION_FIXTURE
from .spatial import PostGISUnavailable, SpatialRepository
from .store import read_json, write_json

CONTRACT_VERSION = "2B-9"
NOTICE = (
    "Preliminary screening based on named dataset versions and acquisition dates. Data may be incomplete, "
    "generalized, delayed, unavailable, or unsuitable for parcel-scale conclusions. Absence of a mapped "
    "feature is not proof of absence on the ground. This is not a wetland delineation, jurisdictional or "
    "FEMA flood determination, permit decision, legal opinion, or substitute for agency consultation and "
    "qualified professional review. No composite suitability score is produced."
)
SCREENING_SOURCES = (
    "census_boundary",
    "annual_nlcd",
    "3dep",
    "ssurgo",
    "padus",
    "fema_nfhl",
)
FIXTURE_SCREENING_SOURCES = (
    "ssurgo",
    "annual_nlcd",
    "3dep",
    "padus",
    "fema_nfhl",
)


def _id() -> str:
    return str(uuid.uuid4())


def _ensure_external_data_root(data_root: Path) -> Path:
    resolved = data_root.resolve()
    repository = Path(__file__).resolve().parents[2]
    if resolved == repository or repository in resolved.parents:
        raise ValueError("Raw and runtime data must be stored outside the project repository")
    return resolved


def transition_job(current: str, target: str) -> str:
    allowed = {
        "queued": {"processing"},
        "processing": {"completed", "failed"},
        "failed": {"queued"},
        "completed": set(),
    }
    if target not in allowed.get(current, set()):
        raise ValueError(f"Invalid job transition: {current} -> {target}")
    return target


def _repository_paths(data_root: Path) -> dict[str, Path]:
    return {
        "projects": data_root / "workspace" / "projects",
        "jobs": data_root / "workspace" / "jobs",
        "boundary": data_root / NORTHERN_COLORADO_REGRESSION_FIXTURE.boundary_cache_relative_path,
    }


def _load_boundary(session: requests.Session, data_root: Path) -> dict[str, Any]:
    path = _repository_paths(data_root)["boundary"]
    if path.exists():
        return read_json(path)
    acquired = acquire_boundary(session, data_root)
    records = acquired.value["counties"]
    payload = {
        "type": "FeatureCollection",
        "name": "2025 TIGER/Line approved counties",
        "crs": "EPSG:4269",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(records[geoid]["geometry"]),
                "properties": {
                    k: v
                    for k, v in records[geoid]["attributes"].items()
                    if k in {"GEOID", "NAME", "STATEFP", "COUNTYFP"}
                },
            }
            for geoid in sorted(records)
        ],
        "union_metrics": acquired.result.metrics,
        "provenance": acquired.result.provenance,
    }
    write_json(path, payload)
    return payload


def _boundary_geometry(payload: dict[str, Any]) -> Any:
    from shapely.ops import unary_union

    return unary_union([shape(feature["geometry"]) for feature in payload["features"]])


def _result_from_snapshot(
    snapshot: dict[str, Any],
    data_root: Path,
    *,
    aoi_geometry_wkt: str | None = None,
    spatial_repository: SpatialRepository | None = None,
    active_aoi_mode: bool = False,
) -> SourceResult:
    """Materialize the screening contract's source outcome from one immutable snapshot."""
    source_id = snapshot["source_id"]
    provenance = dict(snapshot["provenance"])
    provenance["snapshot_id"] = snapshot["snapshot_id"]
    provenance["source_version_id"] = snapshot["version_id"]
    status = snapshot["snapshot_status"]
    reason = snapshot["reason"]
    attempt_status = AttemptStatus.VALIDATED if status == "active" else AttemptStatus.NOT_ACQUIRED
    observation = snapshot["observation_status"]
    coverage_status = snapshot["coverage_status"]
    if status == "unavailable":
        observation = Observation.UNAVAILABLE.value
        attempt_status = AttemptStatus.FAILED
    elif status == "blocked":
        observation = Observation.UNAVAILABLE.value
        attempt_status = AttemptStatus.ACCESS_BLOCKED
    elif status == "quarantined":
        observation = Observation.GEOMETRY_QUARANTINED.value
    elif status in {"unknown", "incomplete"} and observation in {
        Observation.NOT_ASSESSED.value,
        Observation.INCOMPLETE_SOURCE.value,
    }:
        observation = Observation.INCOMPLETE_SOURCE.value

    if status == "active":
        artifact_path = provenance.get("artifact_path")
        artifact_ok = False
        if artifact_path:
            artifact = Path(artifact_path).resolve()
            try:
                artifact.relative_to(data_root.resolve())
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                artifact_ok = digest == provenance.get("sha256")
            except (OSError, ValueError):
                artifact_ok = False
        if not artifact_ok:
            status = "unavailable"
            attempt_status = AttemptStatus.FAILED
            observation = Observation.UNAVAILABLE.value
            coverage_status = "unavailable"
            reason = (
                "The snapshotted source artifact is no longer available or failed its checksum."
            )

    validation = provenance.get("validation", {})
    raster_source_status = "active_aoi" if active_aoi_mode else "fixture_only"
    raster_product_status = "active_aoi_version" if active_aoi_mode else "fixture_only"
    nlcd_validation_scope = (
        "AOI-scoped active Annual NLCD version."
        if active_aoi_mode
        else "Representative Annual NLCD fixture only."
    )
    dep_validation_scope = (
        "AOI-scoped active 3DEP version."
        if active_aoi_mode
        else "Representative 3DEP fixture only."
    )
    if source_id == "ssurgo" and status == "active":
        fixture_provenance = dict(provenance)
        fixture_status = "fixture_only"
        if spatial_repository is None or aoi_geometry_wkt is None:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get(
                    "validation_scope", "Representative SSURGO fixture only."
                ),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=fixture_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=fixture_provenance,
                reason=(
                    "Fixture-only SSURGO screening requires an explicitly configured PostGIS repository."
                ),
            )
        try:
            screened = spatial_repository.screen_ssurgo_snapshot(
                snapshot["snapshot_id"], snapshot["version_id"], aoi_geometry_wkt
            )
        except PostGISUnavailable as exc:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get(
                    "validation_scope", "Representative SSURGO fixture only."
                ),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=fixture_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=fixture_provenance,
                reason=f"SSURGO PostGIS fixture query is unavailable: {exc}",
            )
        fixture_provenance.update(screened.get("provenance", {}))
        if screened["status"] != "available":
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get(
                    "validation_scope", "Representative SSURGO fixture only."
                ),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=fixture_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=fixture_provenance,
                reason=screened["reason"],
            )
        return SourceResult(
            source_id=source_id,
            validation_status=Maturity(snapshot["source_maturity"]),
            validation_scope=validation.get(
                "validation_scope", "Representative SSURGO fixture only."
            ),
            coverage_status=Coverage(screened["coverage_status"]),
            observation_status=Observation(screened["observation_status"]),
            product_status=fixture_status,
            attempt_status=AttemptStatus.VALIDATED,
            metrics=screened["metrics"],
            provenance=fixture_provenance,
            warnings=[
                "SSURGO records are representative fixture-only data; regional coverage is not established."
            ],
            features=screened["features"],
        )
    if source_id == "annual_nlcd" and status == "active":
        raster_provenance = dict(provenance)
        if aoi_geometry_wkt is None:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get("validation_scope", nlcd_validation_scope),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=raster_product_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason="Snapshot-pinned NLCD screening requires the job AOI geometry.",
            )
        artifact_path = raster_provenance.get("artifact_path")
        if not artifact_path:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get("validation_scope", nlcd_validation_scope),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=raster_product_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason="The snapshotted NLCD source has no external raster artifact path.",
            )
        try:
            screened = screen_nlcd_raster(
                Path(artifact_path),
                shapely_wkt.loads(aoi_geometry_wkt),
                source_snapshot_id=snapshot["snapshot_id"],
                source_version_id=snapshot["version_id"],
                provenance=raster_provenance,
                source_status=raster_source_status,
            )
        except (OSError, RasterioError, ValueError) as exc:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get("validation_scope", nlcd_validation_scope),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=raster_product_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason=f"Snapshot-pinned NLCD raster could not be screened: {exc}",
            )
        raster_provenance.update(screened["provenance"])
        nlcd_warnings = [
            "NLCD classes are land-cover classifications, not regulatory constraints or suitability conclusions."
        ]
        if not active_aoi_mode:
            nlcd_warnings.insert(
                0,
                "Annual NLCD is a representative fixture/smoke raster; full regional coverage and production readiness are not established.",
            )
        return SourceResult(
            source_id=source_id,
            validation_status=Maturity(snapshot["source_maturity"]),
            validation_scope=validation.get("validation_scope", nlcd_validation_scope),
            coverage_status=Coverage(screened["coverage_status"]),
            observation_status=Observation(screened["observation_status"]),
            product_status=raster_product_status,
            attempt_status=AttemptStatus.VALIDATED,
            metrics=screened["metrics"],
            provenance=raster_provenance,
            warnings=nlcd_warnings,
        )
    if source_id == "3dep" and status == "active":
        raster_provenance = dict(provenance)
        if aoi_geometry_wkt is None:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get("validation_scope", dep_validation_scope),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=raster_product_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason="Snapshot-pinned 3DEP screening requires the job AOI geometry.",
            )
        artifact_path = raster_provenance.get("artifact_path")
        if not artifact_path:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get("validation_scope", dep_validation_scope),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=raster_product_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason="The snapshotted 3DEP source has no external raster artifact path.",
            )
        try:
            screened = screen_3dep_raster(
                Path(artifact_path),
                shapely_wkt.loads(aoi_geometry_wkt),
                source_snapshot_id=snapshot["snapshot_id"],
                source_version_id=snapshot["version_id"],
                provenance=raster_provenance,
                source_status=raster_source_status,
            )
        except (OSError, RasterioError, ValueError) as exc:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get("validation_scope", dep_validation_scope),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status=raster_product_status,
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason=f"Snapshot-pinned 3DEP raster could not be screened: {exc}",
            )
        raster_provenance.update(screened["provenance"])
        warnings = [
            "Elevation values are reported in the source raster's declared units/datum; no conversion or derived slope is applied.",
        ]
        if not active_aoi_mode:
            warnings.insert(
                0,
                "3DEP is a representative fixture/smoke raster; full regional coverage and production readiness are not established.",
            )
        if not screened["metrics"].get("elevation_units") or not screened["metrics"].get(
            "vertical_datum"
        ):
            warnings.append(
                "The screened 3DEP artifact does not declare complete vertical units/datum metadata; values are not reinterpreted."
            )
        return SourceResult(
            source_id=source_id,
            validation_status=Maturity(snapshot["source_maturity"]),
            validation_scope=validation.get("validation_scope", dep_validation_scope),
            coverage_status=Coverage(screened["coverage_status"]),
            observation_status=Observation(screened["observation_status"]),
            product_status=raster_product_status,
            attempt_status=AttemptStatus.VALIDATED,
            metrics=screened["metrics"],
            provenance=raster_provenance,
            warnings=warnings,
            features=screened.get("features", []),
        )
    metrics = validation.get("metrics", {}) if isinstance(validation, dict) else {}
    return SourceResult(
        source_id=source_id,
        validation_status=Maturity(snapshot["source_maturity"]),
        validation_scope=validation.get(
            "validation_scope", "No active source version was available at job creation."
        ),
        coverage_status=Coverage(coverage_status),
        observation_status=Observation(observation),
        product_status=validation.get("product_status", "snapshotted source outcome"),
        attempt_status=attempt_status,
        metrics=metrics,
        provenance=provenance,
        warnings=validation.get("warnings", []) if isinstance(validation, dict) else [],
        reason=reason,
        quarantined_ids=validation.get("quarantined_ids", [])
        if isinstance(validation, dict)
        else [],
        features=validation.get("features", []) if isinstance(validation, dict) else [],
    )


def _source_availability_status(source: dict[str, Any]) -> str:
    """Summarize availability without collapsing maturity or observation state."""
    snapshot_status = source.get("snapshot_status")
    if snapshot_status == "blocked":
        return "blocked"
    if snapshot_status == "quarantined":
        return "quarantined"
    if source.get("coverage_status") == Coverage.UNAVAILABLE.value:
        return "unavailable"
    if source.get("observation_status") in {
        Observation.INCOMPLETE_SOURCE.value,
        Observation.GEOMETRY_QUARANTINED.value,
    }:
        return "incomplete"
    if source.get("product_status") == "fixture_only":
        return "fixture_only"
    return "available"


def _source_status_entry(source: dict[str, Any]) -> dict[str, Any]:
    provenance = source.get("provenance") or {}
    return {
        "source_id": source["source_id"],
        "source_snapshot_id": source.get("source_snapshot_id"),
        "active_version_id": source.get("active_version_id") or provenance.get("active_version_id"),
        "source_version_id": source.get("source_version_id"),
        "candidate_id": source.get("candidate_id"),
        "ingestion_run_id": source.get("ingestion_run_id"),
        "aoi_geometry_sha256": source.get("aoi_geometry_sha256")
        or provenance.get("aoi_geometry_sha256"),
        "validation_status": source["validation_status"],
        "coverage_status": source["coverage_status"],
        "observation_status": source["observation_status"],
        "availability_status": _source_availability_status(source),
        "snapshot_status": source.get("snapshot_status"),
        "source_status": source.get("source_status"),
        "product_status": source["product_status"],
        "attempt_status": source["attempt_status"],
        "sha256": provenance.get("sha256"),
        "byte_size": provenance.get("byte_size", provenance.get("size_bytes")),
        "reason": source.get("snapshot_reason") or source.get("reason"),
    }


def _job_outcome(source_results: list[dict[str, Any]], *, fixture_mode: bool) -> dict[str, Any]:
    matrix = [_source_status_entry(source) for source in source_results]
    blocked = [row["source_id"] for row in matrix if row["availability_status"] == "blocked"]
    quarantined = [
        row["source_id"] for row in matrix if row["availability_status"] == "quarantined"
    ]
    incomplete = [row["source_id"] for row in matrix if row["availability_status"] == "incomplete"]
    unavailable = [
        row["source_id"] for row in matrix if row["availability_status"] == "unavailable"
    ]
    successful = [
        row["source_id"]
        for row in matrix
        if row["availability_status"] in {"available", "fixture_only"}
    ]
    partial = bool(blocked or quarantined or incomplete or unavailable)
    return {
        "status": "partial" if partial else "complete",
        "product_status": "fixture_only" if fixture_mode else "mixed",
        "availability_status": "partial" if partial else "available",
        "successful_sources": successful,
        "blocked_sources": blocked,
        "quarantined_sources": quarantined,
        "incomplete_sources": incomplete,
        "unavailable_sources": unavailable,
    }


def _parse_aoi(path: Path) -> tuple[Any, str]:
    raw = path.read_bytes()
    return _parse_aoi_bytes(raw)


def _parse_aoi_bytes(raw: bytes) -> tuple[Any, str]:
    data = json.loads(raw)
    if "crs" in data:
        crs_data = data["crs"]
        crs_name = (
            crs_data.get("properties", {}).get("name") if isinstance(crs_data, dict) else None
        )
        if crs_name not in {"EPSG:4326", "urn:ogc:def:crs:OGC:1.3:CRS84"}:
            raise ValueError("AOI GeoJSON CRS metadata must identify WGS84/EPSG:4326")
    if data.get("type") == "Feature":
        data = data.get("geometry")
    elif data.get("type") == "FeatureCollection":
        features = data.get("features", [])
        if len(features) != 1:
            raise ValueError("AOI GeoJSON FeatureCollection must contain exactly one feature")
        data = features[0].get("geometry")
    geom = shape(data)
    if geom.is_empty or geom.geom_type not in {"Polygon", "MultiPolygon"} or not geom.is_valid:
        raise ValueError(
            "AOI must be a nonempty, valid Polygon or MultiPolygon; no repair is performed"
        )
    # RFC 7946 coordinates are WGS 84 longitude/latitude; arbitrary GeoJSON CRS metadata is rejected.
    return geom, hashlib.sha256(raw).hexdigest()


def _validate_aoi(
    geom: Any,
    boundary_payload: dict[str, Any] | None = None,
    *,
    policy: AoiValidationPolicy | None = None,
) -> dict[str, Any]:
    selected_policy = policy or policy_by_id(None)
    boundary = _boundary_geometry(boundary_payload) if boundary_payload is not None else None
    return selected_policy.validate(geom, boundary_geometry=boundary)


def _create_project_from_geometry(
    name: str,
    geom: Any,
    input_hash: str,
    data_root: Path,
    *,
    validation_policy: AoiValidationPolicy,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("Project name cannot be blank")
    data_root = _ensure_external_data_root(data_root)
    session = session or requests.Session()
    boundary = _load_boundary(session, data_root) if validation_policy.boundary_required else None
    spatial = _validate_aoi(geom, boundary, policy=validation_policy)
    project_id = _id()
    aoi_id = _id()
    project = {
        "project_id": project_id,
        "name": name.strip(),
        "created_at": utc_now(),
        "current_aoi_id": aoi_id,
        "current_aoi_revision": 1,
        "aoi_validation_policy": validation_policy.policy_id,
    }
    revision = {
        "aoi_id": aoi_id,
        "project_id": project_id,
        "revision": 1,
        "created_at": utc_now(),
        "input_sha256": input_hash,
        "geometry_sha256": hashlib.sha256(geom.wkb).hexdigest(),
        "geometry": mapping(geom),
        "spatial_validation": spatial,
        "validation_policy": validation_policy.policy_id,
    }
    paths = _repository_paths(data_root)
    write_json(paths["projects"] / project_id / "project.json", project)
    write_json(paths["projects"] / project_id / "aoi-revisions" / f"{aoi_id}.json", revision)
    return {"project": project, "aoi_revision": revision}


def create_project_from_geojson(
    name: str,
    geojson: dict[str, Any],
    data_root: Path,
    *,
    validation_policy: AoiValidationPolicy | None = None,
) -> dict[str, Any]:
    """Persist a generic project/AOI directly from an already received GeoJSON object."""
    raw = json.dumps(geojson, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    geom, input_hash = _parse_aoi_bytes(raw)
    return _create_project_from_geometry(
        name,
        geom,
        input_hash,
        data_root,
        validation_policy=validation_policy or policy_by_id(None),
    )


def create_project(
    name: str,
    aoi_path: Path,
    data_root: Path,
    session: requests.Session | None = None,
    *,
    validation_policy: AoiValidationPolicy | None = None,
) -> dict[str, Any]:
    selected_policy = validation_policy or policy_by_id(None)
    geom, input_hash = _parse_aoi(aoi_path)
    return _create_project_from_geometry(
        name,
        geom,
        input_hash,
        data_root,
        validation_policy=selected_policy,
        session=session,
    )


def revise_aoi(
    project_id: str,
    aoi_path: Path,
    data_root: Path,
    *,
    validation_policy: AoiValidationPolicy | None = None,
) -> dict[str, Any]:
    data_root = _ensure_external_data_root(data_root)
    paths = _repository_paths(data_root)
    project_path = paths["projects"] / project_id / "project.json"
    if not project_path.exists():
        raise FileNotFoundError("Project does not exist")
    project = read_json(project_path)
    selected_policy = validation_policy or policy_by_id(project.get("aoi_validation_policy"))
    boundary = read_json(paths["boundary"]) if selected_policy.boundary_required else None
    geom, input_hash = _parse_aoi(aoi_path)
    spatial = _validate_aoi(geom, boundary, policy=selected_policy)
    revision = int(project["current_aoi_revision"]) + 1
    aoi_id = _id()
    value = {
        "aoi_id": aoi_id,
        "project_id": project_id,
        "revision": revision,
        "created_at": utc_now(),
        "input_sha256": input_hash,
        "geometry_sha256": hashlib.sha256(geom.wkb).hexdigest(),
        "geometry": mapping(geom),
        "spatial_validation": spatial,
        "validation_policy": selected_policy.policy_id,
    }
    project["current_aoi_id"] = aoi_id
    project["current_aoi_revision"] = revision
    write_json(paths["projects"] / project_id / "aoi-revisions" / f"{aoi_id}.json", value)
    write_json(project_path, project)
    return value


def create_job(
    project_id: str,
    data_root: Path,
    aoi_id: str | None = None,
    *,
    source_ids: Sequence[str] = SCREENING_SOURCES,
    screening_mode: str = "standard",
    require_aoi_scoped_active: bool = False,
    defer_source_snapshot: bool = False,
) -> dict[str, Any]:
    data_root = _ensure_external_data_root(data_root)
    paths = _repository_paths(data_root)
    project_path = paths["projects"] / project_id / "project.json"
    if not project_path.exists():
        raise FileNotFoundError("Project does not exist")
    project = read_json(project_path)
    selected_aoi = aoi_id or project["current_aoi_id"]
    revision_path = paths["projects"] / project_id / "aoi-revisions" / f"{selected_aoi}.json"
    if not revision_path.exists():
        raise FileNotFoundError("AOI revision does not belong to this project or does not exist")
    revision = read_json(revision_path)
    if revision["project_id"] != project_id:
        raise ValueError("AOI revision belongs to a different project")
    selected_sources = list(source_ids)
    if screening_mode == "ssurgo_fixture_only" and selected_sources != ["ssurgo"]:
        raise ValueError("The SSURGO fixture-only mode requires source_ids=['ssurgo']")
    if screening_mode == "nlcd_fixture_only" and selected_sources != ["annual_nlcd"]:
        raise ValueError("The NLCD fixture-only mode requires source_ids=['annual_nlcd']")
    if screening_mode == "3dep_fixture_only" and selected_sources != ["3dep"]:
        raise ValueError("The 3DEP fixture-only mode requires source_ids=['3dep']")
    if screening_mode == "active_aoi" and (
        not selected_sources
        or any(source not in {"annual_nlcd", "3dep"} for source in selected_sources)
    ):
        raise ValueError("The active AOI mode requires one or both of annual_nlcd and 3dep")
    if screening_mode == "fixtures" and selected_sources != list(FIXTURE_SCREENING_SOURCES):
        raise ValueError(
            "The unified fixture mode requires the exact SSURGO, NLCD, 3DEP, PAD-US, and FEMA source set"
        )
    job_id = _id()
    job = {
        "job_id": job_id,
        "project_id": project_id,
        "aoi_id": selected_aoi,
        "aoi_revision": revision["revision"],
        "source_ids": selected_sources,
        "screening_mode": screening_mode,
        "status": JobStatus.QUEUED.value,
        "attempt": 0,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "error": None,
        "source_attempts": [],
    }
    if not defer_source_snapshot:
        snapshots = SQLiteSourceRepository(data_root).create_job_snapshots(
            job_id=job_id,
            project_id=project_id,
            aoi_id=selected_aoi,
            aoi_revision=int(revision["revision"]),
            source_ids=selected_sources,
            require_aoi_scoped_active=require_aoi_scoped_active or screening_mode == "active_aoi",
            aoi_geometry_sha256=str(revision["geometry_sha256"]),
        )
        snapshot_by_source = {snapshot["source_id"]: snapshot for snapshot in snapshots}
        job["source_snapshot_ids"] = [
            snapshot_by_source[source_id]["snapshot_id"] for source_id in selected_sources
        ]
    else:
        job["source_snapshot_ids"] = []
        job["snapshot_deferred"] = True
    write_json(paths["jobs"] / job_id / "job.json", job)
    return job


def bind_job_snapshots(
    job_id: str,
    data_root: Path,
    *,
    require_aoi_scoped_active: bool = True,
) -> dict[str, Any]:
    """Bind a deferred job to its exact active source versions before processing."""
    data_root = _ensure_external_data_root(data_root)
    paths = _repository_paths(data_root)
    job_path = paths["jobs"] / job_id / "job.json"
    job = read_json(job_path)
    existing = SQLiteSourceRepository(data_root).get_job_snapshots(job_id)
    if existing:
        return job
    revision = read_json(
        paths["projects"] / job["project_id"] / "aoi-revisions" / f"{job['aoi_id']}.json"
    )
    snapshots = SQLiteSourceRepository(data_root).create_job_snapshots(
        job_id=job_id,
        project_id=job["project_id"],
        aoi_id=job["aoi_id"],
        aoi_revision=int(job["aoi_revision"]),
        source_ids=list(job["source_ids"]),
        require_aoi_scoped_active=require_aoi_scoped_active,
        aoi_geometry_sha256=str(revision["geometry_sha256"]),
    )
    job["source_snapshot_ids"] = [snapshot["snapshot_id"] for snapshot in snapshots]
    job["snapshot_deferred"] = False
    job["updated_at"] = utc_now()
    write_json(job_path, job)
    return job


def run_job(
    job_id: str,
    data_root: Path,
    *,
    spatial_repository: SpatialRepository | None = None,
    screening_mode: str | None = None,
) -> dict[str, Any]:
    data_root = _ensure_external_data_root(data_root)
    paths = _repository_paths(data_root)
    job_path = paths["jobs"] / job_id / "job.json"
    job = read_json(job_path)
    repository = SQLiteSourceRepository(data_root)
    snapshots = repository.get_job_snapshots(job_id)
    if not snapshots:
        raise ValueError(
            "This job has no immutable source snapshot; create a new screening job before running it"
        )
    if job["status"] == JobStatus.COMPLETED.value:
        raise ValueError(
            "Completed jobs are immutable; submit a new job to use new source versions"
        )
    job["status"] = transition_job(job["status"], JobStatus.PROCESSING.value)
    job["attempt"] += 1
    job["updated_at"] = utc_now()
    job["error"] = None
    write_json(job_path, job)
    attempt_diagnostics: list[dict[str, Any]] = []
    try:
        effective_screening_mode = screening_mode or job.get("screening_mode", "standard")
        if effective_screening_mode == "ssurgo_fixture_only" and job["source_ids"] != ["ssurgo"]:
            raise ValueError("The SSURGO fixture-only mode cannot run a multi-source job")
        if effective_screening_mode == "nlcd_fixture_only" and job["source_ids"] != ["annual_nlcd"]:
            raise ValueError("The NLCD fixture-only mode cannot run a multi-source job")
        if effective_screening_mode == "3dep_fixture_only" and job["source_ids"] != ["3dep"]:
            raise ValueError("The 3DEP fixture-only mode cannot run a multi-source job")
        if effective_screening_mode == "active_aoi" and (
            not job["source_ids"]
            or any(source not in {"annual_nlcd", "3dep"} for source in job["source_ids"])
        ):
            raise ValueError("The active AOI mode requires one or both of annual_nlcd and 3dep")
        if effective_screening_mode == "fixtures" and job["source_ids"] != list(
            FIXTURE_SCREENING_SOURCES
        ):
            raise ValueError(
                "The unified fixture mode requires the exact SSURGO, NLCD, 3DEP, PAD-US, and FEMA source set"
            )
        project = read_json(paths["projects"] / job["project_id"] / "project.json")
        revision_path = (
            paths["projects"] / job["project_id"] / "aoi-revisions" / f"{job['aoi_id']}.json"
        )
        revision = read_json(revision_path)
        if set(snapshot["source_id"] for snapshot in snapshots) != set(job["source_ids"]):
            raise ValueError("Persisted source snapshot does not match the job request")
        by_source = {snapshot["source_id"]: snapshot for snapshot in snapshots}
        snapshots = [by_source[source_id] for source_id in job["source_ids"]]
        aoi_geometry_wkt = shape(revision["geometry"]).wkt
        results = []
        for snapshot in snapshots:
            try:
                source_result = _result_from_snapshot(
                    snapshot,
                    data_root,
                    aoi_geometry_wkt=aoi_geometry_wkt,
                    spatial_repository=spatial_repository,
                    active_aoi_mode=effective_screening_mode == "active_aoi",
                )
            except Exception as exc:
                source_result = SourceResult(
                    source_id=snapshot["source_id"],
                    validation_status=Maturity(snapshot["source_maturity"]),
                    validation_scope=(
                        snapshot.get("provenance", {})
                        .get("validation", {})
                        .get("validation_scope", "Source-specific screening attempt")
                    ),
                    coverage_status=Coverage.UNAVAILABLE,
                    observation_status=Observation.UNAVAILABLE,
                    product_status="source_failure",
                    attempt_status=AttemptStatus.FAILED,
                    provenance=dict(snapshot["provenance"]),
                    reason=f"Source screening failed: {type(exc).__name__}: {exc}",
                )
            serialized = source_result.to_dict()
            effective_snapshot_status = snapshot["snapshot_status"]
            if (
                snapshot["snapshot_status"] == "active"
                and source_result.attempt_status == AttemptStatus.FAILED
            ):
                effective_snapshot_status = "unavailable"
            serialized.update(
                {
                    "source_snapshot_id": snapshot["snapshot_id"],
                    "active_version_id": snapshot["provenance"].get("active_version_id"),
                    "source_version_id": snapshot["version_id"],
                    "candidate_id": snapshot["candidate_id"],
                    "ingestion_run_id": snapshot["ingestion_run_id"],
                    "aoi_geometry_sha256": snapshot["provenance"].get("aoi_geometry_sha256"),
                    "snapshot_status": effective_snapshot_status,
                    "snapshot_reason": source_result.reason,
                    "source_status": source_result.metrics.get("source_status")
                    or effective_snapshot_status,
                }
            )
            results.append(serialized)
            attempt_diagnostics.append(
                {
                    "source_id": snapshot["source_id"],
                    "attempt_status": source_result.attempt_status.value,
                    "snapshot_status": snapshot["snapshot_status"],
                    "reason": source_result.reason,
                }
            )
        final_status = JobStatus.COMPLETED if results else JobStatus.FAILED
        outcome = _job_outcome(
            results,
            fixture_mode=effective_screening_mode == "fixtures",
        )
        result = {
            "result_id": _id(),
            "project_id": project["project_id"],
            "project_name": project["name"],
            "aoi_id": revision["aoi_id"],
            "aoi_revision": revision["revision"],
            "aoi_sha256": revision["input_sha256"],
            "aoi_geometry_sha256": revision["geometry_sha256"],
            "submitted_at": job["created_at"],
            "completed_at": utc_now(),
            "calculation_contract_version": CONTRACT_VERSION,
            "application_version": __version__,
            "job_id": job_id,
            "job_attempt": job["attempt"],
            "job_status": final_status.value,
            "screening_mode": effective_screening_mode,
            "overall_status": outcome["status"],
            "product_status": outcome["product_status"],
            "availability_status": outcome["availability_status"],
            "source_status_matrix": [_source_status_entry(source) for source in results],
            "job_outcome": outcome,
            "source_snapshot_ids": [snapshot["snapshot_id"] for snapshot in snapshots],
            "source_snapshots": snapshots,
            "sources_without_active_version": [
                snapshot["source_id"] for snapshot in snapshots if snapshot["version_id"] is None
            ],
            "source_results": results,
            "aoi_spatial_validation": revision["spatial_validation"],
            "limitations_notice": NOTICE,
        }
        attempt_path = paths["jobs"] / job_id / f"attempt-{job['attempt']}.result.json"
        write_json(attempt_path, result)
        # The stable result pointer is atomically advanced only after a complete snapshot exists.
        write_json(paths["jobs"] / job_id / "result.json", result)
        job["status"] = transition_job(job["status"], final_status.value)
        job["updated_at"] = result["completed_at"]
        job["result_path"] = str(paths["jobs"] / job_id / "result.json")
        job["source_attempts"] = [
            {
                "source_id": row["source_id"],
                "attempt_status": row["attempt_status"],
                "snapshot_status": row["snapshot_status"],
                "reason": row["reason"],
            }
            for row in attempt_diagnostics
        ]
        write_json(job_path, job)
        return result
    except Exception as exc:
        job["status"] = transition_job(job["status"], JobStatus.FAILED.value)
        job["updated_at"] = utc_now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["source_attempts"] = attempt_diagnostics
        write_json(job_path, job)
        raise


def retry_job(
    job_id: str,
    data_root: Path,
    *,
    spatial_repository: SpatialRepository | None = None,
) -> dict[str, Any]:
    data_root = _ensure_external_data_root(data_root)
    job = read_json(_repository_paths(data_root)["jobs"] / job_id / "job.json")
    if job["status"] != JobStatus.FAILED.value:
        raise ValueError("Only failed jobs can be retried; completed jobs are immutable")
    job["status"] = transition_job(job["status"], JobStatus.QUEUED.value)
    job["updated_at"] = utc_now()
    write_json(_repository_paths(data_root)["jobs"] / job_id / "job.json", job)
    return run_job(job_id, data_root, spatial_repository=spatial_repository)


def job_status(job_id: str, data_root: Path) -> dict[str, Any]:
    data_root = _ensure_external_data_root(data_root)
    return read_json(_repository_paths(data_root)["jobs"] / job_id / "job.json")


def export_result(job_id: str, data_root: Path, output_dir: Path) -> list[Path]:
    data_root = _ensure_external_data_root(data_root)
    paths = _repository_paths(data_root)
    result = read_json(paths["jobs"] / job_id / "result.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{job_id}.json"
    csv_path = output_dir / f"{job_id}.csv"
    geojson_path = output_dir / f"{job_id}-aoi.geojson"
    write_json(json_path, result)
    import csv

    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "job_id",
                "project_id",
                "aoi_id",
                "aoi_revision",
                "aoi_geometry_sha256",
                "job_status",
                "overall_status",
                "job_product_status",
                "job_availability_status",
                "source_id",
                "source_snapshot_id",
                "snapshot_status",
                "snapshot_reason",
                "validation_status",
                "coverage_status",
                "observation_status",
                "attempt_status",
                "validation_scope",
                "product_status",
                "source_status",
                "active_version_id",
                "source_version_id",
                "candidate_id",
                "ingestion_run_id",
                "source_url",
                "acquired_at",
                "sha256",
                "size_bytes",
                "terms_url",
                "metrics_json",
                "reason",
                "warnings_json",
                "limitations_notice",
                "source_status_matrix_json",
            ],
        )
        writer.writeheader()
        for source in result["source_results"]:
            writer.writerow(
                {
                    "job_id": result["job_id"],
                    "project_id": result["project_id"],
                    "aoi_id": result["aoi_id"],
                    "aoi_revision": result["aoi_revision"],
                    "aoi_geometry_sha256": result["aoi_geometry_sha256"],
                    "job_status": result["job_status"],
                    "overall_status": result.get("overall_status", result["job_status"]),
                    "job_product_status": result.get("product_status", ""),
                    "job_availability_status": result.get("availability_status", ""),
                    "source_id": source["source_id"],
                    "source_snapshot_id": source.get("source_snapshot_id", ""),
                    "snapshot_status": source.get("snapshot_status", ""),
                    "snapshot_reason": source.get("snapshot_reason", ""),
                    "validation_status": source["validation_status"],
                    "coverage_status": source["coverage_status"],
                    "observation_status": source["observation_status"],
                    "attempt_status": source["attempt_status"],
                    "validation_scope": source["validation_scope"],
                    "product_status": source["product_status"],
                    "source_status": source.get("source_status", ""),
                    "active_version_id": source.get("active_version_id")
                    or (source.get("provenance") or {}).get("active_version_id", ""),
                    "source_version_id": source.get("source_version_id")
                    or (source.get("provenance") or {}).get("version_id", ""),
                    "candidate_id": source.get("candidate_id", ""),
                    "ingestion_run_id": source.get("ingestion_run_id", ""),
                    "source_url": (source.get("provenance") or {}).get("source_url", ""),
                    "acquired_at": (source.get("provenance") or {}).get("acquired_at", ""),
                    "sha256": (source.get("provenance") or {}).get("sha256", ""),
                    "size_bytes": (source.get("provenance") or {}).get("size_bytes", ""),
                    "terms_url": (source.get("provenance") or {}).get("terms_url", ""),
                    "metrics_json": json.dumps(source["metrics"], sort_keys=True),
                    "reason": source["reason"] or "",
                    "warnings_json": json.dumps(source["warnings"], sort_keys=True),
                    "limitations_notice": result["limitations_notice"],
                    "source_status_matrix_json": json.dumps(
                        result.get("source_status_matrix", []), sort_keys=True
                    ),
                }
            )
    revision_path = (
        paths["projects"] / result["project_id"] / "aoi-revisions" / f"{result['aoi_id']}.json"
    )
    revision = read_json(revision_path)
    spatial_features = [
        {
            "type": "Feature",
            "geometry": revision["geometry"],
            "properties": {
                "feature_type": "aoi_boundary",
                "project_id": result["project_id"],
                "aoi_id": result["aoi_id"],
                "aoi_revision": result["aoi_revision"],
                "aoi_geometry_sha256": result["aoi_geometry_sha256"],
                "job_id": job_id,
            },
        }
    ]
    for source in result["source_results"]:
        for feature in source.get("features", []):
            spatial_features.append(
                {
                    "type": "Feature",
                    "geometry": feature["geometry"],
                    "properties": {
                        **feature.get("properties", {}),
                        "feature_type": "source_finding",
                        "source_id": source["source_id"],
                        "project_id": result["project_id"],
                        "aoi_id": result["aoi_id"],
                        "aoi_revision": result["aoi_revision"],
                        "aoi_geometry_sha256": result["aoi_geometry_sha256"],
                        "source_snapshot_id": source.get("source_snapshot_id"),
                        "active_version_id": source.get("active_version_id"),
                        "source_version_id": source.get("source_version_id")
                        or (source.get("provenance") or {}).get("version_id"),
                        "candidate_id": source.get("candidate_id"),
                        "ingestion_run_id": source.get("ingestion_run_id"),
                        "sha256": (source.get("provenance") or {}).get("sha256"),
                        "validation_status": source["validation_status"],
                        "coverage_status": source["coverage_status"],
                        "observation_status": source["observation_status"],
                        "snapshot_status": source.get("snapshot_status"),
                        "source_status": source.get("source_status"),
                        "job_id": job_id,
                    },
                }
            )
    write_json(
        geojson_path,
        {
            "type": "FeatureCollection",
            "features": spatial_features,
            "properties": {
                "project_id": result["project_id"],
                "aoi_id": result["aoi_id"],
                "aoi_revision": result["aoi_revision"],
                "aoi_geometry_sha256": result["aoi_geometry_sha256"],
                "job_id": job_id,
                "job_status": result["job_status"],
                "overall_status": result.get("overall_status"),
                "product_status": result.get("product_status"),
                "availability_status": result.get("availability_status"),
                "job_outcome": result.get("job_outcome"),
                "source_snapshot_ids": result["source_snapshot_ids"],
                "sources_without_active_version": result["sources_without_active_version"],
                "source_status_matrix": result.get("source_status_matrix", []),
                "source_states": [
                    {
                        "source_id": source["source_id"],
                        "source_snapshot_id": source.get("source_snapshot_id"),
                        "active_version_id": source.get("active_version_id"),
                        "source_version_id": source.get("source_version_id"),
                        "candidate_id": source.get("candidate_id"),
                        "ingestion_run_id": source.get("ingestion_run_id"),
                        "sha256": (source.get("provenance") or {}).get("sha256"),
                        "aoi_geometry_sha256": result["aoi_geometry_sha256"],
                        "validation_status": source["validation_status"],
                        "coverage_status": source["coverage_status"],
                        "observation_status": source["observation_status"],
                        "snapshot_status": source.get("snapshot_status"),
                        "source_status": source.get("source_status"),
                        "reason": source.get("snapshot_reason") or source.get("reason"),
                    }
                    for source in result["source_results"]
                ],
                "limitations_notice": result["limitations_notice"],
                "note": "Includes the AOI boundary and only valid source spatial findings produced by this run; absent source features are not a no-constraint conclusion.",
            },
        },
    )
    return [json_path, csv_path, geojson_path]
