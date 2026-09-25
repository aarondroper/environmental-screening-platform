"""Read-only regional coverage and seam analysis for staged SSURGO data."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .catalog import SQLiteSourceRepository
from .regression_fixtures import NORTHERN_COLORADO_REGRESSION_FIXTURE
from .spatial import PostGISRepository
from .store import read_json, write_json

AREA_CRS = "EPSG:5070"
SOURCE_CRS = "EPSG:4326"
COVERAGE_ANALYSIS_VERSION = "ssurgo-regional-coverage-v1"
BOUNDARY_DISTANCE_TOLERANCE_M = 1.0


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _area(geometry: BaseGeometry) -> float:
    to_area = Transformer.from_crs(SOURCE_CRS, AREA_CRS, always_xy=True).transform
    return float(transform(to_area, geometry).area)


def _stable_numbers(value: Any, key: str | None = None) -> Any:
    """Normalize analytical floating-point noise before checksumming reports."""
    if isinstance(value, float):
        if key and "area" in key and abs(value) < 1e-3:
            return 0.0
        decimals = (
            10
            if key in {"covered_percentage", "uncovered_percentage"}
            else 4
            if key and "percentage" in key
            else 10
            if abs(value) < 1e-3
            else 1
            if key and "area" in key
            else 4
        )
        return round(value, decimals)
    if isinstance(value, dict):
        return {key: _stable_numbers(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_stable_numbers(item, key) for item in value]
    return value


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": sorted(features, key=lambda item: str(item["properties"].get("id", ""))),
    }


def _geometry_feature(
    identifier: str, geometry: BaseGeometry, properties: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": identifier,
        "properties": properties | {"id": identifier},
        "geometry": mapping(geometry),
    }


def analyze_coverage_geometries(
    aoi: BaseGeometry,
    package_features: Mapping[str, Iterable[BaseGeometry]],
) -> dict[str, Any]:
    """Compute deterministic coverage metrics for WGS84 test geometries.

    This helper mirrors the database analysis contract and is deliberately
    limited to measurement: unions are analytical intermediates and no input
    geometry is changed.
    """
    if aoi.is_empty or not aoi.is_valid or aoi.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("AOI must be a valid nonempty Polygon or MultiPolygon")
    aoi_area = _area(aoi)
    package_rows: list[dict[str, Any]] = []
    package_geometries: dict[str, BaseGeometry] = {}
    outside_feature_area = 0.0
    for package, geometries in sorted(package_features.items()):
        source_geometries = list(geometries)
        clipped = [
            geometry.intersection(aoi) for geometry in source_geometries if geometry.intersects(aoi)
        ]
        package_geometry = unary_union(clipped) if clipped else aoi.boundary.buffer(0)
        clipped_area = sum(_area(geometry) for geometry in clipped)
        source_area = sum(_area(geometry) for geometry in source_geometries)
        outside_area = source_area - clipped_area
        outside_feature_area += outside_area
        package_geometries[package] = package_geometry
        package_rows.append(
            {
                "package_areasymbol": package,
                "feature_count": len(source_geometries),
                "intersecting_feature_count": len(clipped),
                "coverage_area_sqm": _area(package_geometry),
                "sum_feature_intersection_area_sqm": clipped_area,
                "outside_feature_area_sqm": outside_area,
            }
        )
    covered_geometry = (
        unary_union(list(package_geometries.values()))
        if package_geometries
        else aoi.boundary.buffer(0)
    )
    covered_area = _area(covered_geometry)
    gap_geometry = aoi.difference(covered_geometry)
    overlaps: list[dict[str, Any]] = []
    packages = sorted(package_geometries)
    for index, package_a in enumerate(packages):
        for package_b in packages[index + 1 :]:
            overlap = package_geometries[package_a].intersection(package_geometries[package_b])
            overlap_area = _area(overlap)
            if overlap_area > 0:
                overlaps.append(
                    {"package_a": package_a, "package_b": package_b, "area_sqm": overlap_area}
                )
    for row in package_rows:
        row["coverage_percentage_of_aoi"] = row["coverage_area_sqm"] / aoi_area * 100
        row["coverage_contribution_percentage"] = (
            row["coverage_area_sqm"] / covered_area * 100 if covered_area else 0.0
        )
    return {
        "aoi_area_sqm": aoi_area,
        "covered_area_sqm": covered_area,
        "uncovered_area_sqm": max(aoi_area - covered_area, 0.0),
        "outside_aoi_feature_area_sqm": outside_feature_area,
        "overlap_area_sqm": sum(item["area_sqm"] for item in overlaps),
        "overlap_pair_count": len(overlaps),
        "packages": package_rows,
        "overlaps": overlaps,
        "gap_geometry": gap_geometry,
        "covered_geometry": covered_geometry,
    }


def _classify_gap_components(
    aoi_geometry: BaseGeometry, gap_geometry: BaseGeometry
) -> list[dict[str, Any]]:
    to_area = Transformer.from_crs(SOURCE_CRS, AREA_CRS, always_xy=True).transform
    boundary = transform(to_area, aoi_geometry).boundary
    parts = list(gap_geometry.geoms) if hasattr(gap_geometry, "geoms") else [gap_geometry]
    diagnostics = []
    for index, part in enumerate(parts, start=1):
        boundary_adjacent = (
            transform(to_area, part).distance(boundary) <= BOUNDARY_DISTANCE_TOLERANCE_M
        )
        diagnostics.append(
            _geometry_feature(
                f"gap-{index:04d}",
                part,
                {
                    "diagnostic_type": "gap",
                    "area_sqm": _area(part),
                    "boundary_adjacent": boundary_adjacent,
                    "classification": (
                        "aoi_boundary_residual" if boundary_adjacent else "interior_aoi_gap"
                    ),
                    "interpretation": (
                        "Boundary-adjacent residual; attributable to the source/AOI edge or package seam, not filled by this analysis."
                        if boundary_adjacent
                        else "Interior AOI gap in the unioned staged soil coverage; no source records were filled."
                    ),
                },
            )
        )
    return diagnostics


def _load_candidate_inputs(
    data_root: Path, candidate_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = SQLiteSourceRepository(data_root)
    candidate = catalog.get_candidate(candidate_id)
    if candidate is None:
        raise KeyError(f"Unknown candidate: {candidate_id}")
    if candidate["source_id"] != "ssurgo" or candidate["promotion_status"] != "not_promoted":
        raise ValueError("Coverage analysis requires an inactive SSURGO candidate")
    if candidate["status"] not in {"incomplete", "conditionally_validated"}:
        raise ValueError("Coverage analysis requires an incomplete candidate")
    lineage = candidate["validation"].get("lineage", {})
    package_reports = lineage.get("package_reports", [])
    expected_packages = NORTHERN_COLORADO_REGRESSION_FIXTURE.ssurgo_expected_package_count
    if len(package_reports) != expected_packages:
        raise ValueError(f"Candidate does not contain the expected {expected_packages}-package lineage")
    batch_ids = [str(item["batch_id"]) for item in package_reports]
    if len(batch_ids) != len(set(batch_ids)):
        raise ValueError("Candidate package lineage contains duplicate staging batches")
    return candidate, {"batch_ids": batch_ids, "lineage": lineage}


def _write_geojson(path: Path, feature_collection: dict[str, Any]) -> tuple[str, int]:
    write_json(path, feature_collection)
    return _sha256(path)


def analyze_ssurgo_regional_coverage(
    data_root: Path,
    *,
    candidate_id: str,
    database_url: str | None = None,
    repository: PostGISRepository | None = None,
) -> dict[str, Any]:
    """Analyze and persist read-only coverage evidence for one candidate."""
    data_root = data_root.resolve()
    candidate, inputs = _load_candidate_inputs(data_root, candidate_id)
    spatial = repository or PostGISRepository(database_url)
    result = spatial.analyze_ssurgo_regional_coverage(
        inputs["batch_ids"], NORTHERN_COLORADO_REGRESSION_FIXTURE.aoi_id, 1
    )
    aoi_geometry = shape(result["aoi"]["geometry"])
    gap_geometry = shape(result["gap_geometry"])
    gap_features = _classify_gap_components(aoi_geometry, gap_geometry)
    overlap_features = []
    seam_features = list(gap_features)
    for index, item in enumerate(result["overlaps"], start=1):
        feature = _geometry_feature(
            f"overlap-{index:04d}",
            shape(item["geometry"]),
            {
                "diagnostic_type": "overlap",
                "package_a": item["package_a"],
                "package_b": item["package_b"],
                "area_sqm": item["area_sqm"],
                "classification": "package_boundary_overlap",
                "interpretation": "Overlapping accepted package coverage; retained as a diagnostic and not deduplicated.",
            },
        )
        overlap_features.append(feature)
        seam_features.append(feature)

    output_dir = data_root / "ssurgo" / "regional-coverage" / candidate_id
    gap_path = output_dir / "gap-diagnostics.geojson"
    overlap_path = output_dir / "overlap-diagnostics.geojson"
    seam_path = output_dir / "seam-diagnostics.geojson"
    gap_sha, gap_size = _write_geojson(gap_path, _feature_collection(gap_features))
    overlap_sha, overlap_size = _write_geojson(overlap_path, _feature_collection(overlap_features))
    seam_sha, seam_size = _write_geojson(seam_path, _feature_collection(seam_features))

    coverage = result["coverage"]
    aoi_area = float(result["aoi"]["area_sqm"])
    covered_area = float(coverage["covered_area_sqm"])
    uncovered_area = max(float(coverage["uncovered_area_sqm"]), 0.0)
    package_reports: list[dict[str, Any]] = []
    for package in result["packages"]:
        item = dict(package)
        item.pop("coverage_geometry", None)
        item["coverage_percentage_of_aoi"] = package["coverage_area_sqm"] / aoi_area * 100
        item["coverage_contribution_percentage"] = (
            package["coverage_area_sqm"] / covered_area * 100 if covered_area else 0.0
        )
        item["coverage_status"] = "intersects"
        package_reports.append(item)
    package_reports.sort(key=lambda item: item["package_areasymbol"])
    package_paths: list[dict[str, Any]] = []
    for package in package_reports:
        path = output_dir / "packages" / f"{package['package_areasymbol']}.json"
        package = _stable_numbers(package)
        write_json(path, package)
        sha, size = _sha256(path)
        package_paths.append(
            {
                "package_areasymbol": package["package_areasymbol"],
                "path": str(path),
                "sha256": sha,
                "size_bytes": size,
            }
        )

    boundary_gap_count = sum(
        item["properties"]["classification"] == "aoi_boundary_residual" for item in gap_features
    )
    interior_gap_count = len(gap_features) - boundary_gap_count
    aggregate = {
        "schema_version": 1,
        "analysis_version": COVERAGE_ANALYSIS_VERSION,
        "source_id": "ssurgo",
        "candidate_id": candidate_id,
        "source_version_id": candidate["version_id"],
        "staging_run_id": candidate["validation"]["lineage"]["staging_run_id"],
        "synthetic_source_snapshot_id": candidate["validation"]["lineage"][
            "synthetic_source_snapshot_id"
        ],
        "aoi": {
            "aoi_id": result["aoi"]["aoi_id"],
            "aoi_revision": result["aoi"]["aoi_revision"],
            "crs": SOURCE_CRS,
            "analysis_crs": AREA_CRS,
            "area_sqm": aoi_area,
        },
        "coverage": {
            **coverage,
            "covered_percentage": covered_area / aoi_area * 100,
            "uncovered_percentage": uncovered_area / aoi_area * 100,
            "gap_geometry_component_count": len(gap_features),
            "boundary_adjacent_gap_count": boundary_gap_count,
            "interior_gap_count": interior_gap_count,
            "seam_overlap_count": len(overlap_features),
        },
        "interpretation": {
            "coverage_status": "partial" if uncovered_area > 0 else "complete",
            "gap_interpretation": (
                "All detected gaps are boundary-adjacent residuals; no interior AOI gap was detected."
                if interior_gap_count == 0
                else "Interior AOI gaps remain in the unioned staged coverage and are unknown, not absence."
            ),
            "outside_aoi_interpretation": "Outside-AOI feature area is reported for package records and does not contribute to AOI coverage.",
            "overlap_interpretation": "Package overlaps are diagnostics; no records were deduplicated or removed.",
            "screening_limitation": "Uncovered or seam-affected soil area remains unknown and must not be treated as absence of a constraint.",
        },
        "package_reports": package_paths,
        "diagnostics": {
            "gap": {"path": str(gap_path), "sha256": gap_sha, "size_bytes": gap_size},
            "overlap": {
                "path": str(overlap_path),
                "sha256": overlap_sha,
                "size_bytes": overlap_size,
            },
            "seam": {"path": str(seam_path), "sha256": seam_sha, "size_bytes": seam_size},
        },
        "source_data_unchanged": True,
        "staging_data_unchanged": True,
        "promotion_status": "not_promoted",
    }
    aggregate = _stable_numbers(aggregate)
    aggregate_path = output_dir / "aggregate.json"
    write_json(aggregate_path, aggregate)
    aggregate_sha, aggregate_size = _sha256(aggregate_path)
    validation = {
        "analysis_version": COVERAGE_ANALYSIS_VERSION,
        "aggregate_report": str(aggregate_path),
        "aggregate_report_sha256": aggregate_sha,
        "aggregate_report_size_bytes": aggregate_size,
        "coverage": aggregate["coverage"],
        "package_report_count": len(package_paths),
        "diagnostics": aggregate["diagnostics"],
        "candidate_state_preserved": {
            "status": candidate["status"],
            "validation_status": candidate["validation_status"],
            "promotion_status": candidate["promotion_status"],
        },
    }
    updated = SQLiteSourceRepository(data_root).record_coverage_validation(
        candidate_id,
        coverage_status=aggregate["interpretation"]["coverage_status"],
        observation_status="incomplete_source" if uncovered_area > 0 else "data_observed",
        validation=validation,
    )
    manifest_path = data_root / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["ssurgo_regional_coverage"] = {
        "candidate_id": candidate_id,
        "source_version_id": candidate["version_id"],
        "latest_aggregate_report": str(aggregate_path),
        "aggregate_report_sha256": aggregate_sha,
        "aggregate_report_size_bytes": aggregate_size,
        "package_reports": package_paths,
        "diagnostics": aggregate["diagnostics"],
        "coverage_status": aggregate["interpretation"]["coverage_status"],
        "candidate_promotion_status": updated["promotion_status"],
        "active_source_version_created": False,
        "source_data_unchanged": True,
        "staging_data_unchanged": True,
    }
    write_json(manifest_path, manifest)
    return {
        "candidate": updated,
        "aggregate": aggregate,
        "aggregate_report_path": str(aggregate_path),
        "aggregate_report_sha256": aggregate_sha,
        "idempotent": bool(candidate["validation"].get("regional_coverage_validation")),
    }
