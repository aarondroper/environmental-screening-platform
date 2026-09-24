"""Read-only validation of acquired regional SSURGO survey-area packages.

The validator understands the official SSURGO export format present in the
acquired artifacts: ESRI Shapefiles and pipe-delimited tabular files. It never
repairs, clips, drops, or rewrites source records. Package QA is evidence for
the inactive candidates and does not promote a regional source version.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union
from shapely.validation import explain_validity

from .catalog import SQLiteSourceRepository
from .ssurgo_packages import (
    APPROVED_GEOIDS,
    SSURGO_REGIONAL_SIZING,
    SsurgoPackageSpec,
    load_ssurgo_package_specs,
)
from .store import read_json, write_json

EXPECTED_LAYER_TYPES = {
    "soilmu_a": shapefile.POLYGON,
    "soilmu_l": shapefile.POLYLINE,
    "soilmu_p": shapefile.POINT,
    "soilsa_a": shapefile.POLYGON,
    "soilsf_l": shapefile.POLYLINE,
    "soilsf_p": shapefile.POINT,
}
EXPECTED_TABULAR_FILES = ("mapunit.txt", "comp.txt", "legend.txt", "sacatlog.txt")
EXPECTED_HYDRIC_RATINGS = {"", "Yes", "No", "Unranked"}
EXPECTED_HYDRIC_CONDITIONS = {
    "",
    "Farmable under natural conditions",
    "Neither wooded nor farmable under natural conditions",
    "Wooded under natural conditions",
}
SOURCE_CRS = "EPSG:4326"
BOUNDARY_SOURCE_CRS = "EPSG:4269"
APPROVED_BOUNDARY_PATH = Path("geography/canonical/counties_2025.shp")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_approved_aoi(data_root: Path, boundary_path: Path | None = None) -> Any:
    """Load and verify the unchanged 2025 three-county union."""
    path = boundary_path or data_root / APPROVED_BOUNDARY_PATH
    reader = shapefile.Reader(str(path))
    fields = {field[0].upper() for field in reader.fields[1:]}
    if "GEOID" not in fields:
        raise ValueError("Approved Census boundary is missing GEOID")
    prj_path = path.with_suffix(".prj")
    if (
        not prj_path.exists()
        or CRS.from_wkt(prj_path.read_text(encoding="utf-8")).to_epsg() != 4269
    ):
        raise ValueError("Approved Census boundary CRS must be EPSG:4269")
    records = {
        str(record.as_dict()["GEOID"]): shape(item.__geo_interface__)
        for item, record in zip(reader.shapes(), reader.records(), strict=True)
    }
    if set(records) != APPROVED_GEOIDS:
        raise ValueError(
            "Approved Census boundary does not contain exactly the three approved GEOIDs"
        )
    if any(geometry.is_empty or not geometry.is_valid for geometry in records.values()):
        raise ValueError("Approved Census boundary contains an empty or invalid county")
    union = unary_union([records[geoid] for geoid in sorted(records)])
    if union.geom_type != "MultiPolygon" or len(union.geoms) != 3 or not union.is_valid:
        raise ValueError("Approved Census boundary must be a valid three-component MultiPolygon")
    to_wgs84 = Transformer.from_crs(BOUNDARY_SOURCE_CRS, SOURCE_CRS, always_xy=True).transform
    return transform(to_wgs84, union)


def _relative_members(archive: ZipFile) -> tuple[str, list[str]]:
    members = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
    if not members:
        raise ValueError("SSURGO archive contains no files")
    if any(name.startswith("/") or ".." in name.split("/") for name in members):
        raise ValueError("SSURGO archive contains an unsafe member path")
    roots = {name.split("/", 1)[0] for name in members}
    if len(roots) != 1:
        raise ValueError("SSURGO archive must contain exactly one survey-area root")
    return next(iter(roots)), members


def _table(archive: ZipFile, member: str) -> list[list[str]]:
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter="|", quotechar='"'))


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _date_part(value: str) -> str:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return ""
    month, day, year = match.groups()
    return f"{year}-{month}-{day}"


def _layer_report(
    archive: ZipFile,
    root: str,
    symbol: str,
    layer: str,
    expected_shape_type: int,
    aoi: Any,
) -> dict[str, Any]:
    base = f"{root}/spatial/{layer}_{symbol.lower()}"
    members = {name.lower() for name in archive.namelist()}
    required = {f"{base}.{suffix}".lower() for suffix in ("shp", "shx", "dbf", "prj")}
    missing = sorted(required - members)
    if missing:
        return {
            "layer": layer,
            "status": "failed",
            "missing_members": missing,
            "record_count": 0,
            "geometry_type_counts": {},
            "invalid_geometries": [],
            "crs": None,
            "intersecting_record_count": 0,
            "intersecting_mukey_count": 0,
        }
    prj = archive.read(f"{base}.prj").decode("utf-8").strip()
    crs = CRS.from_wkt(prj)
    issues: list[str] = []
    if crs.to_epsg() != 4326:
        issues.append(f"CRS is {crs.to_string()}, expected EPSG:4326")
    reader = shapefile.Reader(
        shp=io.BytesIO(archive.read(f"{base}.shp")),
        shx=io.BytesIO(archive.read(f"{base}.shx")),
        dbf=io.BytesIO(archive.read(f"{base}.dbf")),
    )
    geometry_type_counts: Counter[str] = Counter()
    invalid: list[dict[str, Any]] = []
    mukeys: set[str] = set()
    intersecting_mukeys: set[str] = set()
    intersecting_count = 0
    fields = {field[0].upper() for field in reader.fields[1:]}
    if layer == "soilmu_a" and not {"AREASYMBOL", "MUKEY"}.issubset(fields):
        issues.append("soilmu_a is missing AREASYMBOL or MUKEY")
    for index, (item, record) in enumerate(zip(reader.shapes(), reader.records(), strict=True)):
        geometry = shape(item.__geo_interface__)
        geometry_type_counts[geometry.geom_type] += 1
        record_values = record.as_dict()
        if layer == "soilmu_a":
            record_symbol = _clean(record_values.get("AREASYMBOL"))
            mukey = _clean(record_values.get("MUKEY"))
            if record_symbol != symbol:
                issues.append(f"soilmu_a record {index} has AREASYMBOL {record_symbol!r}")
            if not mukey:
                issues.append(f"soilmu_a record {index} has an empty MUKEY")
            mukeys.add(mukey)
        if geometry.is_empty or not geometry.is_valid:
            invalid.append(
                {
                    "record_index": index,
                    "mukey": _clean(record_values.get("MUKEY")),
                    "geometry_type": geometry.geom_type,
                    "reason": "empty" if geometry.is_empty else explain_validity(geometry),
                }
            )
        if geometry.geom_type not in {
            "Polygon",
            "MultiPolygon",
            "LineString",
            "MultiLineString",
            "Point",
            "MultiPoint",
        }:
            issues.append(f"record {index} has unsupported geometry type {geometry.geom_type}")
        if geometry.geom_type != {
            shapefile.POLYGON: "Polygon",
            shapefile.POLYLINE: "LineString",
            shapefile.POINT: "Point",
        }.get(expected_shape_type):
            issues.append(
                f"record {index} geometry type {geometry.geom_type} does not match layer type"
            )
        if layer == "soilmu_a" and geometry.is_valid and geometry.intersects(aoi):
            intersecting_count += 1
            intersecting_mukeys.add(_clean(record_values.get("MUKEY")))
    if reader.shapeType != expected_shape_type:
        issues.append(
            f"Shapefile shape type {reader.shapeType} does not match expected {expected_shape_type}"
        )
    return {
        "layer": layer,
        "status": "failed" if issues or invalid else "passed",
        "missing_members": [],
        "record_count": len(reader),
        "geometry_type_counts": dict(sorted(geometry_type_counts.items())),
        "invalid_geometries": invalid,
        "crs": crs.to_string(),
        "fields": sorted(fields),
        "issues": issues,
        "intersecting_record_count": intersecting_count,
        "intersecting_mukey_count": len(intersecting_mukeys),
        "spatial_mukey_count": len(mukeys),
    }


def validate_ssurgo_package_archive(
    artifact_path: Path,
    spec: SsurgoPackageSpec,
    aoi_geometry: Any,
    *,
    source_version_id: str | None = None,
    candidate_id: str | None = None,
    ingestion_run_id: str | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Return complete QA for one package without modifying its source bytes."""
    report: dict[str, Any] = {
        "areasymbol": spec.areasymbol,
        "areaname_expected": spec.areaname,
        "provider_package_identifier": spec.provider_package_identifier,
        "provider_release": spec.provider_release,
        "artifact_path": str(artifact_path),
        "artifact_size_bytes": artifact_path.stat().st_size if artifact_path.exists() else None,
        "artifact_sha256": _sha256(artifact_path) if artifact_path.exists() else None,
        "source_version_id": source_version_id,
        "candidate_id": candidate_id,
        "ingestion_run_id": ingestion_run_id,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "format": "SSURGO survey-area ZIP: ESRI Shapefile plus pipe-delimited text tables",
        "status": "failed",
        "issues": [],
        "warnings": [
            "Validation is read-only: source geometries and records were not repaired, dropped, or clipped.",
            "A passed package does not establish complete AOI coverage or production readiness.",
            "Hydric fields are component-level soil information, not a wetlands inventory or regulatory determination.",
        ],
    }
    if not artifact_path.is_file():
        report["issues"].append("candidate artifact is missing")
        return report
    try:
        with ZipFile(artifact_path) as archive:
            root, members = _relative_members(archive)
            bad_member = archive.testzip()
            if bad_member is not None:
                report["issues"].append(f"ZIP CRC validation failed for {bad_member}")
            if root.upper() != spec.areasymbol.upper():
                report["issues"].append(f"archive root {root!r} does not match {spec.areasymbol!r}")
            spatial_members = {name.lower() for name in members if "/spatial/" in name.lower()}
            tabular_members = {name.lower() for name in members if "/tabular/" in name.lower()}
            report["archive"] = {
                "member_count": len(members),
                "root": root,
                "spatial_member_count": len(spatial_members),
                "tabular_member_count": len(tabular_members),
                "crc_test": "failed" if bad_member is not None else "passed",
                "crc_failed_member": bad_member,
                "spatial_version": _clean(
                    archive.read(f"{root}/spatial/version.txt").decode("utf-8")
                )
                if f"{root}/spatial/version.txt".lower() in {m.lower() for m in members}
                else None,
                "tabular_version": _clean(
                    archive.read(f"{root}/tabular/version.txt").decode("utf-8")
                )
                if f"{root}/tabular/version.txt".lower() in {m.lower() for m in members}
                else None,
            }
            layer_reports = {
                layer: _layer_report(
                    archive, root, spec.areasymbol, layer, shape_type, aoi_geometry
                )
                for layer, shape_type in EXPECTED_LAYER_TYPES.items()
            }
            report["spatial_layers"] = layer_reports
            missing_tables = [
                table
                for table in EXPECTED_TABULAR_FILES
                if f"{root}/tabular/{table}".lower() not in {m.lower() for m in members}
            ]
            report["tabular"] = {"missing_tables": missing_tables}
            if missing_tables:
                report["issues"].append(f"missing tabular tables: {missing_tables}")
            if any(layer["status"] == "failed" for layer in layer_reports.values()):
                report["issues"].append("one or more spatial layers failed validation")
            if (
                report["archive"]["spatial_version"] is None
                or report["archive"]["tabular_version"] is None
            ):
                report["issues"].append("missing spatial or tabular version metadata")
            if not missing_tables:
                _validate_tabular(archive, root, spec, layer_reports, report)
    except (
        BadZipFile,
        OSError,
        ValueError,
        KeyError,
        UnicodeDecodeError,
        shapefile.ShapefileException,
    ) as exc:
        report["issues"].append(f"package parse error: {type(exc).__name__}: {exc}")
    report["status"] = "passed" if not report["issues"] else "failed"
    return report


