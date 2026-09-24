"""Derived, auditable PostGIS staging for acquired regional SSURGO packages.

Raw survey-area ZIPs are never rewritten.  This module parses the observed
SSURGO package format and creates project-owned staging records.  Valid source
polygons are retained unchanged; ``make_valid`` is called only for the ten
invalid features covered by the audited discrepancy report.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

import shapefile
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import shape
from shapely.ops import transform
from shapely.validation import explain_validity

from .catalog import SQLiteSourceRepository
from .ssurgo_packages import SSURGO_REGIONAL_SIZING, SsurgoPackageSpec, load_ssurgo_package_specs
from .ssurgo_regional import (
    _clean,
    _polygon_component_count,
    _polygon_ring_count,
    _relative_members,
    _sha256,
    _table,
    load_approved_aoi,
)
from .store import read_json, write_json

AREA_CRS = "EPSG:5070"
SOURCE_CRS = "EPSG:4326"
MAX_AREA_DELTA_PERCENTAGE = 0.1
REPAIR_OPERATION = "shapely.make_valid"


@dataclass(frozen=True)
class RegionalComponentStagingRecord:
    mukey: str
    cokey: str
    comppct_r: float | None
    hydricrating: str
    hydricon: str
    source_attributes: dict[str, Any]


@dataclass(frozen=True)
class RegionalMapUnitStagingRecord:
    mukey: str
    musym: str
    muname: str
    areasymbol: str
    areaname: str
    source_attributes: dict[str, Any]
    components: tuple[RegionalComponentStagingRecord, ...]


@dataclass(frozen=True)
class RegionalFeatureStagingRecord:
    stable_feature_id: str
    source_record_index: int
    mukey: str
    source_geometry_wkt: str
    derived_geometry_wkt: str
    original_valid: bool
    original_validity_reason: str
    original_geometry_type: str
    original_component_count: int
    original_ring_count: int
    original_empty: bool
    original_area_epsg5070_m2: float
    derived_valid: bool
    derived_geometry_type: str
    derived_component_count: int
    derived_ring_count: int
    derived_empty: bool
    derived_area_epsg5070_m2: float
    area_delta_percentage: float | None
    repair_operation: str | None
    geometry_status: str
    attributes_joinable: bool
    source_attributes: dict[str, Any]
    audited_diagnostic: dict[str, Any] | None


@dataclass(frozen=True)
class RegionalPackageStagingRecord:
    batch_id: str
    areasymbol: str
    areaname: str
    provider_package_identifier: str
    source_snapshot_id: str
    source_version_id: str
    ingestion_run_id: str
    candidate_id: str
    source_url: str
    provider_release: str
    retrieved_at: str | None
    terms_url: str
    artifact_path: str
    artifact_sha256: str
    artifact_size_bytes: int
    source_crs: str
    canonical_crs: str
    analysis_crs: str
    map_units: tuple[RegionalMapUnitStagingRecord, ...]
    features: tuple[RegionalFeatureStagingRecord, ...]
    coverage_status: str
    validation_status: str
    staging_status: str
    quarantine_count: int
    provenance: dict[str, Any] = field(default_factory=dict)


def _area(geometry: Any) -> float:
    to_analysis = Transformer.from_crs(SOURCE_CRS, AREA_CRS, always_xy=True).transform
    return float(transform(to_analysis, geometry).area)


def _component_count(geometry: Any) -> int:
    return _polygon_component_count(geometry)


def _number(value: str) -> float | None:
    cleaned = _clean(value)
    return None if not cleaned else float(cleaned)


def _attributes(columns: list[str], row: list[str]) -> dict[str, Any]:
    return {f"column_{index}": value for index, value in enumerate(row)} | {"columns": columns}


def _audited_by_record(
    diagnostics: list[dict[str, Any]],
) -> dict[tuple[str, int], dict[str, Any]]:
    return {
        (str(item.get("mukey", "")), int(item["source_record_index"])): item for item in diagnostics
    }


def _repair_diagnostic(
    geometry: Any,
    *,
    audited: dict[str, Any] | None,
    spec: SsurgoPackageSpec,
    source_record_index: int,
    mukey: str,
    areasymbol: str,
    mapunit_ids: set[str],
    component_counts: dict[str, int],
) -> RegionalFeatureStagingRecord:
    original_area = _area(geometry)
    original_type = geometry.geom_type
    original_components = _component_count(geometry)
    original_rings = _polygon_ring_count(geometry)
    repaired = make_valid(geometry)
    repaired_area = _area(repaired)
    area_delta = (repaired_area - original_area) / original_area * 100 if original_area else None
    polygonal = repaired.geom_type in {"Polygon", "MultiPolygon"}
    joinable = (
        areasymbol == spec.areasymbol
        and mukey in mapunit_ids
        and component_counts.get(mukey, 0) > 0
    )
    accepted = (
        not repaired.is_empty
        and repaired.is_valid
        and polygonal
        and _component_count(repaired) == original_components
        and area_delta is not None
        and abs(area_delta) <= MAX_AREA_DELTA_PERCENTAGE
        and joinable
    )
    status = "repaired_accepted" if accepted else "quarantined"
    return RegionalFeatureStagingRecord(
        stable_feature_id=f"soilmu_a:{spec.areasymbol}:{source_record_index}:{mukey}",
        source_record_index=source_record_index,
        mukey=mukey,
        source_geometry_wkt=geometry.wkt,
        derived_geometry_wkt=repaired.wkt,
        original_valid=False,
        original_validity_reason=explain_validity(geometry),
        original_geometry_type=original_type,
        original_component_count=original_components,
        original_ring_count=original_rings,
        original_empty=geometry.is_empty,
        original_area_epsg5070_m2=original_area,
        derived_valid=bool(repaired.is_valid),
        derived_geometry_type=repaired.geom_type,
        derived_component_count=_component_count(repaired),
        derived_ring_count=_polygon_ring_count(repaired),
        derived_empty=bool(repaired.is_empty),
        derived_area_epsg5070_m2=repaired_area,
        area_delta_percentage=area_delta,
        repair_operation=REPAIR_OPERATION,
        geometry_status=status,
        attributes_joinable=joinable,
        source_attributes={
            "areasymbol": areasymbol,
            "mukey": mukey,
            "audited_stable_feature_id": (audited or {}).get("stable_feature_id"),
        },
        audited_diagnostic=audited,
    )


def _unchanged_feature(
    geometry: Any,
    *,
    source_record_index: int,
    mukey: str,
    source_attributes: dict[str, Any],
    spec: SsurgoPackageSpec,
) -> RegionalFeatureStagingRecord:
    area = _area(geometry)
    return RegionalFeatureStagingRecord(
        stable_feature_id=f"soilmu_a:{spec.areasymbol}:{source_record_index}:{mukey}",
        source_record_index=source_record_index,
        mukey=mukey,
        source_geometry_wkt=geometry.wkt,
        derived_geometry_wkt=geometry.wkt,
        original_valid=True,
        original_validity_reason="Valid Geometry",
        original_geometry_type=geometry.geom_type,
        original_component_count=_component_count(geometry),
        original_ring_count=_polygon_ring_count(geometry),
        original_empty=bool(geometry.is_empty),
        original_area_epsg5070_m2=area,
        derived_valid=True,
        derived_geometry_type=geometry.geom_type,
        derived_component_count=_component_count(geometry),
        derived_ring_count=_polygon_ring_count(geometry),
        derived_empty=bool(geometry.is_empty),
        derived_area_epsg5070_m2=area,
        area_delta_percentage=0.0,
        repair_operation=None,
        geometry_status="unchanged_valid",
        attributes_joinable=True,
        source_attributes=source_attributes,
        audited_diagnostic=None,
    )


def parse_regional_package_for_staging(
    artifact_path: Path,
    spec: SsurgoPackageSpec,
    *,
    candidate: dict[str, Any],
    audited_diagnostics: list[dict[str, Any]],
    batch_id: str | None = None,
) -> RegionalPackageStagingRecord:
    """Parse one package and derive only the audited invalid geometries."""
    if not artifact_path.is_file():
        raise FileNotFoundError(artifact_path)
    if candidate.get("source_id") != "ssurgo":
        raise ValueError("Regional SSURGO staging requires an SSURGO candidate")
    source_version_id = str(candidate.get("version_id") or "")
    if not source_version_id:
        raise ValueError(f"{spec.areasymbol} candidate has no source version")
    with ZipFile(artifact_path) as archive:
        root, _ = _relative_members(archive)
        members = {name.lower(): name for name in archive.namelist()}
        mapunit_member = members[f"{root.lower()}/tabular/mapunit.txt"]
        component_member = members[f"{root.lower()}/tabular/comp.txt"]
        legend_member = members[f"{root.lower()}/tabular/legend.txt"]
        catalog_member = members[f"{root.lower()}/tabular/sacatlog.txt"]
        mapunit_rows = _table(archive, mapunit_member)
        component_rows = _table(archive, component_member)
        legend_rows = _table(archive, legend_member)
        catalog_rows = _table(archive, catalog_member)
        package_names = [
            _clean(legend_rows[0][2]) if legend_rows and len(legend_rows[0]) > 2 else "",
            _clean(catalog_rows[0][1]) if catalog_rows and len(catalog_rows[0]) > 1 else "",
        ]
        package_names = [name for name in package_names if name]
        if not package_names or len(set(package_names)) != 1:
            raise ValueError(f"{spec.areasymbol} package survey names are missing or inconsistent")
        package_name = package_names[0]
        if any(len(row) != 24 for row in mapunit_rows):
            raise ValueError(f"{spec.areasymbol} mapunit.txt does not use the 24-column layout")
        if any(len(row) != 109 for row in component_rows):
            raise ValueError(f"{spec.areasymbol} comp.txt does not use the 109-column layout")
        mapunit_data: dict[str, dict[str, Any]] = {}
        component_data: dict[str, list[RegionalComponentStagingRecord]] = {}
        component_counts: dict[str, int] = {}
        for row in mapunit_rows:
            mukey, musym, muname = _clean(row[23]), _clean(row[0]), _clean(row[1])
            if not mukey or not musym or not muname:
                raise ValueError(f"{spec.areasymbol} contains an incomplete mapunit row")
            mapunit_data[mukey] = {
                "mukey": mukey,
                "musym": musym,
                "muname": muname,
                "areasymbol": spec.areasymbol,
                "areaname": package_name,
                "source_attributes": _attributes(
                    [f"mapunit_{index}" for index in range(len(row))], row
                ),
            }
        for row in component_rows:
            mukey, cokey = _clean(row[107]), _clean(row[108])
            if not mukey or not cokey or mukey not in mapunit_data:
                raise ValueError(f"{spec.areasymbol} has an unjoinable component {mukey}/{cokey}")
            component = RegionalComponentStagingRecord(
                mukey=mukey,
                cokey=cokey,
                comppct_r=_number(row[1]),
                hydricrating=_clean(row[22]),
                hydricon=_clean(row[21]),
                source_attributes=_attributes(
                    [f"component_{index}" for index in range(len(row))], row
                ),
            )
            component_data.setdefault(mukey, []).append(component)
            component_counts[mukey] = component_counts.get(mukey, 0) + 1
        if set(component_data) != set(mapunit_data):
            missing = sorted(set(mapunit_data) - set(component_data))[:20]
            raise ValueError(f"{spec.areasymbol} mapunits lack components: {missing}")
        map_units = tuple(
            RegionalMapUnitStagingRecord(
                **values,
                components=tuple(sorted(component_data[mukey], key=lambda item: item.cokey)),
            )
            for mukey, values in sorted(mapunit_data.items())
        )
        layer_base = f"{root}/spatial/soilmu_a_{spec.areasymbol.lower()}"
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(members[f"{layer_base.lower()}.shp"])),
            shx=io.BytesIO(archive.read(members[f"{layer_base.lower()}.shx"])),
            dbf=io.BytesIO(archive.read(members[f"{layer_base.lower()}.dbf"])),
        )
        audited = _audited_by_record(audited_diagnostics)
        features: list[RegionalFeatureStagingRecord] = []
        invalid_count = 0
        for index, (item, record) in enumerate(zip(reader.shapes(), reader.records(), strict=True)):
            geometry = shape(item.__geo_interface__)
            values = record.as_dict()
            mukey = _clean(values.get("MUKEY"))
            source_attributes = {str(key): value for key, value in values.items()}
            if geometry.is_valid and not geometry.is_empty:
                if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                    raise ValueError(
                        f"{spec.areasymbol} valid soilmu_a feature {index}/{mukey} is not polygonal"
                    )
                feature = _unchanged_feature(
                    geometry,
                    source_record_index=index,
                    mukey=mukey,
                    source_attributes=source_attributes,
                    spec=spec,
                )
            else:
                invalid_count += 1
                audited_item = audited.get((mukey, index))
                if audited_item is None:
                    raise ValueError(
                        f"{spec.areasymbol} invalid feature {index}/{mukey} is not in the audited repair report"
                    )
                feature = _repair_diagnostic(
                    geometry,
                    audited=audited_item,
                    spec=spec,
                    source_record_index=index,
                    mukey=mukey,
                    areasymbol=_clean(values.get("AREASYMBOL")),
                    mapunit_ids=set(mapunit_data),
                    component_counts=component_counts,
                )
                feature = RegionalFeatureStagingRecord(
                    **{**feature.__dict__, "source_attributes": source_attributes}
                )
            features.append(feature)
        audited_ids = {
            (str(item.get("mukey", "")), int(item["source_record_index"]))
            for item in audited_diagnostics
        }
        observed_ids = {
            (feature.mukey, feature.source_record_index)
            for feature in features
            if not feature.original_valid
        }
        if observed_ids != audited_ids:
            raise ValueError(
                f"{spec.areasymbol} invalid-feature set differs from audited report: "
                f"observed={len(observed_ids)} audited={len(audited_ids)}"
            )
    quarantine_count = sum(feature.geometry_status == "quarantined" for feature in features)
    validation_status = "conditionally_validated" if invalid_count else "validated"
    return RegionalPackageStagingRecord(
        batch_id=batch_id or f"ssurgo-regional-{spec.areasymbol.lower()}-{source_version_id}",
        areasymbol=spec.areasymbol,
        areaname=package_name,
        provider_package_identifier=spec.provider_package_identifier,
        source_snapshot_id=f"ssurgo-package:{spec.areasymbol}",
        source_version_id=source_version_id,
        ingestion_run_id=str(candidate.get("run_id") or ""),
        candidate_id=str(candidate.get("candidate_id") or ""),
        source_url=str(candidate.get("source_url") or spec.package_url),
        provider_release=str(candidate.get("provider_release") or spec.provider_release),
        retrieved_at=candidate.get("retrieved_at"),
        terms_url=str(
            candidate.get("terms_url")
            or "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo"
        ),
        artifact_path=str(artifact_path),
        artifact_sha256=_sha256(artifact_path),
        artifact_size_bytes=artifact_path.stat().st_size,
        source_crs=SOURCE_CRS,
        canonical_crs=SOURCE_CRS,
        analysis_crs=AREA_CRS,
        map_units=map_units,
        features=tuple(features),
        coverage_status="intersects",
        validation_status=validation_status,
        staging_status="quarantined" if quarantine_count else "complete",
        quarantine_count=quarantine_count,
        provenance={
            "source_package": spec.areasymbol,
            "sizing_record_areaname": spec.areaname,
            "package_metadata_areaname": package_name,
            "source_format": "SSURGO survey-area ZIP: ESRI Shapefile plus pipe-delimited tables",
            "repair_policy": {
                "operation": REPAIR_OPERATION,
                "area_crs": AREA_CRS,
                "max_area_delta_percentage": MAX_AREA_DELTA_PERCENTAGE,
                "accepted_requirements": [
                    "valid",
                    "nonempty",
                    "polygonal",
                    "same polygon component count",
                    "joinable source attributes",
                ],
            },
            "audited_repair_report": "external manifest ssurgo_regional_discrepancy_audit",
            "hydric_interpretation": "soil information only; not a wetlands inventory or regulatory determination",
            "original_geometry_preserved": True,
            "source_maturity_unchanged": True,
        },
    )


def _latest_audit_reports(data_root: Path) -> dict[str, list[dict[str, Any]]]:
    manifest = read_json(data_root / "manifest.json")
    pointer = manifest.get("ssurgo_regional_discrepancy_audit", {})
    aggregate_path = Path(str(pointer.get("latest_aggregate_report", "")))
    if not aggregate_path.is_file():
        raise FileNotFoundError("Latest SSURGO discrepancy aggregate report is unavailable")
    aggregate = read_json(aggregate_path)
    result: dict[str, list[dict[str, Any]]] = {}
    for relative in aggregate.get("package_reports", []):
        report = read_json(aggregate_path.parent / relative)
        result[str(report["areasymbol"])] = report.get("geometry_diagnostics", [])
    if len(result) != 19:
        raise ValueError("SSURGO discrepancy report does not contain all 19 package diagnostics")
    return result


def _candidate_for_spec(
    candidates: list[dict[str, Any]], spec: SsurgoPackageSpec
) -> dict[str, Any]:
    matches = [item for item in candidates if item.get("provider_release") == spec.provider_release]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one acquired candidate for {spec.areasymbol}, found {len(matches)}"
        )
    candidate = matches[0]
    if candidate.get("status") not in {"incomplete", "validated"}:
        raise ValueError(f"{spec.areasymbol} candidate is not an acquired inactive candidate")
    return candidate


def _update_manifest(data_root: Path, reports: list[dict[str, Any]], aggregate_path: Path) -> None:
    manifest_path = data_root / "manifest.json"
    manifest = read_json(manifest_path)
    by_sha = {str(item.get("sha256")): item for item in manifest.get("artifacts", [])}
    for report in reports:
        entry = by_sha.get(report["artifact_sha256"])
        if entry is not None:
            entry["regional_staging_report"] = report["report_path"]
            entry["regional_staging_status"] = report["staging_status"]
            entry["regional_staging_batch_id"] = report["batch_id"]
    manifest["ssurgo_regional_staging"] = {
        "latest_aggregate_report": str(aggregate_path),
        "aggregate_report_sha256": _sha256(aggregate_path),
        "package_count": len(reports),
        "feature_count": sum(report["feature_count"] for report in reports),
        "repaired_accepted_count": sum(report["repaired_accepted_count"] for report in reports),
        "quarantined_count": sum(report["quarantined_count"] for report in reports),
        "raw_packages_unchanged": True,
        "source_candidates_unchanged": True,
        "active_source_version_created": False,
    }
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)


def stage_ssurgo_regional_packages(
    data_root: Path,
    *,
    database_url: str | None = None,
    sizing_record: Path | None = None,
    boundary_path: Path | None = None,
    repository: Any | None = None,
) -> dict[str, Any]:
    """Stage all 19 acquired packages without production promotion."""
    from .spatial import PostGISRepository

    sizing_path = sizing_record or data_root / SSURGO_REGIONAL_SIZING
    specs = load_ssurgo_package_specs(sizing_path)
    load_approved_aoi(data_root, boundary_path)
    catalog = SQLiteSourceRepository(data_root)
    candidates = catalog.list_candidates("ssurgo")
    audit_reports = _latest_audit_reports(data_root)
    spatial = repository or PostGISRepository(database_url)
    spatial.migrate()
    run_id = str(uuid4())
    output_dir = data_root / "ssurgo" / "regional-staging" / run_id
    package_dir = output_dir / "packages"
    reports: list[dict[str, Any]] = []
    for spec in specs:
        candidate = _candidate_for_spec(candidates, spec)
        package = parse_regional_package_for_staging(
            Path(str(candidate["artifact_path"])),
            spec,
            candidate=candidate,
            audited_diagnostics=audit_reports.get(spec.areasymbol, []),
        )
        stored = spatial.stage_ssurgo_regional_package(package)
        report = {
            "areasymbol": package.areasymbol,
            "areaname": package.areaname,
            "batch_id": package.batch_id,
            "source_snapshot_id": package.source_snapshot_id,
            "source_version_id": package.source_version_id,
            "candidate_id": package.candidate_id,
            "ingestion_run_id": package.ingestion_run_id,
            "artifact_path": package.artifact_path,
            "artifact_sha256": package.artifact_sha256,
            "artifact_size_bytes": package.artifact_size_bytes,
            "feature_count": len(package.features),
            "map_unit_count": len(package.map_units),
            "component_count": sum(len(item.components) for item in package.map_units),
            "original_invalid_count": sum(not item.original_valid for item in package.features),
            "repaired_accepted_count": sum(
                item.geometry_status == "repaired_accepted" for item in package.features
            ),
            "quarantined_count": package.quarantine_count,
            "validation_status": package.validation_status,
            "staging_status": package.staging_status,
            "idempotent": bool(stored.get("idempotent")),
            "provenance": package.provenance,
            "report_path": str(package_dir / f"{package.areasymbol}.json"),
        }
        write_json(package_dir / f"{package.areasymbol}.json", report)
        reports.append(report)
    aggregate = {
        "staging_run_id": run_id,
        "source_id": "ssurgo",
        "status": "completed_with_quarantines"
        if any(item["quarantined_count"] for item in reports)
        else "completed",
        "package_count": len(reports),
        "feature_count": sum(item["feature_count"] for item in reports),
        "map_unit_count": sum(item["map_unit_count"] for item in reports),
        "component_count": sum(item["component_count"] for item in reports),
        "original_invalid_count": sum(item["original_invalid_count"] for item in reports),
        "repaired_accepted_count": sum(item["repaired_accepted_count"] for item in reports),
        "quarantined_count": sum(item["quarantined_count"] for item in reports),
        "area_crs": AREA_CRS,
        "repair_policy": "Owner-approved derived staging only; no active source promotion.",
        "packages": [f"packages/{item['areasymbol']}.json" for item in reports],
        "raw_packages_unchanged": True,
        "source_candidates_unchanged": True,
        "active_source_version_created": False,
        "postgis_staging_only": True,
        "limitations": [
            "Original source geometries and attributes remain preserved in staging and raw packages.",
            "Staging is not canonical production data and does not create an active SSURGO version.",
            "Hydric attributes remain soil information, not a wetlands inventory or regulatory determination.",
        ],
    }
    aggregate_path = output_dir / "aggregate.json"
    write_json(aggregate_path, aggregate)
    _update_manifest(data_root, reports, aggregate_path)
    aggregate["aggregate_report_path"] = str(aggregate_path)
    return aggregate
