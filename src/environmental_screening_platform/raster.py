"""Snapshot-pinned raster screening helpers for bounded source fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from shapely.geometry import box, mapping
from shapely.ops import transform

from .adapters import NLCD_CLASSES
from .models import Coverage, Observation

NLCD_SOURCE_YEAR = 2025
ANALYSIS_CRS = "EPSG:5070"
MAX_CELLS = 16_000_000


def _json_number(value: Any) -> int | float | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _raster_footprint(dataset: rasterio.DatasetReader) -> Any:
    return box(*dataset.bounds)


def screen_nlcd_raster(
    artifact_path: Path,
    aoi_4326: Any,
    *,
    source_snapshot_id: str,
    source_version_id: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Read one exact NLCD artifact and summarize only the requested AOI.

    The caller has already verified the artifact checksum against the immutable
    SQLite snapshot. This function never resolves an active pointer or selects a
    newer artifact.
    """
    with rasterio.open(artifact_path) as dataset:
        if dataset.count != 1 or dataset.width * dataset.height > MAX_CELLS:
            raise ValueError("NLCD fixture must contain one band and at most 16 million cells")
        if dataset.crs is None:
            raise ValueError("NLCD fixture has no CRS metadata")

        to_raster = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform
        aoi_raster = transform(to_raster, aoi_4326)
        to_analysis = Transformer.from_crs(dataset.crs, ANALYSIS_CRS, always_xy=True).transform
        aoi_analysis = transform(
            Transformer.from_crs("EPSG:4326", ANALYSIS_CRS, always_xy=True).transform,
            aoi_4326,
        )
        footprint = _raster_footprint(dataset)
        footprint_aoi = aoi_raster.intersection(footprint)
        aoi_area_sqm = float(aoi_analysis.area)
        covered_area_sqm = float(transform(to_analysis, footprint_aoi).area)
        uncovered_area_sqm = max(aoi_area_sqm - covered_area_sqm, 0.0)

        values = dataset.read(1)
        inside = geometry_mask(
            [mapping(aoi_raster)],
            out_shape=values.shape,
            transform=dataset.transform,
            invert=True,
            all_touched=True,
        )
        nodata = dataset.nodata
        valid = inside & np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        nodata_mask = inside & ~valid
        valid_values = values[valid]
        classes, counts = np.unique(valid_values, return_counts=True)
        valid_count = int(valid_values.size)
        nodata_count = int(nodata_mask.sum())

        corners = [
            dataset.transform @ (0, 0),
            dataset.transform @ (1, 0),
            dataset.transform @ (1, 1),
            dataset.transform @ (0, 1),
        ]
        from shapely.geometry import Polygon

        cell_area_sqm = float(Polygon([to_analysis(x, y) for x, y in corners]).area)
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
                "estimated_area_sqm": round(float(count * cell_area_sqm), 3),
            }

        raster_metadata = {
            "source_year": NLCD_SOURCE_YEAR,
            "crs": dataset.crs.to_string(),
            "transform": [float(value) for value in list(dataset.transform)[:6]],
            "resolution": [abs(float(dataset.transform.a)), abs(float(dataset.transform.e))],
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "nodata": _json_number(nodata),
            "bounds": [float(value) for value in dataset.bounds],
            "cell_area_sqm": round(cell_area_sqm, 3),
        }
        coverage_fraction = covered_area_sqm / aoi_area_sqm if aoi_area_sqm else 0.0
        if covered_area_sqm <= 0:
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
            "source_status": "fixture_only",
            "screening_status": screening_status,
            "source_year": NLCD_SOURCE_YEAR,
            "raster_coverage_area_sqm": round(covered_area_sqm, 3),
            "covered_aoi_area_sqm": round(covered_area_sqm, 3),
            "uncovered_aoi_area_sqm": round(uncovered_area_sqm, 3),
            "covered_aoi_percentage": round(coverage_fraction * 100, 6),
            "aoi_cells_touched": int(inside.sum()),
            "valid_pixel_count": valid_count,
            "nodata_pixel_count": nodata_count,
            "valid_pixel_area_sqm": round(valid_count * cell_area_sqm, 3),
            "nodata_pixel_area_sqm": round(nodata_count * cell_area_sqm, 3),
            "classes": class_metrics,
            "raster": raster_metadata,
        },
    }
