"""AOI context and validation policies.

Generic AOIs are valid WGS84 Polygon/MultiPolygon geometries.  A named
boundary policy can add containment rules for regression or demonstration
fixtures without making that boundary a platform-wide prerequisite.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from pyproj import Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from .regression_fixtures import NORTHERN_COLORADO_REGRESSION_FIXTURE

GENERIC_AOI_POLICY = "generic"
NORTHERN_COLORADO_REGRESSION_POLICY = "northern_colorado_regression"


@dataclass(frozen=True)
class AoiValidationPolicy:
    """Validation rules applied to one AOI input boundary."""

    policy_id: str
    description: str
    boundary_required: bool = False

    def validate(
        self,
        geometry: BaseGeometry,
        *,
        boundary_geometry: BaseGeometry | None = None,
    ) -> dict[str, Any]:
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("AOI must be a nonempty Polygon or MultiPolygon")
        if not geometry.is_valid:
            raise ValueError("AOI geometry is invalid; no repair is performed")
        if geometry.has_z:
            raise ValueError("AOI must contain two-dimensional WGS84 coordinates")
        if not all(math.isfinite(value) for value in geometry.bounds):
            raise ValueError("AOI coordinates must be finite WGS84 longitude/latitude values")
        if self.boundary_required:
            if boundary_geometry is None:
                raise ValueError(f"AOI validation policy {self.policy_id} requires a boundary")
            if not boundary_geometry.covers(geometry):
                raise ValueError(
                    "AOI is not fully contained by the complete approved three-county boundary"
                )
        to_area = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
        area_sqm = transform(to_area, geometry).area
        return {
            "crs": "EPSG:4326",
            "area_crs": "EPSG:5070",
            "area_sqkm": round(area_sqm / 1_000_000, 6),
            "bounds": list(geometry.bounds),
            "validation_policy": self.policy_id,
            "validation_policy_description": self.description,
        }


@dataclass(frozen=True)
class AoiContext:
    """Immutable identity and geometry context passed across workflow seams."""

    project_id: str
    aoi_id: str
    revision: int
    geometry: BaseGeometry
    input_sha256: str
    spatial_validation: dict[str, Any]
    validation_policy: str

    @classmethod
    def from_revision(cls, revision: dict[str, Any]) -> AoiContext:
        from shapely.geometry import shape

        geometry = shape(revision["geometry"])
        geometry_sha256 = hashlib.sha256(geometry.wkb).hexdigest()
        declared_geometry_sha256 = revision.get("geometry_sha256")
        if declared_geometry_sha256 and declared_geometry_sha256 != geometry_sha256:
            raise ValueError("AOI revision geometry hash does not match its geometry")
        return cls(
            project_id=str(revision["project_id"]),
            aoi_id=str(revision["aoi_id"]),
            revision=int(revision["revision"]),
            geometry=geometry,
            input_sha256=str(revision["input_sha256"]),
            spatial_validation=dict(revision["spatial_validation"]),
            validation_policy=str(revision.get("validation_policy", GENERIC_AOI_POLICY)),
        )

    @staticmethod
    def hash_input(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @property
    def geometry_sha256(self) -> str:
        """Stable hash of the canonical geometry carried by this revision."""
        return hashlib.sha256(self.geometry.wkb).hexdigest()


def generic_aoi_policy() -> AoiValidationPolicy:
    return AoiValidationPolicy(
        policy_id=GENERIC_AOI_POLICY,
        description="Valid WGS84 Polygon or MultiPolygon; no project-wide containment boundary",
    )


def northern_colorado_regression_policy() -> AoiValidationPolicy:
    return AoiValidationPolicy(
        policy_id=NORTHERN_COLORADO_REGRESSION_POLICY,
        description=(
            "Northern Colorado 2025 regression/demo boundary: Boulder, Larimer, and Weld counties"
        ),
        boundary_required=True,
    )


def policy_by_id(policy_id: str | None) -> AoiValidationPolicy:
    if policy_id in {None, GENERIC_AOI_POLICY}:
        return generic_aoi_policy()
    if policy_id == NORTHERN_COLORADO_REGRESSION_POLICY:
        return northern_colorado_regression_policy()
    raise ValueError(f"Unknown AOI validation policy: {policy_id}")


def northern_colorado_fixture_metadata() -> dict[str, Any]:
    fixture = NORTHERN_COLORADO_REGRESSION_FIXTURE
    return {
        "fixture_id": fixture.fixture_id,
        "aoi_id": fixture.aoi_id,
        "geoids": list(fixture.county_geoids),
        "vintage": fixture.vintage,
        "policy": NORTHERN_COLORADO_REGRESSION_POLICY,
    }
