"""Project/AOI records and a local job-oriented screening coordinator."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer
from rasterio.errors import RasterioError
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape
from shapely.ops import transform

from . import __version__
from .adapters import acquire_boundary
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
from .raster import screen_nlcd_raster
from .spatial import PostGISUnavailable, SpatialRepository
from .store import read_json, write_json

CONTRACT_VERSION = "2B-6"
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
        "boundary": data_root / "workspace" / "reference" / "approved_counties.geojson",
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
                validation_scope=validation.get(
                    "validation_scope", "Representative Annual NLCD fixture only."
                ),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status="fixture_only",
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason="Snapshot-pinned NLCD screening requires the job AOI geometry.",
            )
        artifact_path = raster_provenance.get("artifact_path")
        if not artifact_path:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get(
                    "validation_scope", "Representative Annual NLCD fixture only."
                ),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status="fixture_only",
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
            )
        except (OSError, RasterioError, ValueError) as exc:
            return SourceResult(
                source_id=source_id,
                validation_status=Maturity(snapshot["source_maturity"]),
                validation_scope=validation.get(
                    "validation_scope", "Representative Annual NLCD fixture only."
                ),
                coverage_status=Coverage.UNAVAILABLE,
                observation_status=Observation.UNAVAILABLE,
                product_status="fixture_only",
                attempt_status=AttemptStatus.FAILED,
                provenance=raster_provenance,
                reason=f"Snapshot-pinned NLCD raster could not be screened: {exc}",
            )
        raster_provenance.update(screened["provenance"])
        return SourceResult(
            source_id=source_id,
            validation_status=Maturity(snapshot["source_maturity"]),
            validation_scope=validation.get(
                "validation_scope", "Representative Annual NLCD fixture only."
            ),
            coverage_status=Coverage(screened["coverage_status"]),
            observation_status=Observation(screened["observation_status"]),
            product_status="fixture_only",
            attempt_status=AttemptStatus.VALIDATED,
            metrics=screened["metrics"],
            provenance=raster_provenance,
            warnings=[
                "Annual NLCD is a representative fixture/smoke raster; full regional coverage and production readiness are not established.",
                "NLCD classes are land-cover classifications, not regulatory constraints or suitability conclusions.",
            ],
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


def _parse_aoi(path: Path) -> tuple[Any, str]:
    raw = path.read_bytes()
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


def _validate_aoi(geom: Any, boundary_payload: dict[str, Any]) -> dict[str, Any]:
    boundary = _boundary_geometry(boundary_payload)
    if not boundary.covers(geom):
        raise ValueError(
            "AOI is not fully contained by the complete approved three-county boundary"
        )
    to_area = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    area_sqm = transform(to_area, geom).area
    return {
        "crs": "EPSG:4326",
        "area_crs": "EPSG:5070",
        "area_sqkm": round(area_sqm / 1_000_000, 6),
        "bounds": list(geom.bounds),
    }


def create_project(
    name: str, aoi_path: Path, data_root: Path, session: requests.Session | None = None
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("Project name cannot be blank")
    data_root = _ensure_external_data_root(data_root)
    session = session or requests.Session()
    boundary = _load_boundary(session, data_root)
    geom, input_hash = _parse_aoi(aoi_path)
    spatial = _validate_aoi(geom, boundary)
    project_id = _id()
    aoi_id = _id()
    project = {
        "project_id": project_id,
        "name": name.strip(),
        "created_at": utc_now(),
        "current_aoi_id": aoi_id,
        "current_aoi_revision": 1,
    }
    revision = {
        "aoi_id": aoi_id,
        "project_id": project_id,
        "revision": 1,
        "created_at": utc_now(),
        "input_sha256": input_hash,
        "geometry": mapping(geom),
        "spatial_validation": spatial,
    }
    paths = _repository_paths(data_root)
    write_json(paths["projects"] / project_id / "project.json", project)
    write_json(paths["projects"] / project_id / "aoi-revisions" / f"{aoi_id}.json", revision)
    return {"project": project, "aoi_revision": revision}


def revise_aoi(project_id: str, aoi_path: Path, data_root: Path) -> dict[str, Any]:
    data_root = _ensure_external_data_root(data_root)
    paths = _repository_paths(data_root)
    project_path = paths["projects"] / project_id / "project.json"
    if not project_path.exists():
        raise FileNotFoundError("Project does not exist")
    project = read_json(project_path)
    boundary = read_json(paths["boundary"])
    geom, input_hash = _parse_aoi(aoi_path)
    spatial = _validate_aoi(geom, boundary)
    revision = int(project["current_aoi_revision"]) + 1
    aoi_id = _id()
    value = {
        "aoi_id": aoi_id,
        "project_id": project_id,
        "revision": revision,
        "created_at": utc_now(),
        "input_sha256": input_hash,
        "geometry": mapping(geom),
        "spatial_validation": spatial,
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
    snapshots = SQLiteSourceRepository(data_root).create_job_snapshots(
        job_id=job_id,
        aoi_id=selected_aoi,
        aoi_revision=int(revision["revision"]),
        source_ids=selected_sources,
    )
    snapshot_by_source = {snapshot["source_id"]: snapshot for snapshot in snapshots}
    job["source_snapshot_ids"] = [
        snapshot_by_source[source_id]["snapshot_id"] for source_id in selected_sources
    ]
    write_json(paths["jobs"] / job_id / "job.json", job)
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
            source_result = _result_from_snapshot(
                snapshot,
                data_root,
                aoi_geometry_wkt=aoi_geometry_wkt,
                spatial_repository=spatial_repository,
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
                    "source_version_id": snapshot["version_id"],
                    "candidate_id": snapshot["candidate_id"],
                    "ingestion_run_id": snapshot["ingestion_run_id"],
                    "snapshot_status": effective_snapshot_status,
                    "snapshot_reason": source_result.reason,
                    "source_status": (
                        source_result.metrics.get("source_status") or effective_snapshot_status
                        if snapshot["source_id"] in {"ssurgo", "annual_nlcd"}
                        else None
                    ),
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
        result = {
            "result_id": _id(),
            "project_id": project["project_id"],
            "project_name": project["name"],
            "aoi_id": revision["aoi_id"],
            "aoi_revision": revision["revision"],
            "aoi_sha256": revision["input_sha256"],
            "submitted_at": job["created_at"],
            "completed_at": utc_now(),
            "calculation_contract_version": CONTRACT_VERSION,
            "application_version": __version__,
            "job_id": job_id,
            "job_attempt": job["attempt"],
            "job_status": final_status.value,
            "screening_mode": effective_screening_mode,
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
                "aoi_revision",
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
                "source_version_id",
                "source_url",
                "acquired_at",
                "sha256",
                "size_bytes",
                "terms_url",
                "metrics_json",
                "reason",
                "warnings_json",
                "limitations_notice",
            ],
        )
        writer.writeheader()
        for source in result["source_results"]:
            writer.writerow(
                {
                    "job_id": result["job_id"],
                    "aoi_revision": result["aoi_revision"],
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
                    "source_version_id": source.get("source_version_id")
                    or (source.get("provenance") or {}).get("version_id", ""),
                    "source_url": (source.get("provenance") or {}).get("source_url", ""),
                    "acquired_at": (source.get("provenance") or {}).get("acquired_at", ""),
                    "sha256": (source.get("provenance") or {}).get("sha256", ""),
                    "size_bytes": (source.get("provenance") or {}).get("size_bytes", ""),
                    "terms_url": (source.get("provenance") or {}).get("terms_url", ""),
                    "metrics_json": json.dumps(source["metrics"], sort_keys=True),
                    "reason": source["reason"] or "",
                    "warnings_json": json.dumps(source["warnings"], sort_keys=True),
                    "limitations_notice": result["limitations_notice"],
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
                        "source_snapshot_id": source.get("source_snapshot_id"),
                        "source_version_id": source.get("source_version_id")
                        or (source.get("provenance") or {}).get("version_id"),
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
                "job_id": job_id,
                "source_snapshot_ids": result["source_snapshot_ids"],
                "sources_without_active_version": result["sources_without_active_version"],
                "source_states": [
                    {
                        "source_id": source["source_id"],
                        "source_snapshot_id": source.get("source_snapshot_id"),
                        "source_version_id": source.get("source_version_id"),
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
