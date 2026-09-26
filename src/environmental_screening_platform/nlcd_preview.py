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
from rasterio.features import geometry_mask
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from .adapters import NLCD_CLASSES

NLCD_PREVIEW_SCHEMA = 1
NLCD_NODATA = 250
NLCD_SOURCE_CRS = "EPSG:5070"

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
    and source nodata written as alpha zero. No reprojection or resampling is
    performed; Leaflet receives the source footprint transformed to WGS84 as
    overlay bounds.
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

        rgba = np.zeros((4, dataset.height, dataset.width), dtype="uint8")
        for value in observed_values:
            code = int(value)
            mask = inside & ~nodata & (values == code)
            rgba[0, mask], rgba[1, mask], rgba[2, mask] = NLCD_DISPLAY_PALETTE[code]
            rgba[3, mask] = 255
        _atomic_png(preview_png, rgba, dataset.transform)

        to_wgs84 = Transformer.from_crs(dataset.crs, "EPSG:4326", always_xy=True).transform
        bounds_wgs84 = transform(to_wgs84, box(*dataset.bounds)).bounds
        source_bounds = _numbers(dataset.bounds)
        source_transform = _numbers(tuple(dataset.transform)[:6])
        source_resolution = [abs(float(dataset.transform.a)), abs(float(dataset.transform.e))]
        raster_metadata = {
            "crs": dataset.crs.to_string(),
            "bounds": source_bounds,
            "transform": source_transform,
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "nodata": int(dataset.nodata),
            "resolution": source_resolution,
        }
        alignment = {
            "aoi_crs": "EPSG:4326",
            "source_crs": dataset.crs.to_string(),
            "aoi_geometry_sha256": aoi_geometry_sha256,
            "aoi_revision": aoi_revision,
            "aoi_intersecting_pixel_count": int(inside.sum()),
            "aoi_valid_pixel_count": int((inside & ~nodata).sum()),
            "aoi_nodata_pixel_count": int((inside & nodata).sum()),
            "outside_aoi_pixels_transparent": True,
            "source_nodata_transparent": True,
            "overlay_bounds_wgs84": _numbers(bounds_wgs84),
        }

    source = dict(source_metadata)
    source.update(
        {
            "sha256": observed_source_sha256,
            "byte_size": source_raster.stat().st_size,
            "raster": raster_metadata,
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
        "raster": raster_metadata,
        "alignment": alignment,
        "display": {
            "asset_path": preview_png.name,
            "metadata_path": metadata_json.name,
            "format": "RGBA PNG",
            "transformation": (
                "Source categorical pixels were masked to the recorded AOI and mapped "
                "to documented NLCD colors. No reprojection or resampling was performed. "
                "Outside-AOI and nodata pixels have alpha 0."
            ),
            "opacity_default": 0.58,
            "asset_sha256": _sha256(preview_png),
            "asset_byte_size": preview_png.stat().st_size,
        },
        "observed_class_values": [int(value) for value in observed_values],
        "legend": [
            {
                "value": int(value),
                "label": NLCD_CLASSES[int(value)],
                "color": "#{:02x}{:02x}{:02x}".format(*NLCD_DISPLAY_PALETTE[int(value)]),
            }
            for value in observed_values
        ],
    }
    if generated_at is not None:
        preview["generated_at"] = generated_at
    _atomic_json(metadata_json, preview)
    return preview
