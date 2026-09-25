"""AOI-bounded TNM Access planning and acquisition for 3DEP DEM tiles."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
from pyproj import CRS, Transformer
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform

from .adapters import TERMS, ProviderData
from .aoi import AoiContext
from .models import Acquisition, AttemptStatus, Coverage, Maturity, Observation, SourceResult
from .store import fetch_raw

THREEDEP_INVENTORY_URL = "https://tnmaccess.nationalmap.gov/api/v1/products"
THREEDEP_DATASET = "National Elevation Dataset (NED)"
THREEDEP_QUERY = "USGS 1/3 Arc Second"
THREEDEP_FORMAT = "GeoTIFF"
THREEDEP_NATIVE_CRS = "EPSG:4269"
THREEDEP_NODATA = -999999
THREEDEP_NOMINAL_ARC_SECONDS = 1 / 3
THREEDEP_MAX_TILES = 16
THREEDEP_MAX_INVENTORY_ITEMS = 1000
# A native 1x1-degree 1/3-arc-second tile is approximately 10,801 x 10,801
# cells. Keep the full native tile within an explicit, bounded validation cap.
THREEDEP_MAX_TILE_CELLS = 125_000_000
THREEDEP_MAX_TILE_BYTES = 600_000_000

_TILE_FILENAME = re.compile(r"USGS_13_(?P<tile>.+?)_(?P<date>\d{8})\.(?:tif|tiff)$", re.I)
_CURRENT_TILE_FILENAME = re.compile(r"USGS_13_(?P<tile>.+?)\.(?:tif|tiff)$", re.I)


def _inventory_parameters(aoi: Any, max_items: int) -> dict[str, Any]:
    minx, miny, maxx, maxy = aoi.bounds
    return {
        "datasets": THREEDEP_DATASET,
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "prodFormats": THREEDEP_FORMAT,
        "q": THREEDEP_QUERY,
        "max": max_items,
        "offset": 0,
    }


def _tile_id(item: dict[str, Any]) -> str:
    url = str(item.get("downloadURL") or "")
    filename = urlparse(url).path.rsplit("/", 1)[-1]
    match = _TILE_FILENAME.match(filename) or _CURRENT_TILE_FILENAME.match(filename)
    if match:
        return match.group("tile")
    title = str(item.get("title") or "")
    match = re.search(r"\b([ns]\d{2}[ew]\d{3})\b", title, re.I)
    if match:
        return match.group(1).lower()
    raise ValueError(f"3DEP inventory item has no stable tile identifier: {title or url}")


def _item_bounds(item: dict[str, Any]) -> tuple[float, float, float, float]:
    bounds = item.get("boundingBox")
    if not isinstance(bounds, dict):
        raise ValueError(f"3DEP inventory item has no boundingBox: {item.get('title', '')}")
    try:
        values = tuple(float(bounds[key]) for key in ("minX", "minY", "maxX", "maxY"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("3DEP inventory boundingBox is incomplete or non-numeric") from exc
    if (
        not all(np.isfinite(value) for value in values)
        or values[0] >= values[2]
        or values[1] >= values[3]
    ):
        raise ValueError("3DEP inventory boundingBox is not a finite nonempty extent")
    return values[0], values[1], values[2], values[3]


def _item_summary(item: dict[str, Any], *, tile_id: str, intersects_aoi: bool) -> dict[str, Any]:
    download_url = str(item.get("downloadURL") or "")
    parsed = urlparse(download_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"3DEP inventory item has an invalid download URL: {download_url}")
    return {
        "tile_id": tile_id,
        "product_id": item.get("sourceId"),
        "title": item.get("title"),
        "download_url": download_url,
        "metadata_url": item.get("metaUrl"),
        "vendor_metadata_url": item.get("vendorMetaUrl"),
        "publication_date": item.get("publicationDate"),
        "last_updated": item.get("lastUpdated"),
        "modification_info": item.get("modificationInfo"),
        "provider_reported_size_bytes": item.get("sizeInBytes"),
        "format": item.get("format"),
        "extent": item.get("extent"),
        "bounding_box": list(_item_bounds(item)),
        "intersects_aoi": intersects_aoi,
        "vertical_datum": "NAVD88 (CONUS; provider description)",
        "vertical_units": "meters",
    }


def _date_key(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text


def discover_3dep_tile_plan(
    session: Any,
    context: AoiContext,
    *,
    max_tiles: int = THREEDEP_MAX_TILES,
    max_inventory_items: int = THREEDEP_MAX_INVENTORY_ITEMS,
) -> dict[str, Any]:
    """Query TNM Access and return a deterministic plan before any tile download."""
    minx, miny, maxx, maxy = context.geometry.bounds
    estimated_tiles = max(1, int(np.ceil(maxx - minx))) * max(1, int(np.ceil(maxy - miny)))
    if estimated_tiles > max_tiles:
        raise ValueError(
            "3DEP AOI exceeds the bounded tile-plan limit: "
            f"{estimated_tiles} estimated 1x1-degree tiles > {max_tiles}; "
            "mosaicking and multi-plan tiling are not implemented"
        )

    params = _inventory_parameters(context.geometry, max_inventory_items)
    response = session.get(THREEDEP_INVENTORY_URL, params=params, timeout=(10, 60))
    response.raise_for_status()
    final_url = str(response.url)
    parsed_final = urlparse(final_url)
    if (
        parsed_final.scheme != "https"
        or parsed_final.hostname != urlparse(THREEDEP_INVENTORY_URL).hostname
    ):
        response.close()
        raise ValueError(f"TNM Access redirected to an unapproved URL: {final_url}")
    payload = response.json()
    response_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in {"content-type", "etag", "last-modified", "content-length"}
    }
    response.close()
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("TNM Access returned an invalid products response")
    total = int(payload.get("total", len(payload["items"])))
    if total > max_inventory_items or len(payload["items"]) != total:
        raise ValueError(
            "3DEP inventory response exceeds the bounded product-plan limit or is incomplete: "
            f"reported {total}, received {len(payload['items'])}, limit {max_inventory_items}"
        )

    aoi = context.geometry
    candidates: list[dict[str, Any]] = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise ValueError("TNM Access returned a non-object inventory item")
        bounds = _item_bounds(item)
        intersects = box(*bounds).intersects(aoi)
        if intersects:
            candidates.append(_item_summary(item, tile_id=_tile_id(item), intersects_aoi=True))
    if not candidates:
        raise ValueError("TNM Access returned no official 3DEP 1/3-arc-second tile for the AOI")

    selected: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        tile_id = candidate["tile_id"]
        current = selected.get(tile_id)
        key = (
            _date_key(candidate.get("publication_date")),
            _date_key(candidate.get("last_updated")),
            str(candidate.get("product_id") or ""),
            candidate["download_url"],
        )
        current_key = (
            (
                _date_key(current.get("publication_date")),
                _date_key(current.get("last_updated")),
                str(current.get("product_id") or ""),
                current["download_url"],
            )
            if current
            else None
        )
        if current is None or current_key is None or key > current_key:
            selected[tile_id] = candidate

    selected_tiles = [selected[tile_id] for tile_id in sorted(selected)]
    if len(selected_tiles) > max_tiles:
        raise ValueError(
            "3DEP AOI intersects too many selected tiles: "
            f"{len(selected_tiles)} > {max_tiles}; mosaicking and multi-plan tiling are not implemented"
        )
    return {
        "aoi_id": context.aoi_id,
        "aoi_revision": context.revision,
        "aoi_input_sha256": context.input_sha256,
        "aoi_geometry_sha256": context.geometry_sha256,
        "aoi_validation_policy": context.validation_policy,
        "inventory_url": THREEDEP_INVENTORY_URL,
        "inventory_final_url": final_url,
        "inventory_parameters": params,
        "inventory_retrieved_at": datetime.now(UTC).isoformat(),
        "inventory_response_headers": response_headers,
        "inventory_total": total,
        "estimated_tile_count": estimated_tiles,
        "selection_policy": "one intersecting product per tile; newest publication date, then last update, product ID, and URL",
        "candidate_products": sorted(
            candidates, key=lambda item: (item["tile_id"], item["download_url"])
        ),
        "selected_tiles": selected_tiles,
        "status": "planned",
    }


def validate_3dep_tile_raster(
    body: bytes,
    aoi: Any,
    *,
    tile: dict[str, Any],
    max_cells: int = THREEDEP_MAX_TILE_CELLS,
) -> dict[str, Any]:
    """Validate one native 1/3-arc-second DEM tile without clipping or resampling."""
    to_area = Transformer.from_crs(THREEDEP_NATIVE_CRS, "EPSG:5070", always_xy=True).transform
    aoi_area = transform(
        Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform, aoi
    )
    with MemoryFile(body) as memory, memory.open() as dataset:
        if dataset.count != 1 or dataset.width <= 0 or dataset.height <= 0:
            raise ValueError("3DEP tile must be a readable single-band raster")
        if dataset.width * dataset.height > max_cells:
            raise ValueError("3DEP tile exceeds the bounded cell limit")
        if (
            dataset.crs is None
            or dataset.crs.to_epsg() != CRS.from_user_input(THREEDEP_NATIVE_CRS).to_epsg()
        ):
            raise ValueError("3DEP tile CRS is not the native NAD83 geographic CRS")
        if dataset.dtypes[0] not in {"int16", "float32", "float64"}:
            raise ValueError(f"3DEP tile has an unsupported DEM datatype: {dataset.dtypes[0]}")
        x_resolution, y_resolution = dataset.res
        transform_x_resolution = dataset.transform.a
        transform_y_resolution = dataset.transform.e
        expected_resolution = THREEDEP_NOMINAL_ARC_SECONDS / 3600
        if (
            abs(abs(x_resolution) - expected_resolution) > 1e-6
            or abs(abs(y_resolution) - expected_resolution) > 1e-6
        ):
            raise ValueError(
                "3DEP tile is not the nominal 1/3-arc-second grid: "
                f"{x_resolution} x {y_resolution} degrees"
            )
        if (
            transform_x_resolution <= 0
            or transform_y_resolution >= 0
            or dataset.transform.b != 0
            or dataset.transform.d != 0
        ):
            raise ValueError("3DEP tile transform is not a regular north-up geographic grid")
        if dataset.nodata is None or float(dataset.nodata) != THREEDEP_NODATA:
            raise ValueError(f"3DEP tile nodata must be {THREEDEP_NODATA}, got {dataset.nodata}")
        values = dataset.read(1).astype("float64")
        aoi_source = transform(
            Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform, aoi
        )
        inside = geometry_mask(
            [mapping(aoi_source)],
            out_shape=values.shape,
            transform=dataset.transform,
            invert=True,
            all_touched=True,
        )
        finite = np.isfinite(values)
        nodata_mask = values == THREEDEP_NODATA
        valid = inside & finite & ~nodata_mask
        nodata_inside = inside & nodata_mask
        heights = values[valid]
        footprint = Polygon.from_bounds(*dataset.bounds)
        footprint_area = transform(to_area, footprint)
        covered_area = aoi_area.intersection(footprint_area).area
        uncovered_area = max(0.0, aoi_area.area - covered_area)
        quantiles = np.quantile(heights, [0, 0.25, 0.5, 0.75, 1]).tolist() if heights.size else []
        return {
            "tile_id": tile["tile_id"],
            "product_id": tile.get("product_id"),
            "source_crs": dataset.crs.to_string(),
            "dimensions": {"width": dataset.width, "height": dataset.height},
            "dtype": dataset.dtypes[0],
            "transform": list(dataset.transform)[:6],
            "resolution_degrees": [float(x_resolution), float(y_resolution)],
            "resolution_arc_seconds": [
                float(abs(x_resolution) * 3600),
                float(abs(y_resolution) * 3600),
            ],
            "nominal_resolution_arc_seconds": THREEDEP_NOMINAL_ARC_SECONDS,
            "nodata": float(dataset.nodata),
            "vertical_datum": tile.get("vertical_datum"),
            "vertical_units": tile.get("vertical_units"),
            "coverage": {
                "aoi_area_sqkm": round(aoi_area.area / 1_000_000, 6),
                "raster_footprint_sqkm": round(footprint_area.area / 1_000_000, 6),
                "covered_aoi_area_sqkm": round(covered_area / 1_000_000, 6),
                "uncovered_aoi_area_sqkm": round(uncovered_area / 1_000_000, 6),
                "covered_aoi_percentage": round(covered_area / aoi_area.area * 100, 6)
                if aoi_area.area
                else None,
                "uncovered_aoi_percentage": round(uncovered_area / aoi_area.area * 100, 6)
                if aoi_area.area
                else None,
            },
            "pixel_accounting": {
                "raster_pixel_count": int(values.size),
                "outside_aoi_pixel_count": int((~inside).sum()),
                "covered_aoi_pixel_count": int(inside.sum()),
                "valid_pixel_count": int(valid.sum()),
                "nodata_pixel_count": int(nodata_inside.sum()),
            },
            "elevation_m": {
                "min": float(quantiles[0]),
                "p25": float(quantiles[1]),
                "median": float(quantiles[2]),
                "p75": float(quantiles[3]),
                "max": float(quantiles[4]),
                "mean": float(heights.mean()),
            }
            if heights.size
            else None,
            "observed_valid": bool(heights.size),
            "tile_bounds": [float(value) for value in dataset.bounds],
        }


def acquire_3dep_tile(
    session: Any,
    data_root: Path,
    context: AoiContext,
    tile: dict[str, Any],
    *,
    plan_id: str,
    inventory_parameters: dict[str, Any],
    acquisition_callback: Callable[[Acquisition], None] | None = None,
    max_bytes: int = THREEDEP_MAX_TILE_BYTES,
) -> ProviderData:
    """Acquire and validate one planned official 3DEP tile."""
    release = f"USGS 3DEP 1/3 arc-second {tile.get('publication_date') or tile['title']}"
    recorded_parameters = {
        "inventory_url": THREEDEP_INVENTORY_URL,
        "inventory_parameters": inventory_parameters,
        "tile_id": tile["tile_id"],
        "product_id": tile.get("product_id"),
        "publication_date": tile.get("publication_date"),
    }
    body, metadata = fetch_raw(
        session,
        source_id="3dep",
        provider="USGS The National Map / 3DEP",
        release=release,
        url=tile["download_url"],
        params=None,
        data_root=data_root,
        terms_url=TERMS["3dep"],
        max_bytes=max_bytes,
        media_type="image/tiff",
        recorded_request_parameters=recorded_parameters,
        acquisition_callback=acquisition_callback,
    )
    profile = validate_3dep_tile_raster(body, context.geometry, tile=tile)
    has_nodata = profile["pixel_accounting"]["nodata_pixel_count"] > 0
    has_uncovered = profile["coverage"]["uncovered_aoi_area_sqkm"] > 0
    provenance = metadata.to_dict()
    provenance.update(
        {
            "plan_id": plan_id,
            "aoi_id": context.aoi_id,
            "aoi_revision": context.revision,
            "aoi_input_sha256": context.input_sha256,
            "aoi_geometry_sha256": context.geometry_sha256,
            "aoi_validation_policy": context.validation_policy,
            "tile_id": tile["tile_id"],
            "product_id": tile.get("product_id"),
            "metadata_url": tile.get("metadata_url"),
            "vendor_metadata_url": tile.get("vendor_metadata_url"),
            "publication_date": tile.get("publication_date"),
            "provider_reported_size_bytes": tile.get("provider_reported_size_bytes"),
            "inventory_parameters": inventory_parameters,
            "raster_validation": profile,
        }
    )
    return ProviderData(
        SourceResult(
            source_id="3dep",
            validation_status=Maturity.VALIDATED,
            validation_scope=(
                "Official TNM Access 1/3-arc-second GeoTIFF tile; exact planned tile and "
                "AOI intersection validated, inactive candidate"
            ),
            coverage_status=Coverage.PARTIAL if has_uncovered else Coverage.COMPLETE,
            observation_status=Observation.NODATA
            if has_nodata or not profile["observed_valid"]
            else Observation.DATA_OBSERVED,
            product_status=release,
            attempt_status=AttemptStatus.VALIDATED,
            metrics=profile,
            provenance=provenance,
            warnings=[
                "The tile is retained at its native geographic grid; no clipping, resampling, or mosaicking is performed.",
                "Nodata and uncovered AOI areas remain unknown and are not interpreted as absence of a constraint.",
                "Elevation values are reported in provider-declared meters/NAVD88 metadata; no derived slope or suitability interpretation is added.",
            ],
            reason=(
                "The planned tile contains nodata or uncovered AOI area; those locations remain unknown."
                if has_nodata or has_uncovered or not profile["observed_valid"]
                else None
            ),
        ),
        value=profile,
    )
