"""Build a small, provenance-bearing browser derivative for Annual NLCD."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import calculate_default_transform, reproject
from shapely.geometry import mapping, shape
from shapely.ops import transform

from .adapters import NLCD_CLASSES

NLCD_PREVIEW_SCHEMA = 2
NLCD_NODATA = 250
NLCD_SOURCE_CRS = "EPSG:5070"
NLCD_DISPLAY_CRS = "EPSG:4326"

# These are the documented NLCD categorical colors. The preview only emits
# entries observed inside the recorded AOI, but keeping the full local domain
# makes the display transformation explicit and prevents class relabeling.
NLCD_DISPLAY_PALETTE: dict[int, tuple[int, int, int]] = {
    11: (70, 107, 159),
    12: (209, 222, 248),
    21: (222, 197, 197),
    22: (217, 146, 130),
    23: (235, 0, 0),
    24: (171, 0, 0),
    31: (179, 172, 159),
    41: (104, 171, 95),
    42: (28, 95, 44),
    43: (181, 197, 143),
    52: (204, 184, 121),
    71: (223, 223, 194),
    72: (217, 217, 57),
    73: (171, 108, 40),
    74: (184, 217, 235),
    81: (219, 216, 142),
    82: (201, 204, 101),
    90: (186, 224, 230),
    95: (123, 204, 196),
}


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


def generate_nlcd_preview(
    source_raster: Path,
    preview_png: Path,
    metadata_json: Path,
    *,
    aoi_geometry: Mapping[str, Any],
    aoi_revision: int,
    aoi_geometry_sha256: str,
    source_metadata: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Generate an AOI-masked RGBA PNG and its exact source/display metadata.

    The source raster remains authoritative. This function only converts the
    source categorical values to display colors, with pixels outside the AOI
    and source nodata written as alpha zero. The native source grid remains
    authoritative and is recorded separately. The browser derivative is
    reprojected with nearest-neighbor categorical resampling to a north-up,
    axis-aligned WGS84 grid before it is written, so Leaflet's image bounds and
    pixel rows/columns use the same coordinate system.
    """
    if not source_raster.is_file():
        raise FileNotFoundError(source_raster)
    observed_source_sha256 = _sha256(source_raster)
    expected_sha256 = source_metadata.get("sha256")
    if expected_sha256 and observed_source_sha256 != expected_sha256:
        raise ValueError(
            "NLCD source checksum mismatch: "
            f"expected {expected_sha256}, observed {observed_source_sha256}"
        )

    aoi = shape(aoi_geometry)
    if aoi.geom_type not in {"Polygon", "MultiPolygon"} or aoi.is_empty or not aoi.is_valid:
        raise ValueError("NLCD preview AOI must be a valid non-empty Polygon or MultiPolygon")

    with rasterio.open(source_raster) as dataset:
        if dataset.count != 1:
            raise ValueError("NLCD preview source must contain exactly one band")
        if dataset.crs is None or dataset.crs.to_string() != NLCD_SOURCE_CRS:
            raise ValueError(f"NLCD preview source must use {NLCD_SOURCE_CRS}")
        if dataset.dtypes[0] != "uint8":
            raise ValueError("NLCD preview source must use uint8 categorical pixels")
        if dataset.nodata != NLCD_NODATA:
            raise ValueError(f"NLCD preview source must use nodata {NLCD_NODATA}")

        to_source = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform
        aoi_source = transform(to_source, aoi)
        values = dataset.read(1)
        inside = geometry_mask(
            [mapping(aoi_source)],
            out_shape=values.shape,
            transform=dataset.transform,
            invert=True,
            all_touched=True,
        )
        nodata = values == NLCD_NODATA
        observed_values = np.unique(values[inside & ~nodata])
        unknown_values = [int(value) for value in observed_values if int(value) not in NLCD_CLASSES]
        if unknown_values:
            raise ValueError(f"NLCD preview found unsupported class values: {unknown_values}")

        source_bounds = _numbers(dataset.bounds)
        source_transform = _numbers(tuple(dataset.transform)[:6])
        source_resolution = [abs(float(dataset.transform.a)), abs(float(dataset.transform.e))]
        native_raster_metadata = {
            "crs": dataset.crs.to_string(),
            "bounds": source_bounds,
            "transform": source_transform,
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "nodata": int(dataset.nodata),
            "resolution": source_resolution,
        }

        display_transform, display_width, display_height = calculate_default_transform(
            dataset.crs,
            NLCD_DISPLAY_CRS,
            dataset.width,
            dataset.height,
            *dataset.bounds,
        )
        if display_transform.b != 0 or display_transform.d != 0:
            raise ValueError("NLCD display transform must be north-up and axis-aligned")
        display_values = np.full((display_height, display_width), NLCD_NODATA, dtype="uint8")
        source_values_for_display = np.where(inside, values, NLCD_NODATA).astype("uint8")
        reproject(
            source=source_values_for_display,
            destination=display_values,
            src_transform=dataset.transform,
            src_crs=dataset.crs,
            src_nodata=NLCD_NODATA,
            dst_transform=display_transform,
            dst_crs=NLCD_DISPLAY_CRS,
            dst_nodata=NLCD_NODATA,
            resampling=Resampling.nearest,
        )

        aoi_display = transform(
            Transformer.from_crs("EPSG:4326", NLCD_DISPLAY_CRS, always_xy=True).transform,
            aoi,
        )
        display_inside = geometry_mask(
            [mapping(aoi_display)],
            out_shape=display_values.shape,
            transform=display_transform,
            invert=True,
            all_touched=True,
        )
        display_values[~display_inside] = NLCD_NODATA
        display_observed_values = np.unique(display_values[display_values != NLCD_NODATA])
        display_unknown_values = [
            int(value) for value in display_observed_values if int(value) not in NLCD_CLASSES
        ]
        if display_unknown_values:
            raise ValueError(
                f"NLCD display found unsupported class values: {display_unknown_values}"
            )

        rgba = np.zeros((4, display_height, display_width), dtype="uint8")
        for value in display_observed_values:
            code = int(value)
            mask = display_values == code
            rgba[0, mask], rgba[1, mask], rgba[2, mask] = NLCD_DISPLAY_PALETTE[code]
            rgba[3, mask] = 255
        _atomic_png(preview_png, rgba, display_transform)

        display_bounds = _numbers(
            (
                display_transform.c,
                display_transform.f + display_transform.e * display_height,
                display_transform.c + display_transform.a * display_width,
                display_transform.f,
            )
        )
        display_raster_metadata = {
            "crs": NLCD_DISPLAY_CRS,
            "bounds": display_bounds,
            "transform": _numbers(tuple(display_transform)[:6]),
            "width": display_width,
            "height": display_height,
            "pixel_dimensions": [display_width, display_height],
            "dtype": "uint8",
            "nodata": NLCD_NODATA,
            "resolution": [abs(float(display_transform.a)), abs(float(display_transform.e))],
        }
        alignment = {
            "aoi_crs": "EPSG:4326",
            "source_crs": dataset.crs.to_string(),
            "display_crs": NLCD_DISPLAY_CRS,
            "aoi_geometry_sha256": aoi_geometry_sha256,
            "aoi_revision": aoi_revision,
            "aoi_intersecting_pixel_count": int(inside.sum()),
            "aoi_valid_pixel_count": int((inside & ~nodata).sum()),
            "aoi_nodata_pixel_count": int((inside & nodata).sum()),
            "display_valid_pixel_count": int((display_values != NLCD_NODATA).sum()),
            "display_width": display_width,
            "display_height": display_height,
            "display_transform": _numbers(tuple(display_transform)[:6]),
            "outside_aoi_pixels_transparent": True,
            "source_nodata_transparent": True,
            "overlay_bounds_wgs84": display_bounds,
        }

    source = dict(source_metadata)
    source.update(
        {
            "sha256": observed_source_sha256,
            "byte_size": source_raster.stat().st_size,
            "raster": native_raster_metadata,
        }
    )
    preview = {
        "schema_version": NLCD_PREVIEW_SCHEMA,
        "status": "available",
        "display_derivative": True,
        "source_id": "annual_nlcd",
        "source_year": int(source.get("source_year", 2025)),
        "source": source,
        "aoi": {
            "revision": aoi_revision,
            "geometry_sha256": aoi_geometry_sha256,
            "geometry_type": aoi.geom_type,
            "bounds_wgs84": _numbers(aoi.bounds),
        },
        "source_raster": native_raster_metadata,
        "display_raster": display_raster_metadata,
        # Keep the existing frontend metadata key during the display contract
        # transition; it now intentionally describes the browser grid.
        "raster": display_raster_metadata,
        "alignment": alignment,
        "display": {
            "asset_path": preview_png.name,
            "metadata_path": metadata_json.name,
            "format": "RGBA PNG",
            "transformation": (
                "Source categorical pixels were masked to the recorded AOI, reprojected "
                "with nearest-neighbor resampling to a north-up EPSG:4326 display grid, "
                "and mapped to documented NLCD colors. Outside-AOI and nodata pixels "
                "have alpha 0."
            ),
            "opacity_default": 0.58,
            "asset_sha256": _sha256(preview_png),
            "asset_byte_size": preview_png.stat().st_size,
        },
        "observed_class_values": [int(value) for value in display_observed_values],
        "legend": [
            {
                "value": int(value),
                "label": NLCD_CLASSES[int(value)],
                "color": "#{:02x}{:02x}{:02x}".format(*NLCD_DISPLAY_PALETTE[int(value)]),
            }
            for value in display_observed_values
        ],
    }
    if generated_at is not None:
        preview["generated_at"] = generated_at
    _atomic_json(metadata_json, preview)
    return preview
