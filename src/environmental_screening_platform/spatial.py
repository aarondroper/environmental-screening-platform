"""Optional PostGIS repository for canonical AOI revisions.

SQLite remains the control-plane catalog. This module stores only canonical
spatial records and links them to SQLite-owned snapshots by immutable text IDs.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pyproj import Transformer
from shapely.geometry import MultiPolygon, shape
from shapely.ops import transform, unary_union

MIGRATION_ID = "001_aoi_revisions"
DEFAULT_DATABASE_URL_ENV = "ESGP_POSTGIS_URL"
SOURCE_CRS = "EPSG:4269"
CANONICAL_CRS = "EPSG:4326"
ANALYSIS_CRS = "EPSG:5070"
EXPECTED_COUNTY_GEOIDS = ("08013", "08069", "08123")


class PostGISUnavailable(RuntimeError):
    """The optional PostGIS client or a reachable database is unavailable."""


@dataclass(frozen=True)
class AoiComponent:
    source_feature_id: str
    source_name: str | None
    source_geometry_wkt: str
    geometry_wkt: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class AoiRevisionRecord:
    aoi_id: str
    project_id: str
    aoi_revision: int
    source_snapshot_id: str
    source_version_id: str | None
    geometry_wkt: str
    source_crs: str
    analysis_crs: str
    geometry_status: str
    analysis_area_sqm: float
    provenance: dict[str, Any]
    components: tuple[AoiComponent, ...]


class SpatialRepository(Protocol):
    """Canonical spatial persistence boundary, independent of the control plane."""

    def migrate(self) -> None: ...

    def insert_aoi_revision(self, record: AoiRevisionRecord) -> dict[str, Any]: ...

    def get_aoi_revision(self, aoi_id: str, aoi_revision: int) -> dict[str, Any] | None: ...

    def validate_geometry(self, aoi_id: str, aoi_revision: int) -> dict[str, Any]: ...

    def get_geometry_for_snapshot(
        self, source_snapshot_id: str, source_version_id: str | None = None
    ) -> dict[str, Any] | None: ...


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _geometry_payload(record: AoiRevisionRecord) -> dict[str, Any]:
    return {
        "aoi_id": record.aoi_id,
        "project_id": record.project_id,
        "aoi_revision": record.aoi_revision,
        "source_snapshot_id": record.source_snapshot_id,
        "source_version_id": record.source_version_id,
        "source_crs": record.source_crs,
        "canonical_crs": CANONICAL_CRS,
        "analysis_crs": record.analysis_crs,
        "geometry_status": record.geometry_status,
        "analysis_area_sqm": record.analysis_area_sqm,
        "provenance": record.provenance,
        "components": [component.source_feature_id for component in record.components],
    }


class PostGISRepository:
    """Small psycopg-backed repository; the driver is intentionally optional."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        migration_path: Path | None = None,
    ) -> None:
        self.database_url = database_url or os.environ.get(DEFAULT_DATABASE_URL_ENV)
        if not self.database_url:
            raise ValueError(
                f"Set {DEFAULT_DATABASE_URL_ENV} or pass database_url; credentials are not configured in code"
            )
        self.migration_path = (
            migration_path
            or Path(__file__).resolve().parents[2] / "migrations" / "001_aoi_revisions.sql"
        )

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on optional environment
            raise PostGISUnavailable(
                "psycopg is not installed; install the optional postgis dependency"
            ) from exc
        try:
            return psycopg.connect(self.database_url)
        except Exception as exc:  # pragma: no cover - depends on optional service
            raise PostGISUnavailable(f"PostGIS connection failed: {exc}") from exc

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            with connection.transaction():
                yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        sql = self.migration_path.read_text(encoding="utf-8")
        with self._transaction() as connection:
            connection.execute(sql)

    def insert_aoi_revision(self, record: AoiRevisionRecord) -> dict[str, Any]:
        if not record.components:
            raise ValueError("An AOI revision requires at least one preserved source component")
        if record.geometry_status != "valid":
            raise ValueError("Only valid AOI revisions may enter the canonical repository")
        if record.source_crs != SOURCE_CRS or record.analysis_crs != ANALYSIS_CRS:
            raise ValueError(
                "This boundary loader expects EPSG:4269 source and EPSG:5070 analysis CRS"
            )
        payload = _geometry_payload(record)
        with self._transaction() as connection:
            existing = connection.execute(
                """SELECT project_id,source_snapshot_id,source_version_id,geometry_status,
                          ST_AsText(geometry) AS geometry_wkt
                   FROM screening.aoi_revisions
                   WHERE aoi_id=%s AND aoi_revision=%s""",
                (record.aoi_id, record.aoi_revision),
            ).fetchone()
            if existing is not None:
                if (
                    existing[0] != record.project_id
                    or existing[1] != record.source_snapshot_id
                    or existing[2] != record.source_version_id
                    or existing[3] != record.geometry_status
                ):
                    raise ValueError(
                        "AOI revision identity conflicts with an existing canonical record"
                    )
                return self.get_aoi_revision(record.aoi_id, record.aoi_revision) or payload

            connection.execute(
                """INSERT INTO screening.aoi_revisions
                   (aoi_id,project_id,aoi_revision,source_snapshot_id,source_version_id,geometry,
                    source_crs,analysis_crs,geometry_status,analysis_area_sqm,provenance)
                   VALUES (%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326),%s,%s,%s,%s,%s::jsonb)""",
                (
                    record.aoi_id,
                    record.project_id,
                    record.aoi_revision,
                    record.source_snapshot_id,
                    record.source_version_id,
                    record.geometry_wkt,
                    record.source_crs,
                    record.analysis_crs,
                    record.geometry_status,
                    record.analysis_area_sqm,
                    _json(record.provenance),
                ),
            )
            for index, component in enumerate(record.components):
                connection.execute(
                    """INSERT INTO screening.aoi_revision_components
                       (aoi_id,aoi_revision,component_index,source_feature_id,source_name,
                        source_geometry,geometry,source_crs,geometry_status,provenance)
                       VALUES (%s,%s,%s,%s,%s,ST_GeomFromText(%s,4269),
                               ST_GeomFromText(%s,4326),%s,'valid',%s::jsonb)""",
                    (
                        record.aoi_id,
                        record.aoi_revision,
                        index,
                        component.source_feature_id,
                        component.source_name,
                        component.source_geometry_wkt,
                        component.geometry_wkt,
                        record.source_crs,
                        _json(component.provenance),
                    ),
                )
        return self.get_aoi_revision(record.aoi_id, record.aoi_revision) or payload

    def get_aoi_revision(self, aoi_id: str, aoi_revision: int) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT aoi_id,project_id,aoi_revision,source_snapshot_id,source_version_id,
                          ST_AsGeoJSON(geometry)::jsonb AS geometry,source_crs,analysis_crs,
                          geometry_status,analysis_area_sqm,provenance,created_at::text
                   FROM screening.aoi_revisions WHERE aoi_id=%s AND aoi_revision=%s""",
                (aoi_id, aoi_revision),
            ).fetchone()
            if row is None:
                return None
            result = dict(
                zip(
                    (
                        "aoi_id",
                        "project_id",
                        "aoi_revision",
                        "source_snapshot_id",
                        "source_version_id",
                        "geometry",
                        "source_crs",
                        "analysis_crs",
                        "geometry_status",
                        "analysis_area_sqm",
                        "provenance",
                        "created_at",
                    ),
                    row,
                    strict=True,
                )
            )
            components = connection.execute(
                """SELECT component_index,source_feature_id,source_name,
                          ST_AsGeoJSON(geometry)::jsonb AS geometry,
                          ST_AsText(source_geometry) AS source_geometry_wkt,source_crs,
                          geometry_status,provenance
                   FROM screening.aoi_revision_components
                   WHERE aoi_id=%s AND aoi_revision=%s ORDER BY component_index""",
                (aoi_id, aoi_revision),
            ).fetchall()
            result["components"] = [
                dict(
                    zip(
                        (
                            "component_index",
                            "source_feature_id",
                            "source_name",
                            "geometry",
                            "source_geometry_wkt",
                            "source_crs",
                            "geometry_status",
                            "provenance",
                        ),
                        component,
                        strict=True,
                    )
                )
                for component in components
            ]
            return result

    def validate_geometry(self, aoi_id: str, aoi_revision: int) -> dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT ST_IsEmpty(geometry),ST_IsValid(geometry),ST_IsValidReason(geometry),
                          ST_GeometryType(geometry),ST_SRID(geometry),ST_NumGeometries(geometry),
                          ST_Area(ST_Transform(geometry,5070))
                   FROM screening.aoi_revisions WHERE aoi_id=%s AND aoi_revision=%s""",
                (aoi_id, aoi_revision),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown AOI revision: {aoi_id}/{aoi_revision}")
        return {
            "empty": row[0],
            "valid": row[1],
            "validity_reason": row[2],
            "geometry_type": row[3],
            "srid": row[4],
            "component_count": row[5],
            "analysis_area_sqm": row[6],
        }

    def get_geometry_for_snapshot(
        self, source_snapshot_id: str, source_version_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            if source_version_id is None:
                row = connection.execute(
                    """SELECT aoi_id,aoi_revision,project_id,source_snapshot_id,source_version_id,
                              ST_AsGeoJSON(geometry)::jsonb AS geometry,geometry_status
                       FROM screening.aoi_revisions WHERE source_snapshot_id=%s
                       ORDER BY created_at DESC LIMIT 1""",
                    (source_snapshot_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT aoi_id,aoi_revision,project_id,source_snapshot_id,source_version_id,
                              ST_AsGeoJSON(geometry)::jsonb AS geometry,geometry_status
                       FROM screening.aoi_revisions
                       WHERE source_snapshot_id=%s AND source_version_id=%s
                       ORDER BY created_at DESC LIMIT 1""",
                    (source_snapshot_id, source_version_id),
                ).fetchone()
        if row is None:
            return None
        return dict(
            zip(
                (
                    "aoi_id",
                    "aoi_revision",
                    "project_id",
                    "source_snapshot_id",
                    "source_version_id",
                    "geometry",
                    "geometry_status",
                ),
                row,
                strict=True,
            )
        )


def census_boundary_record(
    boundary_path: Path,
    *,
    project_id: str,
    aoi_id: str,
    aoi_revision: int,
    source_snapshot_id: str,
    source_version_id: str | None,
) -> AoiRevisionRecord:
    """Build a canonical AOI record from the validated three-county GeoJSON artifact."""
    payload = json.loads(boundary_path.read_text(encoding="utf-8"))
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("Boundary artifact must be a GeoJSON FeatureCollection")
    crs = payload.get("crs", {})
    crs_name: str | None
    if isinstance(crs, str):
        crs_name = crs
    else:
        crs_name = crs.get("properties", {}).get("name") if isinstance(crs, dict) else None
    if crs_name != SOURCE_CRS:
        raise ValueError(f"Boundary artifact CRS must be {SOURCE_CRS}")
    by_geoid = {str(feature.get("properties", {}).get("GEOID")): feature for feature in features}
    if tuple(sorted(by_geoid)) != EXPECTED_COUNTY_GEOIDS or len(features) != 3:
        raise ValueError("Boundary artifact must contain exactly the approved three county GEOIDs")
    canonical_geometries = []
    components: list[AoiComponent] = []
    to_canonical = Transformer.from_crs(SOURCE_CRS, CANONICAL_CRS, always_xy=True).transform
    for geoid in EXPECTED_COUNTY_GEOIDS:
        feature = by_geoid[geoid]
        source_geometry = shape(feature["geometry"])
        if source_geometry.is_empty or not source_geometry.is_valid:
            raise ValueError(f"County {geoid} is empty or invalid")
        if source_geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"County {geoid} is not polygonal")
        canonical_geometry = transform(to_canonical, source_geometry)
        source_multi = (
            MultiPolygon([source_geometry])
            if source_geometry.geom_type == "Polygon"
            else source_geometry
        )
        canonical_multi = (
            MultiPolygon([canonical_geometry])
            if canonical_geometry.geom_type == "Polygon"
            else canonical_geometry
        )
        canonical_geometries.append(canonical_multi)
        components.append(
            AoiComponent(
                source_feature_id=geoid,
                source_name=feature.get("properties", {}).get("NAME"),
                source_geometry_wkt=source_multi.wkt,
                geometry_wkt=canonical_multi.wkt,
                provenance={"source_geoid": geoid, "source_vintage": "2025"},
            )
        )
    union = unary_union(canonical_geometries)
    if union.is_empty or not union.is_valid or union.geom_type != "MultiPolygon":
        raise ValueError("Approved county union must remain a valid MultiPolygon")
    to_analysis = Transformer.from_crs(CANONICAL_CRS, ANALYSIS_CRS, always_xy=True).transform
    analysis_area_sqm = transform(to_analysis, union).area
    return AoiRevisionRecord(
        aoi_id=aoi_id,
        project_id=project_id,
        aoi_revision=aoi_revision,
        source_snapshot_id=source_snapshot_id,
        source_version_id=source_version_id,
        geometry_wkt=union.wkt,
        source_crs=SOURCE_CRS,
        analysis_crs=ANALYSIS_CRS,
        geometry_status="valid",
        analysis_area_sqm=analysis_area_sqm,
        provenance={
            "source_artifact": str(boundary_path),
            "source_feature_geoids": list(EXPECTED_COUNTY_GEOIDS),
            "source_vintage": "2025",
            "normalization": "source geometries preserved in components; transformed from EPSG:4269 to EPSG:4326 for canonical geometry; area measured in EPSG:5070",
        },
        components=tuple(components),
    )
