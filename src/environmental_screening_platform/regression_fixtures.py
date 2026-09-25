"""Explicit Northern Colorado regression/demo configuration.

The values in this module describe the known-good validation fixture.  They
are not defaults for arbitrary projects or a universal source configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RasterExpectation:
    release: str
    crs: str
    resolution_m: float
    nodata: int | float
    max_cells: int


@dataclass(frozen=True)
class NorthernColoradoRegressionFixture:
    fixture_id: str
    aoi_id: str
    vintage: int
    county_names_by_geoid: tuple[tuple[str, str], ...]
    boundary_cache_relative_path: Path
    canonical_boundary_relative_path: Path
    ssurgo_sizing_record_relative_path: Path
    ssurgo_expected_package_count: int
    nlcd: RasterExpectation
    dep: RasterExpectation

    @property
    def county_geoids(self) -> tuple[str, ...]:
        return tuple(geoid for geoid, _ in self.county_names_by_geoid)

    @property
    def county_names(self) -> dict[str, str]:
        return dict(self.county_names_by_geoid)


NORTHERN_COLORADO_REGRESSION_FIXTURE = NorthernColoradoRegressionFixture(
    fixture_id="northern-colorado-front-range-2025",
    aoi_id="northern-colorado-front-range",
    vintage=2025,
    county_names_by_geoid=(
        ("08013", "Boulder"),
        ("08069", "Larimer"),
        ("08123", "Weld"),
    ),
    boundary_cache_relative_path=Path("workspace/reference/approved_counties.geojson"),
    canonical_boundary_relative_path=Path("geography/canonical/counties_2025.shp"),
    ssurgo_sizing_record_relative_path=Path("ssurgo/ssurgo_regional_sizing_2026-09-24.json"),
    ssurgo_expected_package_count=19,
    nlcd=RasterExpectation(
        release="Annual NLCD Collection 1.2, 2025 land cover",
        crs="EPSG:5070",
        resolution_m=30.0,
        nodata=250,
        max_cells=50_000_000,
    ),
    dep=RasterExpectation(
        release="USGS 3DEP 1/3 arc-second representative fixture",
        crs="EPSG:5070",
        resolution_m=10.0,
        nodata=-999999.0,
        max_cells=16_000_000,
    ),
)


NORTHERN_COLORADO_GEOIDS = frozenset(NORTHERN_COLORADO_REGRESSION_FIXTURE.county_geoids)