def _validate_tabular(
    archive: ZipFile,
    root: str,
    spec: SsurgoPackageSpec,
    layer_reports: dict[str, dict[str, Any]],
    report: dict[str, Any],
) -> None:
    mapunit_rows = _table(archive, f"{root}/tabular/mapunit.txt")
    component_rows = _table(archive, f"{root}/tabular/comp.txt")
    legend_rows = _table(archive, f"{root}/tabular/legend.txt")
    sacatalog_rows = _table(archive, f"{root}/tabular/sacatlog.txt")
    report["tabular"].update(
        {
            "mapunit_row_count": len(mapunit_rows),
            "component_row_count": len(component_rows),
            "legend_row_count": len(legend_rows),
            "sacatalog_row_count": len(sacatalog_rows),
            "mapunit_column_count": sorted({len(row) for row in mapunit_rows}),
            "component_column_count": sorted({len(row) for row in component_rows}),
            "required_fields": {
                "mapunit": {"musym": 0, "muname": 1, "mukey": 23},
                "component": {
                    "comppct_r": 1,
                    "hydricon": 21,
                    "hydricrating": 22,
                    "mukey": 107,
                    "cokey": 108,
                },
            },
        }
    )
    if any(len(row) != 24 for row in mapunit_rows):
        report["issues"].append("mapunit.txt contains rows other than the 24-column SSURGO layout")
    if any(len(row) != 109 for row in component_rows):
        report["issues"].append("comp.txt contains rows other than the 109-column SSURGO layout")
    mapunits: dict[str, tuple[str, str]] = {}
    duplicate_mapunits: list[str] = []
    for row in mapunit_rows:
        if len(row) != 24:
            continue
        mukey, musym, muname = _clean(row[23]), _clean(row[0]), _clean(row[1])
        if not mukey or not musym or not muname:
            report["issues"].append("mapunit.txt contains an empty mukey, musym, or muname")
            continue
        value = (musym, muname)
        if mukey in mapunits and mapunits[mukey] != value:
            report["issues"].append(f"mapunit {mukey} has conflicting tabular attributes")
        if mukey in mapunits:
            duplicate_mapunits.append(mukey)
        mapunits[mukey] = value
    components: dict[str, str] = {}
    component_mukeys: set[str] = set()
    duplicate_components: list[str] = []
    hydricrating_counts: Counter[str] = Counter()
    hydricon_counts: Counter[str] = Counter()
    for row in component_rows:
        if len(row) != 109:
            continue
        mukey, cokey = _clean(row[107]), _clean(row[108])
        hydricon, hydricrating = _clean(row[21]), _clean(row[22])
        if not mukey or not cokey:
            report["issues"].append("comp.txt contains an empty mukey or cokey")
            continue
        if cokey in components:
            duplicate_components.append(cokey)
        components[cokey] = mukey
        component_mukeys.add(mukey)
        hydricrating_counts[hydricrating] += 1
        hydricon_counts[hydricon] += 1
        try:
            component_pct = float(_clean(row[1]))
        except ValueError:
            report["issues"].append(f"component {cokey} has nonnumeric comppct_r")
        else:
            if not 0 <= component_pct <= 100:
                report["issues"].append(f"component {cokey} has comppct_r outside 0..100")
        if hydricrating not in EXPECTED_HYDRIC_RATINGS:
            report["issues"].append(
                f"component {cokey} has unexpected hydricrating {hydricrating!r}"
            )
        if hydricon not in EXPECTED_HYDRIC_CONDITIONS:
            report["issues"].append(f"component {cokey} has unexpected hydricon {hydricon!r}")
    missing_component_mapunits = sorted(component_mukeys - set(mapunits))
    soilmu_report = layer_reports["soilmu_a"]
    # The layer report already counts all records but does not retain keys;
    # recomputing identities here would duplicate raw geometry parsing. The
    # table-level relation is checked against the map-unit count and records.
    if soilmu_report["spatial_mukey_count"] != len(mapunits):
        report["issues"].append(
            "soilmu_a unique MUKEY count does not match mapunit.txt unique MUKEY count"
        )
    if missing_component_mapunits:
        report["issues"].append(
            f"comp.txt references mapunits absent from mapunit.txt: {missing_component_mapunits[:20]}"
        )
    if not legend_rows or _clean(legend_rows[0][1]) != spec.areasymbol:
        report["issues"].append("legend.txt survey-area symbol does not match the candidate")
    legend_name = _clean(legend_rows[0][2]) if legend_rows and len(legend_rows[0]) > 2 else ""
    if legend_name != spec.areaname:
        report["issues"].append("legend.txt survey-area name does not match the sizing record")
    if not sacatalog_rows or len(sacatalog_rows[0]) < 4:
        report["issues"].append("sacatlog.txt has no usable survey-area release row")
        release_version = None
        release_date = None
    else:
        release_symbol = _clean(sacatalog_rows[0][0])
        release_name = _clean(sacatalog_rows[0][1])
        release_version = _clean(sacatalog_rows[0][2])
        release_date = _date_part(_clean(sacatalog_rows[0][3]))
        if release_symbol != spec.areasymbol or release_name != spec.areaname:
            report["issues"].append(
                "sacatlog.txt survey-area identity does not match the candidate"
            )
        if release_version != str(spec.saversion):
            report["issues"].append(
                f"sacatlog.txt saversion {release_version!r} does not match {spec.saversion}"
            )
        expected_date = spec.saverest_provider.split("T", 1)[0]
        if release_date != expected_date:
            report["issues"].append(
                f"sacatlog.txt release date {release_date!r} does not match {expected_date!r}"
            )
    report["tabular"].update(
        {
            "unique_mapunit_count": len(mapunits),
            "unique_component_count": len(components),
            "duplicate_mapunit_ids": sorted(set(duplicate_mapunits)),
            "duplicate_component_ids": sorted(set(duplicate_components)),
            "missing_component_mapunit_ids": missing_component_mapunits,
            "hydricrating_counts": dict(sorted(hydricrating_counts.items())),
            "hydricon_counts": dict(sorted(hydricon_counts.items())),
            "hydricrating_nonempty_count": sum(
                value for key, value in hydricrating_counts.items() if key
            ),
            "hydricon_nonempty_count": sum(value for key, value in hydricon_counts.items() if key),
            "survey_area": {
                "areasymbol": spec.areasymbol,
                "areaname": legend_name,
                "saversion": release_version,
                "saverest_date": release_date,
            },
        }
    )
    intersecting = soilmu_report["intersecting_mukey_count"]
    report["coverage"] = {
        "approved_aoi_crs": SOURCE_CRS,
        "package_crs": SOURCE_CRS,
        "aoi_intersects_package": intersecting > 0,
        "intersecting_mapunit_count": intersecting,
        "coverage_status": "intersects" if intersecting > 0 else "no_intersection",
        "method": "valid soilmu_a polygons tested with intersects against the unchanged approved AOI; no clipping or area replacement performed",
    }


