"""Build a small, provenance-bearing browser derivative for 3DEP."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.windows import Window
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

THREE_DEP_PREVIEW_SCHEMA = 1
THREE_DEP_SOURCE_CRS = "EPSG:4269"
THREE_DEP_NODATA = -999999.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_png(path: Path, rgba: np.ndarray, transform_: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".png", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
        with rasterio.open(
            temporary,
            "w",
            driver="PNG",
            width=rgba.shape[2],
            height=rgba.shape[1],
            count=4,
            dtype="uint8",
            transform=transform_,
        ) as output:
            output.write(rgba)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
        if temporary:
            auxiliary = Path(f"{temporary}.aux.xml")
            if auxiliary.exists():
                auxiliary.unlink()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _numbers(values: Any) -> list[float]:
    return [float(value) for value in values]


def _window_for_bounds(dataset: rasterio.DatasetReader, bounds: tuple[float, ...]) -> Window:
    left, bottom, right, top = bounds
    raw = rasterio.windows.from_bounds(left, bottom, right, top, dataset.transform)
    col_start = max(0, math.floor(raw.col_off))
    row_start = max(0, math.floor(raw.row_off))
    col_stop = min(dataset.width, math.ceil(raw.col_off + raw.width))
    row_stop = min(dataset.height, math.ceil(raw.row_off + raw.height))
    if col_stop <= col_start or row_stop <= row_start:
        raise ValueError("3DEP preview AOI does not intersect the source raster")
    return Window(col_start, row_start, col_stop - col_start, row_stop - row_start)


def _hillshade(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Return a relative illumination value without elevation interpretation."""
    if not np.any(valid):
        return np.zeros(values.shape, dtype="float32")
    # The fill is used only to keep gradients around nodata finite. Filled cells
    # are transparent in the published derivative and are never source values.
    fill_value = float(np.median(values[valid]))
    working = np.where(valid, values, fill_value).astype("float32", copy=False)
    dy, dx = np.gradient(working)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    azimuth = math.radians(315.0)
    altitude = math.radians(45.0)
    illumination = np.sin(altitude) * np.sin(slope) + np.cos(altitude) * np.cos(slope) * np.cos(
        azimuth - aspect
    )
    return np.clip((illumination + 1.0) / 2.0, 0.0, 1.0).astype("float32")


def _hillshade_rgba(shade: np.ndarray, visible: np.ndarray) -> np.ndarray:
    # Muted green-gray ramp: this is illumination, not an elevation class ramp.
    dark = np.array([38, 57, 54], dtype="float32")
    middle = np.array([130, 151, 139], dtype="float32")
    light = np.array([235, 235, 218], dtype="float32")
    rgb = np.empty((*shade.shape, 3), dtype="float32")
    lower = shade <= 0.5
    upper = ~lower
    rgb[lower] = dark + (middle - dark) * (shade[lower, None] * 2.0)
    rgb[upper] = middle + (light - middle) * ((shade[upper, None] - 0.5) * 2.0)
    rgba = np.zeros((4, *shade.shape), dtype="uint8")
    rgba[:3] = np.clip(rgb, 0, 255).astype("uint8").transpose(2, 0, 1)
    rgba[3, visible] = 255
    return rgba


