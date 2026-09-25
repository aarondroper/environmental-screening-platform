"""Bounded official-provider adapters used by the local screening worker."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import shapefile
from pyproj import CRS, Transformer
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform

from .aoi import AoiContext
from .models import (
    MATURITY,
    Acquisition,
    AttemptStatus,
    Coverage,
    Maturity,
    Observation,
    SourceResult,
)
from .regression_fixtures import NORTHERN_COLORADO_REGRESSION_FIXTURE
from .store import fetch_raw

CENSUS_URL = "https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip"
NLCD_WCS = "https://dmsdata.cr.usgs.gov/geoserver/wcs"
NLCD_COVERAGE = "mrlc_Land-Cover_conus_year_data:Land-Cover_conus_year_data"
# Product-level Annual NLCD contract. These values are independent of the
# Northern Colorado regression fixture and apply to any bounded AOI request.
NLCD_NATIVE_CRS = "EPSG:5070"
NLCD_NATIVE_RESOLUTION_M = 30.0
NLCD_NATIVE_NODATA = 250
NLCD_PRODUCT_RELEASE = "Annual NLCD Collection 1.2, 2025 land cover"
NLCD_REGIONAL_CRS = str(NORTHERN_COLORADO_REGRESSION_FIXTURE.nlcd.crs)
NLCD_REGIONAL_RESOLUTION_M = float(NORTHERN_COLORADO_REGRESSION_FIXTURE.nlcd.resolution_m)
NLCD_REGIONAL_NODATA = int(NORTHERN_COLORADO_REGRESSION_FIXTURE.nlcd.nodata)
# The exact three-county bounding rectangle includes two detached components;
# its measured provider-snapped window is about 45.7 million cells.
NLCD_REGIONAL_MAX_CELLS = NORTHERN_COLORADO_REGRESSION_FIXTURE.nlcd.max_cells
# Generic AOI requests use the same bounded native grid contract, but this limit
# is deliberately not derived from the Northern Colorado fixture geometry.
NLCD_AOI_MAX_CELLS = 50_000_000
# The WCS provider returns unstable sub-30 m transforms for very small
# envelopes. A bounded padded window gives the provider enough native-grid
# context while the validator still masks all outside-AOI pixels.
NLCD_AOI_MIN_WINDOW_M = 20_000.0
NLCD_RELEASE = NORTHERN_COLORADO_REGRESSION_FIXTURE.nlcd.release
NLCD_CLASSES = {
    11: "open_water",
    12: "perennial_ice_snow",
    21: "developed_open_space",
    22: "developed_low_intensity",
    23: "developed_medium_intensity",
    24: "developed_high_intensity",
    31: "barren_land",
    41: "deciduous_forest",
    42: "evergreen_forest",
    43: "mixed_forest",
    52: "shrub_scrub",
    71: "grassland_herbaceous",
    72: "sedge_herbaceous",
    73: "lichens",
    74: "moss",
    81: "pasture_hay",
    82: "cultivated_crops",
    90: "woody_wetlands_classification",
    95: "emergent_herbaceous_wetlands_classification",
}
THREEDEP_IMAGE = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
)
SSURGO_SDA = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"
GEOGRAPHY_IDS = NORTHERN_COLORADO_REGRESSION_FIXTURE.county_names
TERMS = {
    "census_boundary": "https://www.census.gov/data/developers/about/terms-of-service.html",
    "annual_nlcd": "https://doi.org/10.5066/P143HE8T",
    "3dep": "https://www.usgs.gov/3d-elevation-program/about-3dep-products-services",
    "ssurgo": "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
}


@dataclass
class ProviderData:
    result: SourceResult
    value: Any = None


def _acquisition(acquisition: Acquisition) -> dict[str, Any]:
    return acquisition.to_dict()


def acquire_boundary(
    session: Any,
    data_root: Path,
    *,
    acquisition_callback: Callable[[Acquisition], None] | None = None,
) -> ProviderData:
    body, meta = fetch_raw(
        session,
        source_id="census_boundary",
        provider="US Census Bureau TIGER/Line",
        release="TIGER/Line 2025 county",
        url=CENSUS_URL,
        params=None,
        data_root=data_root,
        terms_url=TERMS["census_boundary"],
        max_bytes=120_000_000,
        media_type="application/zip",
        acquisition_callback=acquisition_callback,
    )
    return parse_boundary_archive(body, meta)


def parse_boundary_archive(body: bytes, meta: Acquisition) -> ProviderData:
    """Validate and normalize an acquired TIGER/Line archive; also used by artifact fixtures."""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"Census archive CRC failure in {bad}")
        shp_name = next(
            n for n in archive.namelist() if n.lower().endswith("tl_2025_us_county.shp")
        )
        dbf_name = shp_name[:-4] + ".dbf"
        prj_name = shp_name[:-4] + ".prj"
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(shp_name)), dbf=io.BytesIO(archive.read(dbf_name))
        )
        fields = [f[0] for f in reader.fields[1:]]
        records: dict[str, Any] = {}
        for record, shp in zip(reader.records(), reader.shapes(), strict=True):
            attrs = dict(zip(fields, record, strict=True))
            geoid = str(attrs.get("GEOID", ""))
            if geoid in GEOGRAPHY_IDS:
                geom = shape(shp.__geo_interface__)
                if (
                    not geom.is_valid
                    or geom.is_empty
                    or geom.geom_type not in {"Polygon", "MultiPolygon"}
                ):
                    raise ValueError(f"Invalid Census geometry for {geoid}")
                records[geoid] = {"geometry": geom, "attributes": attrs}
        if set(records) != set(GEOGRAPHY_IDS):
            raise ValueError(f"Census county IDs incomplete: {sorted(records)}")
        prj = (
            archive.read(prj_name).decode("ascii", errors="replace")
            if prj_name in archive.namelist()
            else ""
        )
        if not prj or CRS.from_wkt(prj).to_epsg() != 4269:
            raise ValueError("Unexpected or missing Census county CRS metadata")
    from shapely.ops import unary_union

    boundary = unary_union([records[k]["geometry"] for k in sorted(records)])
    if not boundary.is_valid or boundary.is_empty:
        raise ValueError("Three-county union is invalid")
    union_components = len(boundary.geoms) if boundary.geom_type == "MultiPolygon" else 1
    if boundary.geom_type != "MultiPolygon" or union_components != 3:
        raise ValueError(
            f"2025 approved county union changed expected 3-component multipart topology: "
            f"{boundary.geom_type} with {union_components} component(s)"
        )
    to_area = Transformer.from_crs("EPSG:4269", "EPSG:5070", always_xy=True).transform
    area_sqmi = transform(to_area, boundary).area / 2_589_988.110336
    return ProviderData(
        SourceResult(
            source_id="census_boundary",
            validation_status=Maturity.VALIDATED,
            validation_scope="Current TIGER/Line 2025 archive; exact approved county GEOIDs and union geometry validated per run",
            coverage_status=Coverage.COMPLETE,
            observation_status=Observation.DATA_OBSERVED,
            product_status="2025 county geometry",
            attempt_status=AttemptStatus.VALIDATED,
            metrics={
                "county_geoids": sorted(records),
                "county_names": GEOGRAPHY_IDS,
                "crs": "EPSG:4269",
                "union_type": boundary.geom_type,
                "union_components": union_components,
                "union_area_sqmi": round(area_sqmi, 3),
                "bounds_epsg4269": [round(v, 6) for v in boundary.bounds],
            },
            provenance=_acquisition(meta),
        ),
        value={"boundary": boundary, "counties": records},
    )


def acquire_nlcd(
    session: Any,
    data_root: Path,
    aoi_4326: Any,
    *,
    acquisition_callback: Callable[[Acquisition], None] | None = None,
) -> ProviderData:
    # WCS 1.0 uses the advertised offering name and native EPSG:3857 coverage grid.
    to_service = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    aoi_service = transform(to_service, aoi_4326)
    to_area = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    aoi_area = transform(to_area, aoi_4326)
    minx, miny, maxx, maxy = aoi_service.bounds
    # The documented service sample is about 38.5 map metres (~30 m ground) at this latitude.
    resolution = 38.5
    width = max(1, int(np.ceil((maxx - minx) / resolution)))
    height = max(1, int(np.ceil((maxy - miny) / resolution)))
    if width * height > 16_000_000:
        raise ValueError("AOI NLCD request exceeds 16 million cells; submit a smaller AOI")
    params = {
        "service": "WCS",
        "version": "1.0.0",
        "request": "GetCoverage",
        "coverage": NLCD_COVERAGE,
        "time": "2025-01-01T00:00:00.000Z",
        "crs": "EPSG:3857",
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "width": width,
        "height": height,
        "format": "image/geotiff",
    }
    body, meta = fetch_raw(
        session,
        source_id="annual_nlcd",
        provider="USGS EROS / MRLC Annual NLCD WCS",
        release="Annual NLCD Collection 1.2, 2025 land cover",
        url=NLCD_WCS,
        params=params,
        data_root=data_root,
        terms_url=TERMS["annual_nlcd"],
        max_bytes=256_000_000,
        acquisition_callback=acquisition_callback,
    )
    if not meta.media_type.lower().startswith("image/tiff"):
        raise ValueError(f"NLCD WCS returned {meta.media_type}, not a GeoTIFF coverage")
    with MemoryFile(body) as mem, mem.open() as dataset:
        if dataset.count != 1 or dataset.width * dataset.height > 16_000_000:
            raise ValueError("NLCD response has unexpected bands or dimensions")
        if dataset.crs is None or dataset.crs.to_epsg() != 3857:
            raise ValueError("NLCD response CRS is not the requested native-service EPSG:3857")
        values = dataset.read(1)
        inside = geometry_mask(
            [mapping(aoi_service)],
            out_shape=values.shape,
            transform=dataset.transform,
            invert=True,
            all_touched=True,
        )
        nodata = dataset.nodata
        valid = (
            values != nodata if nodata is not None else np.ones(values.shape, dtype=bool)
        ) & inside
        classes, counts = np.unique(values[valid], return_counts=True)
        to_area_from_service = Transformer.from_crs(
            dataset.crs, "EPSG:5070", always_xy=True
        ).transform
        pixel_corners = [
            dataset.transform @ (0, 0),
            dataset.transform @ (1, 0),
            dataset.transform @ (1, 1),
            dataset.transform @ (0, 1),
        ]
        cell_area = Polygon([to_area_from_service(x, y) for x, y in pixel_corners]).area
        class_metrics = {
            str(int(code)): {
                "class_name": NLCD_CLASSES.get(int(code), "unrecognized_or_other"),
                "pixel_count": int(count),
                "estimated_area_sqkm": round(float(count * cell_area / 1_000_000), 6),
            }
            for code, count in zip(classes, counts, strict=True)
        }
        nodata_inside = inside & ~valid
        profile = {
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "nodata": nodata,
            "transform": list(dataset.transform)[:6],
            "aoi_cells_touched": int(inside.sum()),
            "valid_pixels": int(valid.sum()),
            "nodata_pixels": int(nodata_inside.sum()),
            "valid_data_fraction_of_aoi_cells": round(float(valid.sum() / inside.sum()), 6)
            if inside.any()
            else None,
            "aoi_area_sqkm": round(aoi_area.area / 1_000_000, 6),
            "classes": class_metrics,
        }
    if not profile["crs"] or not profile["valid_pixels"]:
        raise ValueError("NLCD response lacks a readable CRS or valid data")
    has_nodata = profile["nodata_pixels"] > 0
    return ProviderData(
        SourceResult(
            source_id="annual_nlcd",
            validation_status=Maturity.VALIDATED,
            validation_scope=MATURITY["annual_nlcd"][1],
            coverage_status=Coverage.PARTIAL if has_nodata else Coverage.COMPLETE,
            observation_status=Observation.INCOMPLETE_SOURCE
            if has_nodata
            else Observation.DATA_OBSERVED,
            product_status="effective 2025 annual land cover",
            attempt_status=AttemptStatus.VALIDATED,
            metrics=profile,
            provenance=_acquisition(meta),
            warnings=[
                "WCS 1.0 native-service EPSG:3857 grid; ground area estimated per pixel after EPSG:5070 transformation.",
                "NLCD wetland-themed classes are land-cover classifications, not wetland determinations.",
            ],
            reason="Nodata cells inside requested AOI window" if has_nodata else None,
        ),
        value=profile,
    )


def _nlcd_regional_request(aoi_4326: Any) -> dict[str, Any]:
    """Build the bounded native-product request for the approved regional window."""
    to_product = Transformer.from_crs("EPSG:4326", NLCD_REGIONAL_CRS, always_xy=True).transform
    aoi_product = transform(to_product, aoi_4326)
    minx, miny, maxx, maxy = aoi_product.bounds
    return {
        "service": "WCS",
        "version": "1.0.0",
        "request": "GetCoverage",
        "coverage": NLCD_COVERAGE,
        "time": "2025-01-01T00:00:00.000Z",
        "crs": NLCD_REGIONAL_CRS,
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "resx": NLCD_REGIONAL_RESOLUTION_M,
        "resy": NLCD_REGIONAL_RESOLUTION_M,
        "format": "image/geotiff",
    }


def _nlcd_aoi_request(aoi_4326: Any) -> dict[str, Any]:
    """Build a bounded native-product request from an arbitrary WGS84 AOI."""
    to_product = Transformer.from_crs("EPSG:4326", NLCD_NATIVE_CRS, always_xy=True).transform
    aoi_product = transform(to_product, aoi_4326)
    minx, miny, maxx, maxy = aoi_product.bounds
    width_m = maxx - minx
    height_m = maxy - miny
    if width_m < NLCD_AOI_MIN_WINDOW_M:
        padding = (NLCD_AOI_MIN_WINDOW_M - width_m) / 2
        minx -= padding
        maxx += padding
    if height_m < NLCD_AOI_MIN_WINDOW_M:
        padding = (NLCD_AOI_MIN_WINDOW_M - height_m) / 2
        miny -= padding
        maxy += padding
    width = max(1, int(np.ceil((maxx - minx) / NLCD_NATIVE_RESOLUTION_M)))
    height = max(1, int(np.ceil((maxy - miny) / NLCD_NATIVE_RESOLUTION_M)))
    estimated_cells = width * height
    if estimated_cells > NLCD_AOI_MAX_CELLS:
        raise ValueError(
            "NLCD AOI request exceeds the bounded "
            f"{NLCD_AOI_MAX_CELLS}-cell limit ({estimated_cells} estimated cells); "
            "submit a smaller AOI; tiling is not implemented"
        )
    return {
        "service": "WCS",
        "version": "1.0.0",
        "request": "GetCoverage",
        "coverage": NLCD_COVERAGE,
        "time": "2025-01-01T00:00:00.000Z",
        "crs": NLCD_NATIVE_CRS,
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "resx": NLCD_NATIVE_RESOLUTION_M,
        "resy": NLCD_NATIVE_RESOLUTION_M,
        "format": "image/geotiff",
    }


def _validate_nlcd_regional_raster(
    body: bytes,
    aoi_4326: Any,
    *,
    max_cells: int = NLCD_REGIONAL_MAX_CELLS,
    expected_crs: str = NLCD_REGIONAL_CRS,
    expected_nodata: int = NLCD_REGIONAL_NODATA,
    nominal_resolution_m: float = NLCD_REGIONAL_RESOLUTION_M,
) -> dict[str, Any]:
    """Validate a provider-returned regional NLCD raster without resampling it."""
    to_product = Transformer.from_crs("EPSG:4326", expected_crs, always_xy=True).transform
    aoi_product = transform(to_product, aoi_4326)
    with MemoryFile(body) as mem, mem.open() as dataset:
        if dataset.count != 1:
            raise ValueError("Regional NLCD response must contain exactly one categorical band")
        if dataset.width * dataset.height > max_cells:
            raise ValueError("Regional NLCD response exceeds the bounded cell limit")
        if (
            dataset.crs is None
            or dataset.crs.to_epsg() != CRS.from_user_input(expected_crs).to_epsg()
        ):
            raise ValueError("Regional NLCD response CRS is not the expected native product CRS")
        if dataset.dtypes[0] != "uint8":
            raise ValueError(f"Regional NLCD response must be uint8, got {dataset.dtypes[0]}")
        x_resolution, y_resolution = dataset.res
        if not (
            nominal_resolution_m - 1.0 <= x_resolution <= nominal_resolution_m + 1.0
            and nominal_resolution_m - 1.0 <= y_resolution <= nominal_resolution_m + 1.0
        ):
            raise ValueError(
                "Regional NLCD response is not the nominal 30 m product grid: "
                f"{x_resolution} x {y_resolution} m"
            )
        if (
            abs(x_resolution - y_resolution) > 0.01
            or dataset.transform.b != 0
            or dataset.transform.d != 0
        ):
            raise ValueError("Regional NLCD response is not a regular square aligned raster grid")
        if dataset.nodata is None or int(dataset.nodata) != expected_nodata:
            raise ValueError(
                f"Regional NLCD nodata must be {expected_nodata}, got {dataset.nodata}"
            )
        values = dataset.read(1)
        inside = geometry_mask(
            [mapping(aoi_product)],
            out_shape=values.shape,
            transform=dataset.transform,
            invert=True,
            all_touched=True,
        )
        nodata_mask = values == expected_nodata
        observed_values = values[inside & ~nodata_mask]
        invalid = sorted(
            {int(value) for value in observed_values if int(value) not in NLCD_CLASSES}
        )
        if invalid:
            raise ValueError(
                f"Regional NLCD contains values outside the official class domain: {invalid}"
            )
        footprint = Polygon.from_bounds(*dataset.bounds)
        covered_area = aoi_product.intersection(footprint).area
        aoi_area = aoi_product.area
        uncovered_area = max(0.0, aoi_area - covered_area)
        valid_inside = inside & ~nodata_mask
        nodata_inside = inside & nodata_mask
        classes, counts = np.unique(values[valid_inside], return_counts=True)
        class_metrics = {
            str(int(code)): {
                "class_name": NLCD_CLASSES[int(code)],
                "pixel_count": int(count),
                "percentage_of_valid_covered_pixels": round(
                    float(count / valid_inside.sum() * 100), 6
                )
                if valid_inside.any()
                else None,
            }
            for code, count in zip(classes, counts, strict=True)
        }
        profile = {
            "crs": dataset.crs.to_string(),
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "transform": list(dataset.transform)[:6],
            "bounds": [float(value) for value in dataset.bounds],
            "resolution_m": [float(x_resolution), float(y_resolution)],
            "nominal_resolution_m": nominal_resolution_m,
            "nodata": int(dataset.nodata),
            "source_year": 2025,
            "coverage": {
                "aoi_area_sqkm": round(aoi_area / 1_000_000, 6),
                "raster_footprint_sqkm": round(footprint.area / 1_000_000, 6),
                "covered_aoi_area_sqkm": round(covered_area / 1_000_000, 6),
                "uncovered_aoi_area_sqkm": round(uncovered_area / 1_000_000, 6),
                "covered_aoi_percentage": round(covered_area / aoi_area * 100, 6)
                if aoi_area
                else None,
                "uncovered_aoi_percentage": round(uncovered_area / aoi_area * 100, 6)
                if aoi_area
                else None,
            },
            "pixel_accounting": {
                "raster_pixel_count": int(values.size),
                "outside_aoi_pixel_count": int((~inside).sum()),
                "covered_aoi_pixel_count": int(inside.sum()),
                "valid_pixel_count": int(valid_inside.sum()),
                "nodata_pixel_count": int(nodata_inside.sum()),
            },
            "classes": class_metrics,
            "observed_class_values": [int(code) for code in classes],
            "grid_alignment": "Provider-snapped EPSG:5070 square grid; no client resampling",
        }
    if not observed_values.size:
        raise ValueError("Regional NLCD response contains no valid pixels inside the approved AOI")
    return profile


def _validate_nlcd_aoi_raster(body: bytes, aoi_4326: Any) -> dict[str, Any]:
    """Validate one bounded native NLCD raster against an arbitrary AOI."""
    return _validate_nlcd_regional_raster(
        body,
        aoi_4326,
        max_cells=NLCD_AOI_MAX_CELLS,
        expected_crs=NLCD_NATIVE_CRS,
        expected_nodata=NLCD_NATIVE_NODATA,
        nominal_resolution_m=NLCD_NATIVE_RESOLUTION_M,
    )


def acquire_nlcd_regional(
    session: Any,
    data_root: Path,
    aoi_4326: Any,
    *,
    acquisition_callback: Callable[[Acquisition], None] | None = None,
) -> ProviderData:
    """Acquire the exact approved regional 2025 NLCD window as an inactive candidate."""
    params = _nlcd_regional_request(aoi_4326)
    body, meta = fetch_raw(
        session,
        source_id="annual_nlcd",
        provider="USGS EROS / MRLC Annual NLCD WCS",
        release=NLCD_RELEASE,
        url=NLCD_WCS,
        params=params,
        data_root=data_root,
        terms_url=TERMS["annual_nlcd"],
        max_bytes=256_000_000,
        media_type="image/tiff",
        acquisition_callback=acquisition_callback,
    )
    if not meta.media_type.lower().startswith("image/tiff"):
        raise ValueError(f"Regional NLCD WCS returned {meta.media_type}, not a GeoTIFF")
    profile = _validate_nlcd_regional_raster(body, aoi_4326)
    has_nodata = profile["pixel_accounting"]["nodata_pixel_count"] > 0
    has_uncovered = profile["coverage"]["uncovered_aoi_area_sqkm"] > 0
    return ProviderData(
        SourceResult(
            source_id="annual_nlcd",
            validation_status=Maturity.VALIDATED,
            validation_scope=(
                "Automated official WCS regional window for the exact 2025 "
                "Boulder/Larimer/Weld AOI; inactive validation-only candidate"
            ),
            coverage_status=Coverage.PARTIAL if has_uncovered else Coverage.COMPLETE,
            observation_status=Observation.INCOMPLETE_SOURCE
            if has_nodata or has_uncovered
            else Observation.DATA_OBSERVED,
            product_status=NLCD_RELEASE,
            attempt_status=AttemptStatus.VALIDATED,
            metrics=profile,
            provenance=_acquisition(meta),
            warnings=[
                "The returned raster is a bounded regional window, not a national archive or full historical bundle.",
                "Outside-AOI pixels and nodata are retained as accounting states, never as no constraint observed.",
                "NLCD values are land-cover classifications, not wetlands, regulatory, or suitability determinations.",
            ],
            reason=(
                "Regional raster contains nodata or uncovered AOI area; those locations remain unknown."
                if has_nodata or has_uncovered
                else None
            ),
        ),
        value=profile,
    )


def acquire_nlcd_aoi(
    session: Any,
    data_root: Path,
    aoi_4326: Any,
    *,
    aoi_context: AoiContext | None = None,
    acquisition_callback: Callable[[Acquisition], None] | None = None,
    max_bytes: int = 256_000_000,
) -> ProviderData:
    """Acquire one bounded Annual NLCD window for a persisted AOI revision."""
    params = _nlcd_aoi_request(aoi_4326)
    body, meta = fetch_raw(
        session,
        source_id="annual_nlcd",
        provider="USGS EROS / MRLC Annual NLCD WCS",
        release=NLCD_PRODUCT_RELEASE,
        url=NLCD_WCS,
        params=params,
        data_root=data_root,
        terms_url=TERMS["annual_nlcd"],
        max_bytes=max_bytes,
        media_type="image/tiff",
        acquisition_callback=acquisition_callback,
    )
    if not meta.media_type.lower().startswith("image/tiff"):
        raise ValueError(f"NLCD WCS returned {meta.media_type}, not a GeoTIFF")
    profile = _validate_nlcd_aoi_raster(body, aoi_4326)
    has_nodata = profile["pixel_accounting"]["nodata_pixel_count"] > 0
    has_uncovered = profile["coverage"]["uncovered_aoi_area_sqkm"] > 0
    provenance = _acquisition(meta)
    if aoi_context is not None:
        provenance.update(
            {
                "aoi_id": aoi_context.aoi_id,
                "aoi_revision": aoi_context.revision,
                "aoi_input_sha256": aoi_context.input_sha256,
                "aoi_geometry_sha256": aoi_context.geometry_sha256,
                "aoi_validation_policy": aoi_context.validation_policy,
            }
        )
    provenance.update(
        {
            "source_collection": NLCD_PRODUCT_RELEASE,
            "source_year": 2025,
            "request_crs": NLCD_NATIVE_CRS,
            "request_resolution_m": NLCD_NATIVE_RESOLUTION_M,
            "request_estimated_cells": int(
                np.ceil(
                    (float(params["bbox"].split(",")[2]) - float(params["bbox"].split(",")[0]))
                    / NLCD_NATIVE_RESOLUTION_M
                )
                * np.ceil(
                    (float(params["bbox"].split(",")[3]) - float(params["bbox"].split(",")[1]))
                    / NLCD_NATIVE_RESOLUTION_M
                )
            ),
        }
    )
    return ProviderData(
        SourceResult(
            source_id="annual_nlcd",
            validation_status=Maturity.VALIDATED,
            validation_scope=(
                "Automated official WCS window built from the selected persisted WGS84 AOI; "
                "bounded native grid, inactive validation-only candidate"
            ),
            coverage_status=Coverage.PARTIAL if has_uncovered else Coverage.COMPLETE,
            observation_status=Observation.INCOMPLETE_SOURCE
            if has_nodata or has_uncovered
            else Observation.DATA_OBSERVED,
            product_status=NLCD_PRODUCT_RELEASE,
            attempt_status=AttemptStatus.VALIDATED,
            metrics=profile,
            provenance=provenance,
            warnings=[
                "The returned raster is a bounded AOI window; national and historical bundles are not acquired.",
                "Outside-AOI pixels and nodata are retained as accounting states, never as no constraint observed.",
                "NLCD values are land-cover classifications, not wetlands, regulatory, or suitability determinations.",
            ],
            reason=(
                "Raster contains nodata or uncovered AOI area; those locations remain unknown."
                if has_nodata or has_uncovered
                else None
            ),
        ),
        value=profile,
    )


def acquire_3dep(
    session: Any,
    data_root: Path,
    aoi_4326: Any,
    *,
    acquisition_callback: Callable[[Acquisition], None] | None = None,
) -> ProviderData:
    to_area = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    aoi_area = transform(to_area, aoi_4326)
    minx, miny, maxx, maxy = aoi_area.bounds
    resolution = 10.0
    width = max(1, int(np.ceil((maxx - minx) / resolution)))
    height = max(1, int(np.ceil((maxy - miny) / resolution)))
    if width * height > 12_000_000:
        raise ValueError("AOI 3DEP request exceeds 12 million cells; submit a smaller AOI")
    params = {
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "bboxSR": 5070,
        "imageSR": 5070,
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
        "noData": -999999,
        "noDataInterpretation": "esriNoDataMatchAny",
        "f": "image",
    }
    body, meta = fetch_raw(
        session,
        source_id="3dep",
        provider="USGS 3DEP ImageServer",
        release="3DEP 1/3 arc-second service; regional window",
        url=THREEDEP_IMAGE,
        params=params,
        data_root=data_root,
        terms_url=TERMS["3dep"],
        max_bytes=256_000_000,
        acquisition_callback=acquisition_callback,
    )
    if not meta.media_type.lower().startswith("image/tiff"):
        raise ValueError(f"3DEP image service returned {meta.media_type}, not a GeoTIFF coverage")
    with MemoryFile(body) as mem, mem.open() as dataset:
        if dataset.count != 1 or dataset.width * dataset.height > 12_000_000:
            raise ValueError("3DEP response has unexpected bands or dimensions")
        if dataset.crs is None or dataset.crs.to_epsg() != 5070:
            raise ValueError("3DEP response CRS is not the requested EPSG:5070")
        values = dataset.read(1).astype("float64")
        inside = geometry_mask(
            [mapping(aoi_area)],
            out_shape=values.shape,
            transform=dataset.transform,
            invert=True,
            all_touched=True,
        )
        nodata = dataset.nodata
        valid = np.isfinite(values) & inside
        if nodata is not None:
            valid &= values != nodata
        heights = values[valid]
        if heights.size == 0:
            raise ValueError("3DEP window contains no valid elevation cells")
        q = np.quantile(heights, [0, 0.25, 0.5, 0.75, 1], method="linear")
        cell_x, cell_y = abs(dataset.transform.a), abs(dataset.transform.e)
        # Horn 3x3 derivative; edges and any stencil touching nodata remain unknown.
        slope = _horn_slope(values, valid, cell_x, cell_y, inside)
        slope_q = np.quantile(slope, [0, 0.5, 0.9, 1], method="linear") if slope.size else []
        profile = {
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "width": dataset.width,
            "height": dataset.height,
            "dtype": dataset.dtypes[0],
            "nodata": nodata,
            "cell_size_m": [cell_x, cell_y],
            "valid_pixels": int(heights.size),
            "aoi_cells_touched": int(inside.sum()),
            "nodata_pixels": int((inside & ~valid).sum()),
            "valid_data_fraction_of_aoi_cells": round(float(heights.size / inside.sum()), 6)
            if inside.any()
            else None,
            "aoi_area_sqkm": round(aoi_area.area / 1_000_000, 6),
            "elevation_m": {
                "min": float(q[0]),
                "p25": float(q[1]),
                "median": float(q[2]),
                "p75": float(q[3]),
                "max": float(q[4]),
                "mean": float(heights.mean()),
            },
            "horn_slope_degrees": (
                {
                    "min": float(slope_q[0]),
                    "median": float(slope_q[1]),
                    "p90": float(slope_q[2]),
                    "max": float(slope_q[3]),
                }
                if len(slope_q)
                else None
            ),
        }
    if not profile["crs"]:
        raise ValueError("3DEP response has no CRS")
    partial = profile["nodata_pixels"] > 0
    return ProviderData(
        SourceResult(
            source_id="3dep",
            validation_status=Maturity.VALIDATED,
            validation_scope=MATURITY["3dep"][1],
            coverage_status=Coverage.PARTIAL if partial else Coverage.COMPLETE,
            observation_status=Observation.INCOMPLETE_SOURCE
            if partial
            else Observation.DATA_OBSERVED,
            product_status="3DEP elevation image-service AOI window",
            attempt_status=AttemptStatus.VALIDATED,
            metrics=profile,
            provenance=_acquisition(meta),
            warnings=[
                "Official image-service window requested in EPSG:5070 at 10 m; service resampling recorded as bilinear.",
                "Horn slope uses 3x3 neighbors; nodata/edge stencils excluded.",
            ],
            reason="Nodata exists within returned AOI window" if partial else None,
        ),
        value=profile,
    )


def _horn_slope(
    values: np.ndarray, valid: np.ndarray, dx: float, dy: float, aoi_cells: np.ndarray
) -> np.ndarray:
    if values.shape[0] < 3 or values.shape[1] < 3:
        return np.array([], dtype="float64")
    a = values[:-2, :-2]
    b = values[:-2, 1:-1]
    c = values[:-2, 2:]
    d = values[1:-1, :-2]
    f = values[1:-1, 2:]
    g = values[2:, :-2]
    h = values[2:, 1:-1]
    i = values[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * dx)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * dy)
    stencil_valid = (
        valid[:-2, :-2]
        & valid[:-2, 1:-1]
        & valid[:-2, 2:]
        & valid[1:-1, :-2]
        & valid[1:-1, 1:-1]
        & valid[1:-1, 2:]
        & valid[2:, :-2]
        & valid[2:, 1:-1]
        & valid[2:, 2:]
        & aoi_cells[1:-1, 1:-1]
    )
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy)))[stencil_valid]


def acquire_ssurgo(
    session: Any,
    data_root: Path,
    aoi_4326: Any,
    *,
    acquisition_callback: Callable[[Acquisition], None] | None = None,
) -> ProviderData:
    # SDA's published spatial helper returns map-unit keys; geometry and component tables
    # are joined in one provider-side query so no full survey-area packages are needed.
    wkt = aoi_4326.wkt.replace("'", "''")
    sql = (
        "~DeclareGeometry(@aoi)~ "
        f"SELECT @aoi=geometry::STGeomFromText('{wkt}',4326) "
        "~DeclareIdGeomTable(@clipped)~ "
        "~GetClippedMapunits(@aoi,polygon,geo,@clipped)~ "
        "SELECT mu.mukey, mu.musym, mu.muname, c.cokey, c.comppct_r, c.hydricrating, "
        "c.hydricon, g.geom.STAsText() AS polygon_wkt "
        "FROM @clipped g JOIN mapunit mu ON mu.mukey=g.id "
        "JOIN component c ON c.mukey=mu.mukey WHERE g.geom.STDimension()=2"
    )
    body, meta = fetch_raw(
        session,
        source_id="ssurgo",
        provider="USDA NRCS Soil Data Access",
        release="Current SDA SSURGO tabular and map-unit spatial query",
        url=SSURGO_SDA,
        params=None,
        data_root=data_root,
        terms_url=TERMS["ssurgo"],
        max_bytes=64_000_000,
        form_body={"query": sql, "format": "JSON+COLUMNNAME"},
        media_type="application/json",
        acquisition_callback=acquisition_callback,
    )
    parsed = json.loads(body)
    table = parsed.get("Table") if isinstance(parsed, dict) else None
    if not isinstance(table, list) or not table:
        raise ValueError("SDA response did not contain a non-empty Table")
    columns = [str(v).lower() for v in table[0]]
    needed = {"mukey", "cokey", "comppct_r", "hydricrating", "hydricon"}
    if not needed.issubset(columns):
        raise ValueError(f"SDA response missing required columns: {sorted(needed - set(columns))}")
    rows = [dict(zip(columns, row, strict=True)) for row in table[1:]]
    mapunits = sorted({str(row["mukey"]) for row in rows})
    component_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        percentage = row.get("comppct_r")
        if percentage is not None:
            percentage_number = float(percentage)
            percentage = (
                int(percentage_number) if percentage_number.is_integer() else percentage_number
            )
        component = {
            "mukey": str(row.get("mukey")),
            "cokey": str(row.get("cokey")),
            "comppct_r": percentage,
            "hydricrating": row.get("hydricrating"),
            "hydricon": row.get("hydricon"),
        }
        component_key: tuple[str, str] = (
            str(component["mukey"]),
            str(component["cokey"]),
        )
        previous = component_by_key.get(component_key)
        if previous is not None and previous != component:
            raise ValueError(f"Conflicting SSURGO component values for {component_key}")
        component_by_key[component_key] = component
    ratings: dict[str, dict[str, int]] = {}
    component_indicators = list(component_by_key.values())
    for row in component_indicators:
        label = str(row.get("hydricrating") or "Unranked/NULL")
        ratings[label] = {
            **ratings.get(label, {}),
            "component_count": ratings.get(label, {}).get("component_count", 0) + 1,
        }
    if not rows:
        return ProviderData(
            SourceResult(
                source_id="ssurgo",
                validation_status=Maturity.VALIDATED,
                validation_scope=MATURITY["ssurgo"][1],
                coverage_status=Coverage.UNKNOWN,
                observation_status=Observation.INCOMPLETE_SOURCE,
                product_status="current SSURGO SDA query",
                metrics={},
                provenance=_acquisition(meta),
                reason="Provider returned no intersecting map-unit rows; empty result is not evidence of complete coverage or no hydric soil.",
            ),
        )
    unique_geometries: dict[tuple[str, str], Any] = {}
    geometries = [r for r in rows if r.get("polygon_wkt")]
    if geometries:
        from shapely import wkt as shapely_wkt

        for row in geometries:
            unique_geometries[(str(row["mukey"]), str(row["polygon_wkt"]))] = shapely_wkt.loads(
                str(row["polygon_wkt"])
            )
        source_geoms = list(unique_geometries.values())
        if any(g.is_empty or not g.is_valid for g in source_geoms):
            raise ValueError("SDA returned invalid map-unit polygon geometry")
        if any(g.geom_type not in {"Polygon", "MultiPolygon"} for g in source_geoms):
            raise ValueError("SDA clipped map-unit geometry is not polygonal")
        to_area = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
        aoi_area = transform(to_area, aoi_4326)
        from shapely.ops import unary_union

        clipped = [transform(to_area, g).intersection(aoi_area) for g in source_geoms]
        mapunit_area = unary_union(clipped).area
        coverage_fraction = min(1.0, mapunit_area / aoi_area.area) if aoi_area.area else 0
        source_geometries_by_mukey: dict[str, list[Any]] = {}
        for (mukey, _), geom in unique_geometries.items():
            source_geometries_by_mukey.setdefault(mukey, []).append(geom)
        geometry_by_mukey = {
            mukey: unary_union(parts) for mukey, parts in source_geometries_by_mukey.items()
        }
    else:
        mapunit_area = None
        coverage_fraction = None
        geometry_by_mukey = {}
    mapunit_attributes: dict[str, dict[str, str]] = {}
    for row in rows:
        mapunit_attributes.setdefault(
            str(row["mukey"]),
            {"musym": str(row.get("musym") or ""), "muname": str(row.get("muname") or "")},
        )
    spatial_features = [
        {
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "source_id": "ssurgo",
                "mukey": mukey,
                **mapunit_attributes.get(mukey, {}),
                "interpretation": "soil map-unit polygon; hydric indicators are component-level soil information, not wetlands mapping",
            },
        }
        for mukey, geom in sorted(geometry_by_mukey.items())
        if not geom.is_empty and geom.is_valid and geom.geom_type in {"Polygon", "MultiPolygon"}
    ]
    metrics = {
        "intersecting_mapunit_count": len(mapunits),
        "component_row_count": len(component_indicators),
        "component_hydricrating_counts": dict(sorted(ratings.items())),
        "component_hydric_indicators": component_indicators,
        "mapunit_covered_area_sqkm": round(mapunit_area / 1_000_000, 6)
        if mapunit_area is not None
        else None,
        "aoi_area_sqkm": round(aoi_area.area / 1_000_000, 6) if mapunit_area is not None else None,
        "mapunit_coverage_fraction_of_aoi": round(coverage_fraction, 6)
        if coverage_fraction is not None
        else None,
        "unique_mapunit_polygon_piece_count": len(unique_geometries),
        "mapunit_area_method": "area of union of unique map-unit polygon intersections in EPSG:5070"
        if mapunit_area is not None
        else None,
        "hydric_interpretation": "soil component indicators only; not wetlands mapping or a regulatory determination",
    }
    return ProviderData(
        SourceResult(
            source_id="ssurgo",
            validation_status=Maturity.VALIDATED,
            validation_scope=MATURITY["ssurgo"][1],
            coverage_status=Coverage.COMPLETE
            if coverage_fraction is not None and coverage_fraction >= 0.999
            else Coverage.PARTIAL,
            observation_status=Observation.DATA_OBSERVED
            if coverage_fraction is not None and coverage_fraction >= 0.999
            else Observation.INCOMPLETE_SOURCE,
            product_status="current SSURGO SDA query",
            attempt_status=AttemptStatus.VALIDATED,
            metrics=metrics,
            provenance=_acquisition(meta),
            warnings=["Component hydric ratings are not spatially delineated within map units."],
            reason=None
            if coverage_fraction is not None and coverage_fraction >= 0.999
            else "Returned map-unit polygons do not establish full AOI soil-survey coverage.",
            features=spatial_features,
        ),
        value=rows,
    )


def unavailable(source_id: str, error: Exception) -> SourceResult:
    maturity, scope = MATURITY[source_id]
    return SourceResult(
        source_id=source_id,
        validation_status=maturity,
        validation_scope=scope,
        coverage_status=Coverage.UNAVAILABLE,
        observation_status=Observation.UNAVAILABLE,
        product_status="not available for this screening attempt",
        attempt_status=(
            AttemptStatus.ACCESS_BLOCKED if source_id == "fema_nfhl" else AttemptStatus.FAILED
        ),
        reason=f"{type(error).__name__}: {error}",
    )


def non_operational_sources() -> list[SourceResult]:
    pad_maturity, pad_scope = MATURITY["padus"]
    fema_maturity, fema_scope = MATURITY["fema_nfhl"]
    return [
        SourceResult(
            "padus",
            pad_maturity,
            pad_scope,
            Coverage.UNKNOWN,
            Observation.INCOMPLETE_SOURCE,
            "PAD-US 4.1",
            warnings=[
                "Regional source not acquired by this slice.",
                "The five-feature validation sample had two unchanged accepted features and three repaired candidates quarantined; current AOI impact is unknown.",
            ],
            metrics={
                "prior_validation_sample": {
                    "sample_features": 5,
                    "unchanged_accepted": 2,
                    "repaired_candidates_quarantined": 3,
                    "regional_coverage_verified": False,
                }
            },
            reason="Conditionally validated sample only; full regional coverage unverified.",
        ),
        SourceResult(
            "fema_nfhl",
            fema_maturity,
            fema_scope,
            Coverage.UNAVAILABLE,
            Observation.UNAVAILABLE,
            "NFHL effective/pending products not acquired",
            reason=fema_scope,
        ),
    ]
