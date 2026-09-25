"""AOI-agnostic SSURGO survey-area discovery and package acquisition.

This path discovers survey areas through the official NRCS Soil Data Access
service, resolves the official Web Soil Survey cache package for each current
release, and records inactive package candidates.  It intentionally stops at
container validation: regional staging, repair, clipping, coverage analysis,
and promotion remain separate workflows.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .aoi import AoiContext
from .catalog import SourceRepository, SQLiteSourceRepository
from .models import Acquisition
from .ssurgo_packages import (
    OFFICIAL_PACKAGE_HOST,
    SSURGO_TERMS_URL,
    SsurgoPackageSpec,
    acquire_ssurgo_package,
)
from .store import fetch_raw, read_json, write_json

SSURGO_SDA_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"
SSURGO_PROVIDER = "USDA NRCS Soil Data Access / Web Soil Survey"
SSURGO_MAX_SURVEY_AREAS = 16
SSURGO_MAX_TOTAL_BYTES = 500_000_000
_AREA_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}$")


class SsurgoPlanRejected(ValueError):
    """The requested AOI cannot be acquired within explicit configured bounds."""


def build_sda_discovery_query(aoi: Any) -> str:
    """Build the official SDA survey-area intersection query for one AOI."""
    wkt = aoi.wkt.replace("'", "''")
    return (
        "select s.areasymbol, c.areaname, c.saversion, c.saverest, "
        "c.mbrminx, c.mbrminy, c.mbrmaxx, c.mbrmaxy "
        "from SDA_Get_Areasymbol_from_intersection_with_WktWgs84("
        f"'{wkt}') s join sacatalog c on c.areasymbol=s.areasymbol "
        "order by s.areasymbol"
    )


def parse_sda_discovery(body: bytes) -> list[dict[str, Any]]:
    """Parse and validate the SDA JSON+COLUMNNAME discovery response."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("SDA survey-area discovery returned invalid JSON") from exc
    table = payload.get("Table") if isinstance(payload, dict) else None
    if not isinstance(table, list) or not table:
        raise ValueError("SDA survey-area discovery did not return a Table")
    columns = [str(value).lower() for value in table[0]]
    required = {"areasymbol", "areaname", "saversion", "saverest"}
    missing = required - set(columns)
    if missing:
        raise ValueError(f"SDA discovery response missing columns: {sorted(missing)}")
    areas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_row in table[1:]:
        if not isinstance(raw_row, list) or len(raw_row) != len(columns):
            raise ValueError("SDA discovery response contains a malformed row")
        row = dict(zip(columns, raw_row, strict=True))
        symbol = str(row.get("areasymbol") or "").upper()
        if not _AREA_SYMBOL.fullmatch(symbol) or symbol in seen:
            raise ValueError(f"SDA discovery returned invalid or duplicate areasymbol: {symbol!r}")
        try:
            saversion = int(row["saversion"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"SDA discovery returned invalid saversion for {symbol}") from exc
        saverest = str(row.get("saverest") or "").strip()
        if not saverest:
            raise ValueError(f"SDA discovery returned no saverest for {symbol}")
        area = {
            "areasymbol": symbol,
            "areaname": str(row.get("areaname") or "").strip(),
            "saversion": saversion,
            "saverest_provider": saverest,
        }
        for key in ("mbrminx", "mbrminy", "mbrmaxx", "mbrmaxy"):
            if row.get(key) is not None:
                area[key] = float(row[key])
        seen.add(symbol)
        areas.append(area)
    return areas


def _release_date(saverest: str) -> str:
    """Return the WSS cache date component from SDA's release timestamp."""
    for pattern in ("%m/%d/%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(saverest, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unsupported SDA saverest timestamp: {saverest}")


def resolve_package(area: dict[str, Any]) -> dict[str, Any]:
    """Resolve the official WSS package URL from an SDA survey-area row."""
    symbol = str(area["areasymbol"])
    release_date = _release_date(str(area["saverest_provider"]))
    package_identifier = f"wss_SSA_{symbol}_soildb_US_2003_[{release_date}].zip"
    package_url = f"https://{OFFICIAL_PACKAGE_HOST}/DSD/Download/Cache/SSA/{package_identifier}"
    return {
        **area,
        "provider_package_identifier": package_identifier,
        "package_url": package_url,
        "format": "SSURGO survey-area ZIP (spatial shapefiles and tabular data)",
        "provider_release": (
            f"SSURGO {symbol} saversion {area['saversion']} saverest {area['saverest_provider']}"
        ),
    }


def _probe_package(session: Any, url: str) -> dict[str, Any]:
    """Read official package headers without consuming the ZIP body."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != OFFICIAL_PACKAGE_HOST:
        raise ValueError(f"SSURGO package URL is not the official HTTPS route: {url}")
    response = None
    try:
        response = session.get(url, timeout=(10, 60), stream=True, allow_redirects=True)
        response.raise_for_status()
        final = urlparse(response.url)
        if final.scheme != "https" or final.hostname != OFFICIAL_PACKAGE_HOST:
            raise ValueError(f"Provider redirected to an unapproved package URL: {response.url}")
        declared = response.headers.get("Content-Length")
        if not declared:
            raise ValueError("SSURGO package response did not provide Content-Length")
        try:
            size = int(declared)
        except ValueError as exc:
            raise ValueError("SSURGO package Content-Length is not numeric") from exc
        if size <= 0:
            raise ValueError("SSURGO package Content-Length is not positive")
        return {
            "final_url": response.url,
            "provider_reported_size_bytes": size,
            "http_status": response.status_code,
            "response_headers": {
                key: value
                for key, value in response.headers.items()
                if key.lower()
                in {"content-length", "content-type", "etag", "last-modified", "accept-ranges"}
            },
        }
    finally:
        if response is not None:
            response.close()


def _plan_id(plan: dict[str, Any]) -> str:
    stable = dict(plan)
    stable.pop("created_at", None)
    stable.pop("plan_status", None)
    stable.pop("discovery", None)
    stable.pop("package_metadata", None)
    body = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _write_plan(data_root: Path, plan: dict[str, Any]) -> Path:
    path = data_root / "ssurgo" / "package-plans" / f"{plan['plan_id']}.json"
    write_json(path, plan)
    return path


def _update_manifest(data_root: Path, batch: dict[str, Any]) -> Path:
    path = data_root / "manifest.json"
    manifest: dict[str, Any] = (
        read_json(path)
        if path.exists()
        else {
            "manifest_version": 1,
            "retrieved_on": datetime.now(UTC).date().isoformat(),
            "scope": "External source artifacts and validation records",
            "artifacts": [],
            "failed_attempts": [],
        }
    )
    artifacts_value = manifest.setdefault("artifacts", [])
    artifacts: list[dict[str, Any]] = artifacts_value if isinstance(artifacts_value, list) else []
    manifest["artifacts"] = artifacts
    failures_value = manifest.setdefault("failed_attempts", [])
    failures: list[dict[str, Any]] = failures_value if isinstance(failures_value, list) else []
    manifest["failed_attempts"] = failures
    plan = batch["plan"]
    plan_entry = {
        "source": "NRCS SSURGO generic AOI package plan",
        "official_url": SSURGO_SDA_URL,
        "release_version": "SDA survey-area discovery and current WSS package metadata",
        "retrieval_date": plan.get("discovery", {}).get("acquired_at"),
        "local_path": batch.get("plan_path"),
        "file_size_bytes": Path(batch["plan_path"]).stat().st_size
        if batch.get("plan_path")
        else None,
        "sha256": None,
        "license_terms_url": SSURGO_TERMS_URL,
        "validation_status": plan.get("plan_status"),
        "aoi": plan.get("aoi"),
        "survey_area_count": len(plan.get("survey_areas", [])),
        "notes": "Deterministic plan persisted before package bodies were acquired.",
    }
    # The plan is JSON and its checksum is useful provenance, but avoid a second
    # write cycle solely to embed the checksum in the JSON itself.
    if batch.get("plan_path"):
        plan_entry["sha256"] = hashlib.sha256(Path(batch["plan_path"]).read_bytes()).hexdigest()
    artifacts[:] = [
        item
        for item in artifacts
        if item.get("local_path") != batch.get("plan_path")
        and item.get("plan_id") != plan.get("plan_id")
    ]
    plan_entry["plan_id"] = plan.get("plan_id")
    artifacts.append(plan_entry)
    for item in batch.get("packages", []):
        candidate = item.get("candidate") or {}
        validation = candidate.get("validation") or {}
        provenance = validation.get("source_provenance") or {}
        attempt = (candidate.get("acquisition_attempts") or [{}])[-1]
        details = attempt.get("details") or {}
        entry = {
            "source": f"NRCS SSURGO survey-area package {item['areasymbol']}",
            "official_url": item["package_url"],
            "final_url": provenance.get("source_url") or details.get("actual_url"),
            "release_version": candidate.get("provider_release") or item.get("provider_release"),
            "retrieval_date": provenance.get("acquired_at") or candidate.get("retrieved_at"),
            "local_path": candidate.get("artifact_path"),
            "file_size_bytes": candidate.get("byte_size"),
            "provider_reported_size_bytes": item.get("provider_reported_size_bytes"),
            "sha256": candidate.get("sha256"),
            "license_terms_url": candidate.get("terms_url") or SSURGO_TERMS_URL,
            "validation_status": candidate.get("status"),
            "candidate_id": candidate.get("candidate_id"),
            "run_id": candidate.get("run_id"),
            "source_version_id": candidate.get("version_id"),
            "aoi": plan.get("aoi"),
            "http_status": details.get("http_status") or provenance.get("http_status"),
            "http_headers": details.get("response_headers")
            or provenance.get("response_headers", {}),
            "notes": "Inactive candidate; package structure only. No staging, clipping, coverage, or promotion.",
        }
        key = entry.get("candidate_id") or entry.get("local_path") or entry["official_url"]
        artifacts[:] = [
            current
            for current in artifacts
            if (
                current.get("candidate_id")
                or current.get("local_path")
                or current.get("official_url")
            )
            != key
        ]
        if candidate.get("status") == "failed":
            failures.append({**entry, "error": (candidate.get("error") or {}).get("message")})
        else:
            artifacts.append(entry)
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(path, manifest)
    return path


def ingest_ssurgo_aoi(
    data_root: Path,
    *,
    project_id: str,
    aoi_id: str | None = None,
    repository: SourceRepository | None = None,
    session: Any | None = None,
    max_survey_areas: int = SSURGO_MAX_SURVEY_AREAS,
    max_total_bytes: int = SSURGO_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    """Discover and acquire bounded official SSURGO packages for one AOI."""
    from .ingestion import _aoi_context, ingest_source

    resolved_root = data_root.resolve()
    geometry, revision = _aoi_context(resolved_root, project_id, aoi_id)
    if geometry is None or revision is None:
        raise ValueError("Generic SSURGO acquisition requires a persisted AOI revision")
    context = AoiContext.from_revision(revision)
    repository = repository or SQLiteSourceRepository(resolved_root)
    http_session = session or requests.Session()
    query = build_sda_discovery_query(context.geometry)
    discovery_params = {
        "aoi_id": context.aoi_id,
        "aoi_revision": context.revision,
        "aoi_geometry_sha256": context.geometry_sha256,
        "crs": "EPSG:4326",
        "format": "JSON+COLUMNNAME",
    }
    body, discovery_meta = fetch_raw(
        http_session,
        source_id="ssurgo",
        provider=SSURGO_PROVIDER,
        release="SDA survey-area intersection discovery",
        url=SSURGO_SDA_URL,
        params=None,
        data_root=resolved_root,
        terms_url=SSURGO_TERMS_URL,
        max_bytes=2_000_000,
        form_body={"query": query, "format": "JSON+COLUMNNAME"},
        media_type="application/json",
        recorded_request_parameters=discovery_params | {"query": query},
    )
    areas = [resolve_package(area) for area in parse_sda_discovery(body)]
    if len(areas) > max_survey_areas:
        reason = f"SSURGO AOI intersects {len(areas)} survey areas; configured limit is {max_survey_areas}"
        rejected_plan: dict[str, Any] = {
            "plan_id": "rejected-before-package-resolution",
            "plan_status": "rejected",
            "aoi": {
                "project_id": context.project_id,
                "aoi_id": context.aoi_id,
                "revision": context.revision,
                "geometry_sha256": context.geometry_sha256,
                "crs": "EPSG:4326",
            },
            "limits": {"max_survey_areas": max_survey_areas, "max_total_bytes": max_total_bytes},
            "survey_areas": areas,
            "rejection_reason": reason,
        }
        rejected_plan["plan_id"] = _plan_id(rejected_plan)
        plan_path = _write_plan(resolved_root, rejected_plan)
        raise SsurgoPlanRejected(f"{reason}; plan written to {plan_path}")

    plan: dict[str, Any] = {
        "plan_status": "planned",
        "aoi": {
            "project_id": context.project_id,
            "aoi_id": context.aoi_id,
            "revision": context.revision,
            "geometry_sha256": context.geometry_sha256,
            "crs": "EPSG:4326",
        },
        "limits": {"max_survey_areas": max_survey_areas, "max_total_bytes": max_total_bytes},
        "discovery": discovery_meta.to_dict(),
        "discovery_request": discovery_params | {"query": query},
        "survey_areas": areas,
    }
    plan["plan_id"] = _plan_id(plan)
    plan_path = _write_plan(resolved_root, plan)

    probe_errors: dict[str, str] = {}
    for area in areas:
        try:
            area.update(_probe_package(http_session, area["package_url"]))
        except Exception as exc:
            probe_errors[area["areasymbol"]] = f"{type(exc).__name__}: {exc}"
            area["provider_reported_size_bytes"] = None
            area["size_status"] = "unavailable"
    if probe_errors:
        plan["plan_status"] = "rejected"
        plan["package_metadata_errors"] = probe_errors
        plan["rejection_reason"] = (
            "Cannot enforce the aggregate SSURGO download limit because one or more official "
            "package sizes are unavailable. No package bodies were downloaded."
        )
        _write_plan(resolved_root, plan)
        raise SsurgoPlanRejected(plan["rejection_reason"])

    total_bytes = sum(int(area["provider_reported_size_bytes"]) for area in areas)
    if total_bytes > max_total_bytes:
        reason = f"SSURGO package plan is {total_bytes} bytes; configured total limit is {max_total_bytes}"
        plan["plan_status"] = "rejected"
        plan["total_provider_reported_size_bytes"] = total_bytes
        plan["rejection_reason"] = reason
        _write_plan(resolved_root, plan)
        raise SsurgoPlanRejected(reason)
    plan["plan_status"] = "ready"
    plan["total_provider_reported_size_bytes"] = total_bytes
    plan["package_metadata_retrieved"] = True
    _write_plan(resolved_root, plan)

    package_results: list[dict[str, Any]] = []
    for area in areas:
        spec = SsurgoPackageSpec(
            areasymbol=area["areasymbol"],
            areaname=area["areaname"],
            provider_package_identifier=area["provider_package_identifier"],
            saversion=area["saversion"],
            saverest_provider=area["saverest_provider"],
            package_url=area["package_url"],
            format=area["format"],
            provider_reported_size_bytes=int(area["provider_reported_size_bytes"]),
            mapunit_count=None,
            plan_metadata={
                "plan_id": plan["plan_id"],
                "aoi_geometry_sha256": context.geometry_sha256,
                "provider_reported_size_bytes": area["provider_reported_size_bytes"],
                "preflight_http": area.get("response_headers", {}),
                "discovery_release": area["provider_release"],
            },
        )

        def acquire(
            _source_id: str,
            root: Path,
            _aoi: Any,
            callback: Callable[[Acquisition], None],
            *,
            package_spec: SsurgoPackageSpec = spec,
        ) -> Any:
            return acquire_ssurgo_package(
                http_session,
                root,
                package_spec,
                acquisition_callback=callback,
            )

        outcome = ingest_source(
            "ssurgo",
            resolved_root,
            project_id=context.project_id,
            aoi_id=context.aoi_id,
            repository=repository,
            acquirer=acquire,
            requested_url=spec.package_url,
        )
        package_results.append(
            {
                "areasymbol": spec.areasymbol,
                "areaname": spec.areaname,
                "provider_package_identifier": spec.provider_package_identifier,
                "package_url": spec.package_url,
                "provider_release": spec.provider_release,
                "provider_reported_size_bytes": spec.provider_reported_size_bytes,
                "candidate": outcome.get("candidate"),
                "run": outcome.get("run"),
            }
        )
    batch = {
        "source": "ssurgo",
        "status": "completed_validation_only"
        if all((item.get("candidate") or {}).get("status") != "failed" for item in package_results)
        else "partial_failure",
        "plan": plan,
        "plan_path": str(plan_path),
        "aoi": plan["aoi"],
        "packages": package_results,
        "acquired_count": sum(
            1 for item in package_results if (item.get("candidate") or {}).get("artifact_path")
        ),
        "failed_count": sum(
            1 for item in package_results if (item.get("candidate") or {}).get("status") == "failed"
        ),
        "promotion_status": "not_promoted",
        "production_ready": False,
        "limitations": [
            "Generic acquisition discovers and validates package containers only.",
            "No staging, repair, clipping, coverage analysis, regional completeness, or promotion is performed.",
            "Hydric-soil fields remain soil information, not a wetlands inventory or regulatory determination.",
        ],
    }
    batch_path = resolved_root / "ssurgo" / "aoi-package-acquisition" / f"{plan['plan_id']}.json"
    write_json(batch_path, batch)
    batch["batch_record_path"] = str(batch_path)
    batch["manifest_path"] = str(_update_manifest(resolved_root, batch))
    return batch