def generate_3dep_preview(
    source_raster: Path,
    preview_png: Path,
    metadata_json: Path,
    *,
    aoi_geometry: Mapping[str, Any],
    aoi_revision: int,
    aoi_geometry_sha256: str,
    source_metadata: Mapping[str, Any],
    generated_at: str | None = None,
    padding_degrees: float = 0.001,
) -> dict[str, Any]:
    """Generate an AOI-windowed relative hillshade and exact display metadata."""
    if not source_raster.is_file():
        raise FileNotFoundError(source_raster)
    observed_source_sha256 = _sha256(source_raster)
    expected_sha256 = source_metadata.get("sha256")
    if expected_sha256 and observed_source_sha256 != expected_sha256:
        raise ValueError(
            "3DEP source checksum mismatch: "
            f"expected {expected_sha256}, observed {observed_source_sha256}"
        )
    if padding_degrees < 0 or not math.isfinite(padding_degrees):
        raise ValueError("3DEP preview padding must be a finite non-negative value")

    aoi = shape(aoi_geometry)
    if aoi.geom_type not in {"Polygon", "MultiPolygon"} or aoi.is_empty or not aoi.is_valid:
        raise ValueError("3DEP preview AOI must be a valid non-empty Polygon or MultiPolygon")

    with rasterio.open(source_raster) as dataset:
        if dataset.count != 1:
            raise ValueError("3DEP preview source must contain exactly one band")
        source_crs = dataset.crs.to_string() if dataset.crs else None
        if source_crs != THREE_DEP_SOURCE_CRS:
            raise ValueError(f"3DEP preview source must use {THREE_DEP_SOURCE_CRS}")
        if dataset.dtypes[0] != "float32":
            raise ValueError("3DEP preview source must use float32 elevation cells")
        if dataset.nodata is None or not math.isclose(float(dataset.nodata), THREE_DEP_NODATA):
            raise ValueError(f"3DEP preview source must use nodata {THREE_DEP_NODATA}")

        to_source = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform
        aoi_source = transform(to_source, aoi)
        minx, miny, maxx, maxy = aoi_source.bounds
        padded_bounds = (
            minx - padding_degrees,
            miny - padding_degrees,
            maxx + padding_degrees,
            maxy + padding_degrees,
        )
        window = _window_for_bounds(dataset, padded_bounds)
        values = dataset.read(1, window=window)
        window_transform = dataset.window_transform(window)
        inside_aoi = geometry_mask(
            [mapping(aoi_source)],
            out_shape=values.shape,
            transform=window_transform,
            invert=True,
            all_touched=True,
        )
        nodata = values == float(dataset.nodata)
        valid = np.isfinite(values) & ~nodata
        visible = inside_aoi & valid
        shade = _hillshade(values, valid)
        _atomic_png(preview_png, _hillshade_rgba(shade, visible), window_transform)

        to_wgs84 = Transformer.from_crs(dataset.crs, "EPSG:4326", always_xy=True).transform
        preview_bounds_source = rasterio.windows.bounds(window, dataset.transform)
        overlay_bounds_wgs84 = transform(to_wgs84, box(*preview_bounds_source)).bounds
        source_bounds = _numbers(dataset.bounds)
        source_transform = _numbers(tuple(dataset.transform)[:6])
        source_resolution = [abs(float(dataset.transform.a)), abs(float(dataset.transform.e))]
        raster_metadata = {
            "crs": source_crs,
            "bounds": source_bounds,
            "transform": source_transform,
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "nodata": float(dataset.nodata),
            "resolution": source_resolution,
            "resolution_arc_seconds": [value * 3600.0 for value in source_resolution],
        }
        preview_raster_metadata = {
            "bounds_source_crs": _numbers(preview_bounds_source),
            "bounds_wgs84": _numbers(overlay_bounds_wgs84),
            "transform": _numbers(tuple(window_transform)[:6]),
            "width": int(window.width),
            "height": int(window.height),
            "dtype": "uint8 RGBA",
            "nodata": "alpha=0",
            "resampling": "none; native source cells retained in the AOI window",
        }
        raster_tags = {**dataset.tags(), **dataset.tags(1)}
        vertical_declared = any(
            key.lower() in {"vertical_units", "vertical_datum", "verticaldatum", "vertunits"}
            for key in raster_tags
        )

    source = dict(source_metadata)
    source.update(
        {
            "sha256": observed_source_sha256,
            "byte_size": source_raster.stat().st_size,
            "raster": raster_metadata,
            "vertical_metadata_declared_in_raster": vertical_declared,
        }
    )
    preview = {
        "schema_version": THREE_DEP_PREVIEW_SCHEMA,
        "status": "available",
        "display_derivative": True,
        "source_id": "3dep",
        "source": source,
        "aoi": {
            "revision": aoi_revision,
            "geometry_sha256": aoi_geometry_sha256,
            "geometry_type": aoi.geom_type,
            "bounds_wgs84": _numbers(aoi.bounds),
        },
        "raster": raster_metadata,
        "preview_raster": preview_raster_metadata,
        "alignment": {
            "aoi_crs": "EPSG:4326",
            "source_crs": source_crs,
            "aoi_geometry_sha256": aoi_geometry_sha256,
            "aoi_revision": aoi_revision,
            "aoi_valid_cell_count": int(visible.sum()),
            "aoi_nodata_cell_count": int((inside_aoi & nodata).sum()),
            "preview_valid_cell_count": int(valid.sum()),
            "outside_aoi_pixels_transparent": True,
            "source_nodata_transparent": True,
            "overlay_bounds_wgs84": _numbers(overlay_bounds_wgs84),
        },
        "vertical_metadata": {
            "declared_in_source_raster": vertical_declared,
            "units": None,
            "datum": None,
            "warning": (
                "The retained source GeoTIFF does not declare vertical units or datum "
                "in its raster metadata; this display derivative shows relative "
                "illumination only and performs no elevation conversion."
            ),
        },
        "display": {
            "asset_path": preview_png.name,
            "metadata_path": metadata_json.name,
            "format": "RGBA PNG",
            "representation": "relative terrain hillshade",
            "transformation": (
                "The retained source cells were windowed around the recorded AOI and "
                "rendered as a muted relative hillshade. No reprojection, resampling, "
                "vertical-unit conversion, or datum conversion was performed. "
                "Outside-AOI and nodata cells have alpha 0."
            ),
            "hillshade": {
                "azimuth_degrees": 315.0,
                "sun_elevation_degrees": 45.0,
                "nodata_gradient_fill": "valid-cell median for derivative only",
            },
            "opacity_default": 0.42,
            "default_visible": False,
            "asset_sha256": _sha256(preview_png),
            "asset_byte_size": preview_png.stat().st_size,
        },
        "legend": [
            {"label": "shaded relative relief", "color": "#263936"},
            {"label": "intermediate illumination", "color": "#82978b"},
            {"label": "illuminated relative relief", "color": "#ebebda"},
        ],
    }
    if generated_at is not None:
        preview["generated_at"] = generated_at
    _atomic_json(metadata_json, preview)
    return preview
