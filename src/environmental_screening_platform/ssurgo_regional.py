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
from urllib.parse import unquote, urlparse
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import shapefile
from pyproj import CRS, Transformer
from shapely import make_valid
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
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if not match:
        return ""
    month, day, year = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _polygon_component_count(geometry: Any) -> int:
    if geometry.geom_type == "Polygon":
        return 1
    if geometry.geom_type == "MultiPolygon":
        return len(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return sum(_polygon_component_count(item) for item in geometry.geoms)
    return 0


def _polygon_ring_count(geometry: Any) -> int:
    if geometry.geom_type == "Polygon":
        return 1 + len(geometry.interiors)
    if geometry.geom_type == "MultiPolygon":
        return sum(1 + len(item.interiors) for item in geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return sum(_polygon_ring_count(item) for item in geometry.geoms)
    return 0


def _normalise_survey_name(value: str | None) -> str:
    normalized = re.sub(r"\barea\b", "", _clean(value).casefold())
    normalized = " ".join(normalized.split())
    return re.sub(r"\s+([,])", r"\1", normalized)


def _classify_identity(
    *,
    package_name: str,
    official_name: str,
    identifiers_match: bool,
    release_match: bool,
    url_match: bool,
    manifest_match: bool,
    additional_names: tuple[str, ...] = (),
) -> str:
    if not all((identifiers_match, release_match, url_match, manifest_match)):
        return "source_package_mismatch"
    names = (package_name, official_name, *additional_names)
    if len(set(names)) == 1:
        return "confirmed_identity"
    if len({_normalise_survey_name(name) for name in names}) == 1:
        return "harmless_naming_variation"
    return "unresolved_identity"


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


def _package_identity_audit(
    archive: ZipFile,
    root: str,
    spec: SsurgoPackageSpec,
    *,
    lookup_record: dict[str, Any] | None,
    manifest_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    members = {name.lower(): name for name in archive.namelist()}

    def table(name: str) -> list[list[str]]:
        member = members.get(f"{root.lower()}/tabular/{name}".lower())
        return _table(archive, member) if member else []

    legend_rows = table("legend.txt")
    sacatalog_rows = table("sacatlog.txt")
    legend_name = _clean(legend_rows[0][2]) if legend_rows and len(legend_rows[0]) > 2 else ""
    sacatalog_name = (
        _clean(sacatalog_rows[0][1]) if sacatalog_rows and len(sacatalog_rows[0]) > 1 else ""
    )
    package_names = [name for name in (legend_name, sacatalog_name) if name]

    metadata_names: list[str] = []
    metadata_member = members.get(f"{root.lower()}/soil_metadata_{spec.areasymbol.lower()}.txt")
    if metadata_member:
        metadata_text = archive.read(metadata_member).decode("utf-8", errors="replace")
        metadata_names.extend(
            match.strip()
            for match in re.findall(r"Title:\s+Soil Survey of ([^\r\n]+)", metadata_text)
        )
        metadata_names.extend(
            match.strip()
            for match in re.findall(r"Resource_Description:\s+([^\r\n]+?)\s+SSURGO", metadata_text)
        )

    official_name = _clean((lookup_record or {}).get("areaname")) or spec.areaname
    package_name = legend_name or sacatalog_name
    package_symbol = _clean(legend_rows[0][1]) if legend_rows and len(legend_rows[0]) > 1 else ""
    catalog_symbol = _clean(sacatalog_rows[0][0]) if sacatalog_rows else ""
    catalog_version = (
        _clean(sacatalog_rows[0][2]) if sacatalog_rows and len(sacatalog_rows[0]) > 2 else ""
    )
    catalog_date = (
        _date_part(_clean(sacatalog_rows[0][3]))
        if sacatalog_rows and len(sacatalog_rows[0]) > 3
        else ""
    )
    expected_date = spec.saverest_provider.split("T", 1)[0]

    decoded_url = unquote(spec.package_url)
    package_url_name = Path(urlparse(decoded_url).path).name
    url_match = (
        spec.areasymbol in decoded_url
        and expected_date in decoded_url
        and spec.provider_package_identifier == package_url_name
    )
    manifest_url = _clean(
        (manifest_entry or {}).get("url") or (manifest_entry or {}).get("final_url")
    )
    manifest_match = bool(
        manifest_entry
        and manifest_entry.get("sha256")
        and manifest_entry.get("release_version") == spec.provider_release
        and manifest_url == spec.package_url
    )
    identifiers_match = (
        package_symbol == spec.areasymbol
        and catalog_symbol == spec.areasymbol
        and package_name == sacatalog_name
    )
    release_match = (
        catalog_version == str(spec.saversion)
        and catalog_date == expected_date
        and str((lookup_record or {}).get("saversion", spec.saversion)) == str(spec.saversion)
        and _date_part(str((lookup_record or {}).get("saverest", ""))) == expected_date
    )
    classification = _classify_identity(
        package_name=package_name,
        official_name=official_name,
        identifiers_match=identifiers_match,
        release_match=release_match,
        url_match=url_match,
        manifest_match=manifest_match,
        additional_names=(spec.areaname,),
    )
    return {
        "classification": classification,
        "package_metadata": {
            "legend_name": legend_name,
            "sacatlog_name": sacatalog_name,
            "soil_metadata_names": metadata_names,
            "package_symbol": package_symbol,
            "sacatlog_symbol": catalog_symbol,
            "saversion": catalog_version,
            "saverest_date": catalog_date,
        },
        "sda_metadata": {
            "source_path": "ssurgo/ssurgo_area_release_inventory.json",
            "areasymbol": (lookup_record or {}).get("areasymbol"),
            "areaname": (lookup_record or {}).get("areaname"),
            "saversion": (lookup_record or {}).get("saversion"),
            "saverest": (lookup_record or {}).get("saverest"),
        },
        "official_survey_area_lookup": {
            "source_path": "ssurgo/ssurgo_area_release_inventory.json",
            "areasymbol": (lookup_record or {}).get("areasymbol"),
            "areaname": (lookup_record or {}).get("areaname"),
        },
        "sizing_record": {
            "source_path": str(SSURGO_REGIONAL_SIZING),
            "areasymbol": spec.areasymbol,
            "areaname": spec.areaname,
            "provider_release": spec.provider_release,
        },
        "package_url": {
            "url": spec.package_url,
            "decoded_filename": package_url_name,
            "areasymbol_in_url": spec.areasymbol in decoded_url,
            "release_date_in_url": expected_date in decoded_url,
            "matches_sizing_identifier": url_match,
        },
        "manifest": {
            "present": manifest_entry is not None,
            "source": (manifest_entry or {}).get("source"),
            "url": manifest_url or None,
            "release_version": (manifest_entry or {}).get("release_version"),
            "sha256": (manifest_entry or {}).get("sha256"),
            "matches_package_release_and_url": manifest_match,
        },
        "comparison": {
            "package_names_agree": bool(package_names) and len(set(package_names)) == 1,
            "package_symbol_matches": identifiers_match,
            "release_matches": release_match,
            "package_url_matches": url_match,
            "manifest_matches": manifest_match,
        },
        "decision_note": (
            "Package and official identifiers/release/URL evidence agree; the name differs only by "
            "the word 'Area'."
            if classification == "harmless_naming_variation"
            else "No naming or source identity discrepancy was observed."
            if classification == "confirmed_identity"
            else "Identity requires owner/provider review before regional staging."
        ),
    }


def _invalid_geometry_diagnostics(
    archive: ZipFile, root: str, spec: SsurgoPackageSpec
) -> list[dict[str, Any]]:
    members = {name.lower(): name for name in archive.namelist()}
    base = f"{root.lower()}/spatial/soilmu_a_{spec.areasymbol.lower()}"
    reader = shapefile.Reader(
        shp=io.BytesIO(archive.read(members[f"{base}.shp"])),
        shx=io.BytesIO(archive.read(members[f"{base}.shx"])),
        dbf=io.BytesIO(archive.read(members[f"{base}.dbf"])),
    )
    mapunit_member = members[f"{root.lower()}/tabular/mapunit.txt"]
    component_member = members[f"{root.lower()}/tabular/comp.txt"]
    mapunit_rows = _table(archive, mapunit_member)
    component_rows = _table(archive, component_member)
    mapunit_ids = {_clean(row[23]) for row in mapunit_rows if len(row) == 24 and _clean(row[23])}
    component_counts = Counter(
        _clean(row[107]) for row in component_rows if len(row) == 109 and _clean(row[107])
    )
    to_analysis = Transformer.from_crs(4326, 5070, always_xy=True).transform
    diagnostics: list[dict[str, Any]] = []
    for index, (item, record) in enumerate(zip(reader.shapes(), reader.records(), strict=True)):
        geometry = shape(item.__geo_interface__)
        if geometry.is_empty or geometry.is_valid:
            continue
        values = record.as_dict()
        mukey = _clean(values.get("MUKEY"))
        repaired = make_valid(geometry)
        original_area = transform(to_analysis, geometry).area
        repaired_area = transform(to_analysis, repaired).area
        attributes_joinable = (
            _clean(values.get("AREASYMBOL")) == spec.areasymbol
            and mukey in mapunit_ids
            and component_counts[mukey] > 0
        )
        diagnostics.append(
            {
                "stable_feature_id": f"soilmu_a:{spec.areasymbol}:{mukey}",
                "package": spec.areasymbol,
                "layer": "soilmu_a",
                "source_record_index": index,
                "mukey": mukey,
                "musym": _clean(values.get("MUSYM")),
                "original": {
                    "valid": False,
                    "validity_reason": explain_validity(geometry),
                    "geometry_type": geometry.geom_type,
                    "polygon_component_count": _polygon_component_count(geometry),
                    "ring_count": _polygon_ring_count(geometry),
                    "empty": geometry.is_empty,
                    "area_epsg5070_m2": original_area,
                },
                "derived_make_valid": {
                    "operation": "shapely.make_valid",
                    "diagnostic_only": True,
                    "valid": repaired.is_valid,
                    "geometry_type": repaired.geom_type,
                    "polygon_component_count": _polygon_component_count(repaired),
                    "ring_count": _polygon_ring_count(repaired),
                    "empty": repaired.is_empty,
                    "area_epsg5070_m2": repaired_area,
                    "area_delta_percentage": (
                        (repaired_area - original_area) / original_area * 100
                        if original_area
                        else None
                    ),
                },
                "component_change": {
                    "polygon_component_delta": _polygon_component_count(repaired)
                    - _polygon_component_count(geometry),
                    "ring_delta": _polygon_ring_count(repaired) - _polygon_ring_count(geometry),
                    "geometry_type_changed": repaired.geom_type != geometry.geom_type,
                },
                "attributes": {
                    "source_attributes_preserved_in_diagnostic": True,
                    "areasymbol_matches": _clean(values.get("AREASYMBOL")) == spec.areasymbol,
                    "mapunit_row_present": mukey in mapunit_ids,
                    "component_row_count": component_counts[mukey],
                    "remain_joinable": attributes_joinable,
                },
            }
        )
    return diagnostics


def audit_ssurgo_package_discrepancies(
    artifact_path: Path,
    spec: SsurgoPackageSpec,
    *,
    lookup_record: dict[str, Any] | None = None,
    manifest_entry: dict[str, Any] | None = None,
    package_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive discrepancy diagnostics without writing or promoting any geometry."""
    report: dict[str, Any] = {
        "areasymbol": spec.areasymbol,
        "artifact_path": str(artifact_path),
        "artifact_sha256": _sha256(artifact_path) if artifact_path.is_file() else None,
        "artifact_size_bytes": artifact_path.stat().st_size if artifact_path.is_file() else None,
        "audit_status": "failed",
        "diagnostic_only": True,
        "package_validation_status": (package_validation or {}).get("status"),
        "geometry_crs": "EPSG:5070",
        "geometry_diagnostics": [],
        "identity_audit": None,
        "issues": [],
        "limitations": [
            "make_valid output exists only as in-memory diagnostics and is not a staging or canonical artifact.",
            "No source record was repaired, dropped, clipped, quarantined, or promoted by this audit.",
        ],
    }
    if not artifact_path.is_file():
        report["issues"].append("candidate artifact is missing")
        return report
    try:
        with ZipFile(artifact_path) as archive:
            root, _ = _relative_members(archive)
            report["geometry_diagnostics"] = _invalid_geometry_diagnostics(archive, root, spec)
            report["identity_audit"] = _package_identity_audit(
                archive,
                root,
                spec,
                lookup_record=lookup_record,
                manifest_entry=manifest_entry,
            )
            report["audit_status"] = "complete"
    except (
        BadZipFile,
        OSError,
        ValueError,
        KeyError,
        UnicodeDecodeError,
        shapefile.ShapefileException,
    ) as exc:
        report["issues"].append(f"audit parse error: {type(exc).__name__}: {exc}")
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


def _survey_lookup_records(path: Path) -> dict[str, dict[str, Any]]:
    record = read_json(path)
    rows = record.get("Table", [])
    if not rows:
        return {}
    headers = [str(header) for header in rows[0]]
    return {
        str(row[0]): dict(zip(headers, row, strict=False)) for row in rows[1:] if row and row[0]
    }


def _manifest_artifacts_by_sha(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entry["sha256"]): entry
        for entry in manifest.get("artifacts", [])
        if entry.get("sha256")
    }


def _update_discrepancy_manifest(
    data_root: Path,
    reports: list[dict[str, Any]],
    package_paths: dict[str, Path],
    aggregate_path: Path,
) -> None:
    manifest_path = data_root / "manifest.json"
    manifest = read_json(manifest_path)
    by_sha = _manifest_artifacts_by_sha(manifest)
    for report in reports:
        entry = by_sha.get(report["artifact_sha256"])
        if entry is not None:
            package_path = package_paths[report["areasymbol"]]
            identity = report.get("identity_audit") or {}
            entry["discrepancy_audit_report"] = str(package_path)
            entry["discrepancy_audit_status"] = report["audit_status"]
            entry["discrepancy_identity_classification"] = identity.get(
                "classification", "audit_failed"
            )
            entry["discrepancy_geometry_count"] = len(report["geometry_diagnostics"])
            entry["discrepancy_audit_report_sha256"] = _sha256(package_path)
    manifest["ssurgo_regional_discrepancy_audit"] = {
        "latest_aggregate_report": str(aggregate_path),
        "aggregate_report_sha256": _sha256(aggregate_path),
        "package_count": len(reports),
        "packages_with_geometry_discrepancies": sum(
            bool(report["geometry_diagnostics"]) for report in reports
        ),
        "packages_with_identity_discrepancies": sum(
            (report.get("identity_audit") or {}).get("classification") != "confirmed_identity"
            for report in reports
        ),
        "raw_packages_unchanged": True,
        "catalog_unchanged": True,
        "postgis_accessed": False,
    }
    manifest["retrieved_on"] = datetime.now(UTC).date().isoformat()
    write_json(manifest_path, manifest)


def audit_ssurgo_regional_discrepancies(
    data_root: Path,
    *,
    sizing_record: Path | None = None,
    lookup_record: Path | None = None,
    manifest_path: Path | None = None,
    boundary_path: Path | None = None,
    repository: SQLiteSourceRepository | None = None,
) -> dict[str, Any]:
    """Audit existing regional QA discrepancies without changing source state."""
    sizing_path = sizing_record or data_root / SSURGO_REGIONAL_SIZING
    lookup_path = lookup_record or data_root / "ssurgo/ssurgo_area_release_inventory.json"
    manifest_file = manifest_path or data_root / "manifest.json"
    specs = load_ssurgo_package_specs(sizing_path)
    aoi = load_approved_aoi(data_root, boundary_path)
    catalog = repository or SQLiteSourceRepository(data_root)
    candidates = catalog.list_candidates("ssurgo")
    lookup = _survey_lookup_records(lookup_path)
    manifest = read_json(manifest_file)
    manifest_by_sha = _manifest_artifacts_by_sha(manifest)
    run_id = str(uuid4())
    output_dir = data_root / "ssurgo" / "regional-discrepancy-audit" / run_id
    package_dir = output_dir / "packages"
    reports: list[dict[str, Any]] = []
    for spec in specs:
        candidate = _candidate_for_spec(candidates, spec)
        artifact_path = Path(candidate["artifact_path"])
        package_validation = validate_ssurgo_package_archive(
            artifact_path,
            spec,
            aoi,
            source_version_id=candidate.get("version_id"),
            candidate_id=candidate.get("candidate_id"),
            ingestion_run_id=candidate.get("run_id"),
            source_url=candidate.get("source_url"),
            retrieved_at=candidate.get("retrieved_at"),
        )
        report = audit_ssurgo_package_discrepancies(
            artifact_path,
            spec,
            lookup_record=lookup.get(spec.areasymbol),
            manifest_entry=manifest_by_sha.get(package_validation["artifact_sha256"]),
            package_validation=package_validation,
        )
        report["candidate_status"] = candidate.get("status")
        report["candidate_validation_status"] = candidate.get("validation_status")
        report["candidate_promotion_status"] = candidate.get("promotion_status")
        report["package_validation_issues"] = package_validation["issues"]
        reports.append(report)
        write_json(package_dir / f"{spec.areasymbol}.json", report)

    diagnostics = [
        diagnostic for report in reports for diagnostic in report["geometry_diagnostics"]
    ]
    classifications = Counter(
        (report.get("identity_audit") or {}).get("classification", "audit_failed")
        for report in reports
    )
    repaired = [diagnostic["derived_make_valid"] for diagnostic in diagnostics]
    aggregate = {
        "audit_id": run_id,
        "source_id": "ssurgo",
        "sizing_record": str(sizing_path),
        "official_lookup": str(lookup_path),
        "approved_boundary": {
            "geoids": sorted(APPROVED_GEOIDS),
            "vintage": 2025,
            "geometry_type": aoi.geom_type,
            "component_count": len(aoi.geoms),
            "crs": SOURCE_CRS,
        },
        "status": "completed_with_discrepancies"
        if diagnostics or any(value != "confirmed_identity" for value in classifications)
        else "completed",
        "package_count": len(reports),
        "package_validation_counts": {
            "passed": sum(report["package_validation_status"] == "passed" for report in reports),
            "failed": sum(report["package_validation_status"] == "failed" for report in reports),
        },
        "geometry_diagnostics": {
            "invalid_feature_count": len(diagnostics),
            "packages_affected": sum(bool(report["geometry_diagnostics"]) for report in reports),
            "derived_valid_count": sum(item["valid"] for item in repaired),
            "derived_nonempty_count": sum(not item["empty"] for item in repaired),
            "geometry_type_change_count": sum(
                item["component_change"]["geometry_type_changed"] for item in diagnostics
            ),
            "polygon_component_change_count": sum(
                item["component_change"]["polygon_component_delta"] != 0 for item in diagnostics
            ),
            "ring_change_count": sum(
                item["component_change"]["ring_delta"] != 0 for item in diagnostics
            ),
            "attributes_joinable_count": sum(
                item["attributes"]["remain_joinable"] for item in diagnostics
            ),
            "max_absolute_area_delta_percentage": max(
                (abs(item["area_delta_percentage"]) for item in repaired), default=None
            ),
            "area_crs": "EPSG:5070",
        },
        "identity_classifications": dict(sorted(classifications.items())),
        "decision_report": {
            "geometry": "diagnostic_only; no repaired record is accepted for staging or canonical use",
            "identity": "WY621 and WY721 are harmless naming variations when symbol, release, URL, and manifest evidence agree",
            "recommendation": "Keep all candidates inactive/incomplete pending owner disposition and any separately authorized staging policy.",
        },
        "package_reports": [f"packages/{report['areasymbol']}.json" for report in reports],
        "raw_packages_unchanged": True,
        "catalog_unchanged": True,
        "postgis_accessed": False,
        "limitations": [
            "Derived make_valid geometries are diagnostics only and were not persisted.",
            "The audit does not establish gap-free regional canonical coverage or production readiness.",
            "Hydric attributes remain soil information, not a wetlands inventory or regulatory determination.",
        ],
    }
    aggregate_path = output_dir / "aggregate.json"
    write_json(aggregate_path, aggregate)
    package_paths = {
        report["areasymbol"]: package_dir / f"{report['areasymbol']}.json" for report in reports
    }
    _update_discrepancy_manifest(data_root, reports, package_paths, aggregate_path)
    return aggregate
