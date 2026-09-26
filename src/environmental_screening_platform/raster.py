"""Snapshot-pinned raster screening helpers for bounded source artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform

from .adapters import NLCD_CLASSES
from .models import Coverage, Observation
from .regression_fixtures import NORTHERN_COLORADO_REGRESSION_FIXTURE

NLCD_SOURCE_YEAR = 2025
ANALYSIS_CRS = "EPSG:5070"
MAX_CELLS = NORTHERN_COLORADO_REGRESSION_FIXTURE.dep.max_cells


@dataclass(frozen=True)
class _RasterWindow:
    values: np.ndarray
    inside: np.ndarray
    valid: np.ndarray
    nodata: int | float | None
    aoi_area_sqm: float
    covered_area_sqm: float
    coverage_fraction: float
    cell_area_sqm: float
    metadata: dict[str, Any]
    dataset_tags: dict[str, str]
    band_tags: dict[str, str]
    footprint_geojson: dict[str, Any]


def _json_number(value: Any) -> int | float | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _raster_footprint(dataset: rasterio.DatasetReader) -> Any:
    return box(*dataset.bounds)


def _read_raster_window(
    artifact_path: Path,
    aoi_4326: Any,
    *,
    max_cells: int,
) -> _RasterWindow:
    """Read one single-band raster and derive shared AOI/grid accounting."""
    with rasterio.open(artifact_path) as dataset:
        if dataset.count != 1:
            raise ValueError("Raster must contain exactly one band")
        if dataset.crs is None:
            raise ValueError("Raster has no CRS metadata")
        to_raster = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform
        aoi_raster = transform(to_raster, aoi_4326)
        to_analysis = Transformer.from_crs(dataset.crs, ANALYSIS_CRS, always_xy=True).transform
        aoi_analysis = transform(
            Transformer.from_crs("EPSG:4326", ANALYSIS_CRS, always_xy=True).transform,
            aoi_4326,
        )
        footprint_aoi = aoi_raster.intersection(_raster_footprint(dataset))
        aoi_area_sqm = float(aoi_analysis.area)
        covered_area_sqm = float(transform(to_analysis, footprint_aoi).area)
        coverage_fraction = covered_area_sqm / aoi_area_sqm if aoi_area_sqm else 0.0
        if footprint_aoi.is_empty:
            read_window = Window(0, 0, 1, 1)
        elif dataset.width * dataset.height <= max_cells:
            read_window = Window(0, 0, dataset.width, dataset.height)
        else:
            read_window = (
                from_bounds(
                    *footprint_aoi.bounds,
                    transform=dataset.transform,
                )
                .round_offsets()
                .round_lengths()
            )
            read_window = read_window.intersection(Window(0, 0, dataset.width, dataset.height))
        if read_window.width * read_window.height > max_cells:
            raise ValueError(f"AOI raster window exceeds the {max_cells}-cell screening limit")
        values = dataset.read(1, window=read_window)
        read_transform = dataset.window_transform(read_window)
        inside = geometry_mask(
            [mapping(aoi_raster)],
            out_shape=values.shape,
            transform=read_transform,
            invert=True,
            all_touched=True,
        )
        nodata = dataset.nodata
        valid = inside & np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        corners = [
            read_transform @ (0, 0),
            read_transform @ (1, 0),
            read_transform @ (1, 1),
            read_transform @ (0, 1),
        ]
        cell_area_sqm = float(Polygon([to_analysis(x, y) for x, y in corners]).area)
        metadata = {
            "crs": dataset.crs.to_string(),
            "transform": [float(value) for value in list(dataset.transform)[:6]],
            "resolution": [abs(float(dataset.transform.a)), abs(float(dataset.transform.e))],
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "nodata": _json_number(nodata),
            "bounds": [float(value) for value in dataset.bounds],
            "cell_area_sqm": round(cell_area_sqm, 3),
            "read_window": [
                float(read_window.col_off),
                float(read_window.row_off),
                float(read_window.width),
                float(read_window.height),
            ],
        }
        footprint_wgs84 = transform(
            Transformer.from_crs(dataset.crs, "EPSG:4326", always_xy=True).transform,
            _raster_footprint(dataset),
        )
        return _RasterWindow(
            values=values,
            inside=inside,
            valid=valid,
            nodata=_json_number(nodata),
            aoi_area_sqm=aoi_area_sqm,
            covered_area_sqm=covered_area_sqm,
            coverage_fraction=coverage_fraction,
            cell_area_sqm=cell_area_sqm,
            metadata=metadata,
            dataset_tags=dict(dataset.tags()),
            band_tags=dict(dataset.tags(1)),
            footprint_geojson=mapping(footprint_wgs84),
        )


def screen_nlcd_raster(
    artifact_path: Path,
    aoi_4326: Any,
    *,
    source_snapshot_id: str,
    source_version_id: str,
    provenance: dict[str, Any],
    source_status: str = "fixture_only",
) -> dict[str, Any]:
    """Read one exact NLCD artifact and summarize only the requested AOI.

    The caller has already verified the artifact checksum against the immutable
    SQLite snapshot. This function never resolves an active pointer or selects a
    newer artifact.
    """
    window = _read_raster_window(artifact_path, aoi_4326, max_cells=MAX_CELLS)
    nodata_mask = window.inside & ~window.valid
    valid_values = window.values[window.valid]
    classes, counts = np.unique(valid_values, return_counts=True)
    valid_count = int(valid_values.size)
    nodata_count = int(nodata_mask.sum())
    class_metrics: dict[str, dict[str, Any]] = {}
    for code, count in zip(classes, counts, strict=True):
        numeric_code = int(code) if float(code).is_integer() else str(code)
        key = str(numeric_code)
        class_metrics[key] = {
            "class_value": numeric_code,
            "class_name": NLCD_CLASSES.get(int(code), "unrecognized_or_other"),
            "pixel_count": int(count),
            "percentage_of_valid_pixels": round(float(count / valid_count * 100), 6)
            if valid_count
            else 0.0,
            "estimated_area_sqm": round(float(count * window.cell_area_sqm), 3),
        }
    raster_metadata = {"source_year": NLCD_SOURCE_YEAR, **window.metadata}
    coverage_fraction = window.coverage_fraction
    if window.covered_area_sqm <= 0:
        screening_status = "uncovered"
        observation_status = Observation.NOT_COVERED
    elif nodata_count:
        screening_status = "nodata"
        observation_status = Observation.NODATA
    else:
        screening_status = "observed"
        observation_status = Observation.DATA_OBSERVED

    result_provenance = dict(provenance)
    result_provenance.update(
        {
            "source_snapshot_id": source_snapshot_id,
            "source_version_id": source_version_id,
            "raster": raster_metadata,
            "selection": "exact immutable source snapshot artifact; no latest-version lookup",
        }
    )
    return {
        "status": "available",
        "screening_status": screening_status,
        "coverage_status": Coverage.COMPLETE.value
        if coverage_fraction >= 0.999999
        else Coverage.PARTIAL.value,
        "observation_status": observation_status.value,
        "provenance": result_provenance,
        "metrics": {
            "source_status": source_status,
            "screening_status": screening_status,
            "source_year": NLCD_SOURCE_YEAR,
            "raster_coverage_area_sqm": round(window.covered_area_sqm, 3),
            "covered_aoi_area_sqm": round(window.covered_area_sqm, 3),
            "uncovered_aoi_area_sqm": round(
                max(window.aoi_area_sqm - window.covered_area_sqm, 0.0), 3
            ),
            "covered_aoi_percentage": round(coverage_fraction * 100, 6),
            "aoi_cells_touched": int(window.inside.sum()),
            "valid_pixel_count": valid_count,
            "nodata_pixel_count": nodata_count,
            "valid_pixel_area_sqm": round(valid_count * window.cell_area_sqm, 3),
            "nodata_pixel_area_sqm": round(nodata_count * window.cell_area_sqm, 3),
            "classes": class_metrics,
            "raster": raster_metadata,
        },
    }


def _metadata_value(tags: dict[str, str], *names: str) -> str | None:
    lowered = {key.lower(): value for key, value in tags.items()}
    for name in names:
        if lowered.get(name.lower()):
            return lowered[name.lower()]
    return None


def screen_3dep_raster(
    artifact_path: Path,
    aoi_4326: Any,
    *,
    source_snapshot_id: str,
    source_version_id: str,
    provenance: dict[str, Any],
    source_status: str = "fixture_only",
) -> dict[str, Any]:
    """Summarize raw elevation values from one exact 3DEP snapshot artifact."""
    window = _read_raster_window(artifact_path, aoi_4326, max_cells=12_000_000)
    nodata_mask = window.inside & ~window.valid
    valid_values = window.values[window.valid].astype("float64")
    nodata_count = int(nodata_mask.sum())
    units = _metadata_value(
        window.band_tags | window.dataset_tags,
        "units",
        "unit",
        "vertical_units",
    )
    vertical_datum = _metadata_value(
        window.band_tags | window.dataset_tags,
        "vertical_datum",
        "verticaldatum",
        "datum",
    )
    if window.covered_area_sqm <= 0:
        screening_status = "uncovered"
        observation_status = Observation.NOT_COVERED
        statistics: dict[str, Any] = {}
    elif nodata_count or not valid_values.size:
        screening_status = "nodata"
        observation_status = Observation.NODATA
        statistics = {}
        if valid_values.size:
            statistics = _elevation_statistics(valid_values)
    else:
        screening_status = "observed"
        observation_status = Observation.DATA_OBSERVED
        statistics = _elevation_statistics(valid_values)
    raster_metadata = {
        **window.metadata,
        "source_year": None,
        "units": units,
        "vertical_datum": vertical_datum,
        "dataset_tags": window.dataset_tags,
        "band_tags": window.band_tags,
    }
    result_provenance = dict(provenance)
    result_provenance.update(
        {
            "source_snapshot_id": source_snapshot_id,
            "source_version_id": source_version_id,
            "raster": raster_metadata,
            "selection": "exact immutable source snapshot artifact; no latest-version lookup",
        }
    )
    return {
        "status": "available",
        "screening_status": screening_status,
        "coverage_status": Coverage.COMPLETE.value
        if window.coverage_fraction >= 0.999999
        else Coverage.PARTIAL.value,
        "observation_status": observation_status.value,
        "provenance": result_provenance,
        "features": [
            {
                "type": "Feature",
                "geometry": window.footprint_geojson,
                "properties": {
                    "spatial_representation": "raster_footprint",
                    "source_snapshot_id": source_snapshot_id,
                    "source_version_id": source_version_id,
                    "source_status": source_status,
                    "crs": raster_metadata["crs"],
                    "resolution": raster_metadata["resolution"],
                    "nodata": raster_metadata["nodata"],
                    "vertical_datum": vertical_datum,
                    "elevation_units": units,
                    "intersects_aoi": window.covered_area_sqm > 0,
                },
            }
        ]
        if window.covered_area_sqm > 0
        else [],
        "metrics": {
            "source_status": source_status,
            "screening_status": screening_status,
            "source_year": None,
            "raster_coverage_area_sqm": round(window.covered_area_sqm, 3),
            "covered_aoi_area_sqm": round(window.covered_area_sqm, 3),
            "uncovered_aoi_area_sqm": round(
                max(window.aoi_area_sqm - window.covered_area_sqm, 0.0), 3
            ),
            "covered_aoi_percentage": round(window.coverage_fraction * 100, 6),
            "valid_cell_count": int(valid_values.size),
            "nodata_cell_count": nodata_count,
            "minimum_elevation": statistics.get("min"),
            "maximum_elevation": statistics.get("max"),
            "mean_elevation": statistics.get("mean"),
            "elevation_percentiles": {
                key: value for key, value in statistics.items() if key in {"p25", "median", "p75"}
            },
            "elevation_units": units,
            "vertical_datum": vertical_datum,
            "raster": raster_metadata,
        },
    }


def _elevation_statistics(values: np.ndarray) -> dict[str, float]:
    if not values.size:
        return {}
    quantiles = np.quantile(values, [0, 0.25, 0.5, 0.75, 1], method="linear")
    return {
        "min": float(quantiles[0]),
        "p25": float(quantiles[1]),
        "median": float(quantiles[2]),
        "p75": float(quantiles[3]),
        "max": float(quantiles[4]),
        "mean": float(values.mean()),
    }