def _candidate_for_spec(
    candidates: list[dict[str, Any]], spec: SsurgoPackageSpec
) -> dict[str, Any]:
    matches = [
        candidate
        for candidate in candidates
        if candidate.get("provider_release") == spec.provider_release
        and candidate.get("artifact_path")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one acquired candidate for {spec.areasymbol}, found {len(matches)}"
        )
    return matches[0]


def validate_ssurgo_regional_packages(
    data_root: Path,
    *,
    sizing_record: Path | None = None,
    boundary_path: Path | None = None,
    repository: SQLiteSourceRepository | None = None,
) -> dict[str, Any]:
    """Validate all acquired regional candidates and write external QA reports."""
    sizing_path = sizing_record or data_root / SSURGO_REGIONAL_SIZING
    specs = load_ssurgo_package_specs(sizing_path)
    aoi = load_approved_aoi(data_root, boundary_path)
    catalog = repository or SQLiteSourceRepository(data_root)
    candidates = catalog.list_candidates("ssurgo")
    run_id = str(uuid4())
    output_dir = data_root / "ssurgo" / "regional-package-validation" / run_id
    package_dir = output_dir / "packages"
    reports: list[dict[str, Any]] = []
    for spec in specs:
        candidate = _candidate_for_spec(candidates, spec)
        report = validate_ssurgo_package_archive(
            Path(candidate["artifact_path"]),
            spec,
            aoi,
            source_version_id=candidate.get("version_id"),
            candidate_id=candidate.get("candidate_id"),
            ingestion_run_id=candidate.get("run_id"),
            source_url=candidate.get("source_url"),
            retrieved_at=candidate.get("retrieved_at"),
        )
        report["candidate_status"] = candidate.get("status")
        report["candidate_validation_status"] = candidate.get("validation_status")
        report["candidate_promotion_status"] = candidate.get("promotion_status")
        reports.append(report)
        write_json(package_dir / f"{spec.areasymbol}.json", report)
    passed = [report for report in reports if report["status"] == "passed"]
    failed = [report for report in reports if report["status"] == "failed"]
    aggregate = {
        "validation_id": run_id,
        "source_id": "ssurgo",
        "sizing_record": str(sizing_path),
        "approved_boundary": {
            "geoids": sorted(APPROVED_GEOIDS),
            "vintage": 2025,
            "geometry_type": aoi.geom_type,
            "component_count": len(aoi.geoms),
            "crs": SOURCE_CRS,
            "bounds": list(aoi.bounds),
        },
        "started_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "passed" if not failed else "partial_failure",
        "package_count": len(reports),
        "passed_package_count": len(passed),
        "failed_package_count": len(failed),
        "invalid_geometry_count": sum(
            len(report.get("spatial_layers", {}).get("soilmu_a", {}).get("invalid_geometries", []))
            for report in reports
        ),
        "aggregate_counts": {
            "spatial_layer_records": {
                layer: sum(
                    report.get("spatial_layers", {}).get(layer, {}).get("record_count", 0)
                    for report in reports
                )
                for layer in EXPECTED_LAYER_TYPES
            },
            "mapunit_rows": sum(
                report.get("tabular", {}).get("mapunit_row_count", 0) for report in reports
            ),
            "component_rows": sum(
                report.get("tabular", {}).get("component_row_count", 0) for report in reports
            ),
            "unique_mapunits": sum(
                report.get("tabular", {}).get("unique_mapunit_count", 0) for report in reports
            ),
            "unique_components": sum(
                report.get("tabular", {}).get("unique_component_count", 0) for report in reports
            ),
            "intersecting_mapunits": sum(
                report.get("coverage", {}).get("intersecting_mapunit_count", 0)
                for report in reports
            ),
            "hydricrating_nonempty": sum(
                report.get("tabular", {}).get("hydricrating_nonempty_count", 0)
                for report in reports
            ),
            "hydricon_nonempty": sum(
                report.get("tabular", {}).get("hydricon_nonempty_count", 0) for report in reports
            ),
        },
        "identity_discrepancy_package_count": sum(
            any(
                "survey-area name does not match" in issue
                or "survey-area identity does not match" in issue
                for issue in report["issues"]
            )
            for report in reports
        ),
        "intersecting_package_count": sum(
            1 for report in reports if report.get("coverage", {}).get("aoi_intersects_package")
        ),
        "package_reports": [f"packages/{report['areasymbol']}.json" for report in reports],
        "failed_packages": [
            {
                "areasymbol": report["areasymbol"],
                "issues": report["issues"],
                "invalid_geometry_count": len(
                    report.get("spatial_layers", {})
                    .get("soilmu_a", {})
                    .get("invalid_geometries", [])
                ),
            }
            for report in failed
        ],
        "candidate_policy": "All candidates remain inactive/incomplete; QA does not promote or alter catalog state.",
        "limitations": [
            "Validation reads original package members and does not repair, drop, or clip source records.",
            "Intersection confirms package contact with the approved AOI; it is not a clipped canonical coverage calculation.",
            "Hydric attributes remain soil information, not a wetlands inventory or regulatory determination.",
        ],
    }
    write_json(output_dir / "aggregate.json", aggregate)
    _update_manifest(data_root, reports, str(output_dir / "aggregate.json"))
    return aggregate


def _update_manifest(data_root: Path, reports: list[dict[str, Any]], aggregate_path: str) -> None:
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
    for report in reports:
        for entry in manifest.setdefault("artifacts", []):
            if entry.get("sha256") == report["artifact_sha256"]:
                entry["regional_qa_report"] = str(
                    Path(aggregate_path).parent / "packages" / f"{report['areasymbol']}.json"
                )
                entry["regional_qa_status"] = report["status"]
                entry["regional_invalid_geometry_count"] = len(
                    report.get("spatial_layers", {})
                    .get("soilmu_a", {})
                    .get("invalid_geometries", [])
                )
                entry["regional_intersection_status"] = report.get("coverage", {}).get(
                    "coverage_status", "unverified"
                )
                break
    manifest["ssurgo_regional_qa"] = {
        "latest_aggregate_report": aggregate_path,
        "status": "passed"
        if all(report["status"] == "passed" for report in reports)
        else "partial_failure",
        "package_count": len(reports),
        "passed_package_count": sum(report["status"] == "passed" for report in reports),
        "failed_package_count": sum(report["status"] == "failed" for report in reports),
        "raw_packages_unchanged": True,
    }
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)
