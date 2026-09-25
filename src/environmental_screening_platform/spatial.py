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
from shapely import wkt
from shapely.geometry import MultiPolygon, shape
from shapely.ops import transform, unary_union

from .regression_fixtures import NORTHERN_COLORADO_REGRESSION_FIXTURE
from .ssurgo import SsurgoBatchRecord
from .ssurgo_regional_staging import RegionalPackageStagingRecord

MIGRATION_ID = "001_aoi_revisions"
SSURGO_MIGRATION_ID = "002_ssurgo_mapunits"
SSURGO_REGIONAL_STAGING_MIGRATION_ID = "003_ssurgo_regional_staging"
DEFAULT_DATABASE_URL_ENV = "ESGP_POSTGIS_URL"
SOURCE_CRS = "EPSG:4269"
CANONICAL_CRS = "EPSG:4326"
ANALYSIS_CRS = "EPSG:5070"
EXPECTED_COUNTY_GEOIDS = NORTHERN_COLORADO_REGRESSION_FIXTURE.county_geoids


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

    def screen_ssurgo_snapshot(
        self, source_snapshot_id: str, source_version_id: str, aoi_geometry_wkt: str
    ) -> dict[str, Any]: ...

    def stage_ssurgo_regional_package(
        self, package: RegionalPackageStagingRecord
    ) -> dict[str, Any]: ...

    def analyze_ssurgo_regional_coverage(
        self, batch_ids: list[str], aoi_id: str, aoi_revision: int
    ) -> dict[str, Any]: ...


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
        self.migration_path = migration_path
        self.migrations_directory = Path(__file__).resolve().parents[2] / "migrations"

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on optional environment
            raise PostGISUnavailable(
                "psycopg is not installed; install the optional postgis dependency"
            ) from exc
        database_url = self.database_url
        if database_url is None:  # pragma: no cover - constructor validates this
            raise PostGISUnavailable("PostGIS connection URL is not configured")
        try:
            return psycopg.connect(database_url)
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
        migration_paths = (
            [self.migration_path]
            if self.migration_path is not None
            else sorted(self.migrations_directory.glob("*.sql"))
        )
        with self._transaction() as connection:
            for migration_path in migration_paths:
                connection.execute(migration_path.read_text(encoding="utf-8"))

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

    def stage_ssurgo_batch(self, batch: SsurgoBatchRecord) -> dict[str, Any]:
        """Insert one SSURGO candidate into staging, preserving it before QA."""
        if not batch.map_units:
            raise ValueError("An SSURGO batch requires at least one map unit")
        if batch.source_crs != "EPSG:4326" or batch.canonical_crs != "EPSG:4326":
            raise ValueError("This SSURGO slice expects EPSG:4326 source and canonical geometry")
        if batch.analysis_crs != ANALYSIS_CRS:
            raise ValueError("This SSURGO slice expects EPSG:5070 analysis geometry")
        with self._transaction() as connection:
            existing = connection.execute(
                """SELECT batch_id,artifact_sha256,artifact_size_bytes
                   FROM screening.ssurgo_ingestion_batches
                   WHERE source_snapshot_id=%s AND source_version_id=%s""",
                (batch.source_snapshot_id, batch.source_version_id),
            ).fetchone()
            if existing is not None:
                if existing[0] != batch.batch_id:
                    raise ValueError(
                        "SSURGO source snapshot/version is already staged under another batch"
                    )
                if existing[1] != batch.artifact_sha256 or existing[2] != batch.artifact_size_bytes:
                    raise ValueError(
                        "SSURGO artifact checksum or size conflicts with the staged source version"
                    )
                return self.get_ssurgo_batch(batch.batch_id) or {"batch_id": batch.batch_id}
            connection.execute(
                """INSERT INTO screening.ssurgo_ingestion_batches
                   (batch_id,source_id,source_snapshot_id,source_version_id,ingestion_run_id,
                    candidate_id,source_url,provider_release,retrieved_at,terms_url,artifact_path,
                    artifact_sha256,artifact_size_bytes,source_crs,canonical_crs,analysis_crs,
                    validation_status,coverage_status,observation_status,promotion_status,
                    validation_json,provenance)
                   VALUES (%s,'ssurgo',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           'incomplete',%s,%s,'staged','{}'::jsonb,%s::jsonb)""",
                (
                    batch.batch_id,
                    batch.source_snapshot_id,
                    batch.source_version_id,
                    batch.ingestion_run_id,
                    batch.candidate_id,
                    batch.source_url,
                    batch.provider_release,
                    batch.retrieved_at,
                    batch.terms_url,
                    batch.artifact_path,
                    batch.artifact_sha256,
                    batch.artifact_size_bytes,
                    batch.source_crs,
                    batch.canonical_crs,
                    batch.analysis_crs,
                    batch.coverage_status,
                    batch.observation_status,
                    _json(batch.provenance),
                ),
            )
            for map_unit in batch.map_units:
                for component in map_unit.components:
                    if component.mukey != map_unit.mukey:
                        raise ValueError("SSURGO component does not join its map unit")
                connection.execute(
                    """INSERT INTO screening.ssurgo_map_units_staging
                       (batch_id,mukey,areasymbol,areaname,musym,muname,source_snapshot_id,
                        source_version_id,source_crs,canonical_crs,analysis_crs,source_geometry,
                        geometry,geometry_status,analysis_area_sqm,source_geometry_piece_count,
                        provenance)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               ST_GeomFromText(%s,4326),ST_GeomFromText(%s,4326),%s,%s,%s,%s::jsonb)""",
                    (
                        batch.batch_id,
                        map_unit.mukey,
                        map_unit.areasymbol,
                        map_unit.areaname,
                        map_unit.musym,
                        map_unit.muname,
                        batch.source_snapshot_id,
                        batch.source_version_id,
                        batch.source_crs,
                        batch.canonical_crs,
                        batch.analysis_crs,
                        map_unit.geometry_wkt,
                        map_unit.geometry_wkt,
                        map_unit.geometry_status,
                        map_unit.analysis_area_sqm,
                        map_unit.source_geometry_piece_count,
                        _json(map_unit.provenance),
                    ),
                )
                for component in map_unit.components:
                    connection.execute(
                        """INSERT INTO screening.ssurgo_components_staging
                           (batch_id,mukey,cokey,source_snapshot_id,source_version_id,
                            comppct_r,hydricrating,hydricon,provenance)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                        (
                            batch.batch_id,
                            component.mukey,
                            component.cokey,
                            batch.source_snapshot_id,
                            batch.source_version_id,
                            component.comppct_r,
                            component.hydricrating,
                            component.hydricon,
                            _json(component.provenance),
                        ),
                    )
        return self.get_ssurgo_batch(batch.batch_id) or {"batch_id": batch.batch_id}

    def stage_ssurgo_regional_package(
        self, package: RegionalPackageStagingRecord
    ) -> dict[str, Any]:
        """Stage one acquired regional package in one idempotent transaction.

        The staging tables retain both original and derived geometries.  This
        method has no production-promotion path and uses only explicit source
        package/version identifiers supplied by the caller.
        """
        if not package.map_units or not package.features:
            raise ValueError("A regional SSURGO package must contain map units and features")
        mapunit_ids = {item.mukey for item in package.map_units}
        feature_ids = [item.stable_feature_id for item in package.features]
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("Regional SSURGO features must have unique stable identifiers")
        if any(item.mukey not in mapunit_ids for item in package.features):
            raise ValueError("Regional SSURGO feature references an unknown map unit")
        expected_quarantine = sum(
            item.geometry_status == "quarantined" for item in package.features
        )
        if expected_quarantine != package.quarantine_count:
            raise ValueError("Regional SSURGO quarantine count does not match feature statuses")
        if package.source_crs != CANONICAL_CRS or package.analysis_crs != ANALYSIS_CRS:
            raise ValueError(
                "Regional SSURGO staging expects EPSG:4326 source and EPSG:5070 analysis CRS"
            )
        with self._transaction() as connection:
            existing = connection.execute(
                """SELECT batch_id,artifact_sha256,artifact_size_bytes
                   FROM screening.ssurgo_regional_staging_batches
                   WHERE source_snapshot_id=%s AND source_version_id=%s""",
                (package.source_snapshot_id, package.source_version_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing[0] != package.batch_id
                    or existing[1] != package.artifact_sha256
                    or existing[2] != package.artifact_size_bytes
                ):
                    raise ValueError(
                        "Regional SSURGO source version is already staged with conflicting provenance"
                    )
                connection.execute(
                    """UPDATE screening.ssurgo_regional_staging_batches
                       SET package_name=%s WHERE batch_id=%s AND package_name IS DISTINCT FROM %s""",
                    (package.areaname, package.batch_id, package.areaname),
                )
                connection.execute(
                    """UPDATE screening.ssurgo_regional_map_units_staging
                       SET areaname=%s WHERE batch_id=%s AND areaname IS DISTINCT FROM %s""",
                    (package.areaname, package.batch_id, package.areaname),
                )
                result = self.get_ssurgo_regional_staging_batch(package.batch_id) or {}
                result["idempotent"] = True
                return result

            feature_count = len(package.features)
            map_unit_count = len(package.map_units)
            component_count = sum(len(item.components) for item in package.map_units)
            connection.execute(
                """INSERT INTO screening.ssurgo_regional_staging_batches
                   (batch_id,source_id,package_areasymbol,package_name,
                    provider_package_identifier,source_snapshot_id,source_version_id,
                    ingestion_run_id,candidate_id,source_url,provider_release,retrieved_at,
                    artifact_path,artifact_sha256,artifact_size_bytes,terms_url,source_crs,
                    analysis_crs,validation_status,coverage_status,staging_status,
                    promotion_status,feature_count,map_unit_count,component_count,
                    original_invalid_count,repaired_accepted_count,quarantined_count,provenance)
                   VALUES (%s,'ssurgo',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,'staging_only',%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (
                    package.batch_id,
                    package.areasymbol,
                    package.areaname,
                    package.provider_package_identifier,
                    package.source_snapshot_id,
                    package.source_version_id,
                    package.ingestion_run_id,
                    package.candidate_id,
                    package.source_url,
                    package.provider_release,
                    package.retrieved_at,
                    package.artifact_path,
                    package.artifact_sha256,
                    package.artifact_size_bytes,
                    package.terms_url,
                    package.source_crs,
                    package.analysis_crs,
                    package.validation_status,
                    package.coverage_status,
                    package.staging_status,
                    feature_count,
                    map_unit_count,
                    component_count,
                    sum(not item.original_valid for item in package.features),
                    sum(item.geometry_status == "repaired_accepted" for item in package.features),
                    package.quarantine_count,
                    _json(package.provenance),
                ),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO screening.ssurgo_regional_map_units_staging
                       (batch_id,mukey,musym,muname,areasymbol,areaname,source_attributes,provenance)
                       VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    [
                        (
                            package.batch_id,
                            item.mukey,
                            item.musym,
                            item.muname,
                            item.areasymbol,
                            item.areaname,
                            _json(item.source_attributes),
                            _json({"source_version_id": package.source_version_id}),
                        )
                        for item in package.map_units
                    ],
                )
                cursor.executemany(
                    """INSERT INTO screening.ssurgo_regional_components_staging
                       (batch_id,mukey,cokey,comppct_r,hydricrating,hydricon,source_attributes,provenance)
                       VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    [
                        (
                            package.batch_id,
                            component.mukey,
                            component.cokey,
                            component.comppct_r,
                            component.hydricrating,
                            component.hydricon,
                            _json(component.source_attributes),
                            _json({"source_version_id": package.source_version_id}),
                        )
                        for map_unit in package.map_units
                        for component in map_unit.components
                    ],
                )
                cursor.executemany(
                    """INSERT INTO screening.ssurgo_regional_features_staging
                   (batch_id,stable_feature_id,source_record_index,mukey,source_geometry,
                    derived_geometry,original_valid,original_validity_reason,original_geometry_type,
                    original_component_count,original_ring_count,original_empty,
                    original_area_epsg5070_m2,derived_valid,derived_geometry_type,
                    derived_component_count,derived_ring_count,derived_empty,
                    derived_area_epsg5070_m2,area_delta_percentage,repair_operation,
                    geometry_status,attributes_joinable,source_attributes,audited_diagnostic,provenance)
                   VALUES (%s,%s,%s,%s,ST_GeomFromWKB(%s,4326),ST_GeomFromWKB(%s,4326),
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s::jsonb,%s::jsonb,%s::jsonb)""",
                    [
                        (
                            package.batch_id,
                            feature.stable_feature_id,
                            feature.source_record_index,
                            feature.mukey,
                            wkt.loads(feature.source_geometry_wkt).wkb,
                            wkt.loads(feature.derived_geometry_wkt).wkb,
                            feature.original_valid,
                            feature.original_validity_reason,
                            feature.original_geometry_type,
                            feature.original_component_count,
                            feature.original_ring_count,
                            feature.original_empty,
                            feature.original_area_epsg5070_m2,
                            feature.derived_valid,
                            feature.derived_geometry_type,
                            feature.derived_component_count,
                            feature.derived_ring_count,
                            feature.derived_empty,
                            feature.derived_area_epsg5070_m2,
                            feature.area_delta_percentage,
                            feature.repair_operation,
                            feature.geometry_status,
                            feature.attributes_joinable,
                            _json(feature.source_attributes),
                            _json(feature.audited_diagnostic)
                            if feature.audited_diagnostic
                            else None,
                            _json(
                                {
                                    "source_snapshot_id": package.source_snapshot_id,
                                    "source_version_id": package.source_version_id,
                                    "candidate_id": package.candidate_id,
                                    "ingestion_run_id": package.ingestion_run_id,
                                }
                            ),
                        )
                        for feature in package.features
                    ],
                )
            counts = connection.execute(
                """SELECT
                   (SELECT count(*) FROM screening.ssurgo_regional_map_units_staging WHERE batch_id=%s),
                   (SELECT count(*) FROM screening.ssurgo_regional_components_staging WHERE batch_id=%s),
                   (SELECT count(*) FROM screening.ssurgo_regional_features_staging WHERE batch_id=%s)""",
                (package.batch_id, package.batch_id, package.batch_id),
            ).fetchone()
            if counts != (map_unit_count, component_count, feature_count):
                raise RuntimeError("Regional SSURGO staging count reconciliation failed")
        return self.get_ssurgo_regional_staging_batch(package.batch_id) or {
            "batch_id": package.batch_id
        }

    def get_ssurgo_regional_staging_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT batch_id,source_id,package_areasymbol,package_name,
                          source_snapshot_id,source_version_id,ingestion_run_id,candidate_id,
                          artifact_path,artifact_sha256,artifact_size_bytes,validation_status,
                          coverage_status,staging_status,promotion_status,feature_count,
                          map_unit_count,component_count,original_invalid_count,
                          repaired_accepted_count,quarantined_count,provenance,created_at::text,
                          (SELECT count(*) FROM screening.ssurgo_regional_features_staging f
                           WHERE f.batch_id=b.batch_id AND f.geometry_status='quarantined')
                       FROM screening.ssurgo_regional_staging_batches b WHERE batch_id=%s""",
                (batch_id,),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "batch_id",
            "source_id",
            "package_areasymbol",
            "package_name",
            "source_snapshot_id",
            "source_version_id",
            "ingestion_run_id",
            "candidate_id",
            "artifact_path",
            "artifact_sha256",
            "artifact_size_bytes",
            "validation_status",
            "coverage_status",
            "staging_status",
            "promotion_status",
            "feature_count",
            "map_unit_count",
            "component_count",
            "original_invalid_count",
            "repaired_accepted_count",
            "quarantined_count",
            "provenance",
            "created_at",
            "quarantined_feature_count",
        )
        return dict(zip(keys, row, strict=True))

    def get_ssurgo_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT b.batch_id,b.source_id,b.source_snapshot_id,b.source_version_id,
                          b.ingestion_run_id,b.candidate_id,b.source_url,b.provider_release,
                          b.retrieved_at::text,b.terms_url,b.artifact_path,b.artifact_sha256,
                          b.artifact_size_bytes,b.source_crs,b.canonical_crs,b.analysis_crs,
                          b.validation_status,b.coverage_status,b.observation_status,
                          b.promotion_status,b.validation_json,b.provenance,b.error_json,
                          b.created_at::text,b.validated_at::text,b.promoted_at::text,
                          (SELECT count(*) FROM screening.ssurgo_map_units_staging s
                           WHERE s.batch_id=b.batch_id) AS staging_map_unit_count,
                          (SELECT count(*) FROM screening.ssurgo_components_staging s
                           WHERE s.batch_id=b.batch_id) AS staging_component_count,
                          (SELECT count(*) FROM screening.ssurgo_map_units c
                           WHERE c.batch_id=b.batch_id) AS canonical_map_unit_count,
                          (SELECT count(*) FROM screening.ssurgo_components c
                           WHERE c.batch_id=b.batch_id) AS canonical_component_count
                   FROM screening.ssurgo_ingestion_batches b
                   WHERE b.batch_id=%s""",
                (batch_id,),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "batch_id",
            "source_id",
            "source_snapshot_id",
            "source_version_id",
            "ingestion_run_id",
            "candidate_id",
            "source_url",
            "provider_release",
            "retrieved_at",
            "terms_url",
            "artifact_path",
            "artifact_sha256",
            "artifact_size_bytes",
            "source_crs",
            "canonical_crs",
            "analysis_crs",
            "validation_status",
            "coverage_status",
            "observation_status",
            "promotion_status",
            "validation_json",
            "provenance",
            "error_json",
            "created_at",
            "validated_at",
            "promoted_at",
            "staging_map_unit_count",
            "staging_component_count",
            "canonical_map_unit_count",
            "canonical_component_count",
        )
        return dict(zip(keys, row, strict=True))

    def validate_ssurgo_batch(self, batch_id: str) -> dict[str, Any]:
        """Run database-side SSURGO QA and retain either success or failure."""
        try:
            with self._transaction() as connection:
                batch = connection.execute(
                    """SELECT source_snapshot_id,source_version_id,source_crs,canonical_crs,
                              analysis_crs,promotion_status
                       FROM screening.ssurgo_ingestion_batches WHERE batch_id=%s FOR UPDATE""",
                    (batch_id,),
                ).fetchone()
                if batch is None:
                    raise KeyError(f"Unknown SSURGO batch: {batch_id}")
                map_stats = connection.execute(
                    """SELECT count(*)::int,
                              count(*) FILTER (WHERE geometry_status <> 'valid'
                                  OR ST_IsEmpty(source_geometry) OR NOT ST_IsValid(source_geometry)
                                  OR ST_IsEmpty(geometry) OR NOT ST_IsValid(geometry)
                                  OR ST_GeometryType(source_geometry) <> 'ST_MultiPolygon'
                                  OR ST_GeometryType(geometry) <> 'ST_MultiPolygon'
                                  OR analysis_area_sqm IS NULL OR analysis_area_sqm <= 0)::int,
                              count(*) FILTER (WHERE source_snapshot_id <> %s
                                  OR source_version_id <> %s OR source_crs <> %s
                                  OR canonical_crs <> %s OR analysis_crs <> %s)::int,
                              count(*) FILTER (WHERE mukey = '' OR musym = '' OR muname = '')::int
                       FROM screening.ssurgo_map_units_staging WHERE batch_id=%s""",
                    (batch[0], batch[1], batch[2], batch[3], batch[4], batch_id),
                ).fetchone()
                component_stats = connection.execute(
                    """SELECT count(*)::int,
                              count(*) FILTER (WHERE c.source_snapshot_id <> %s
                                  OR c.source_version_id <> %s)::int,
                              count(*) FILTER (WHERE c.mukey = '' OR c.cokey = '')::int,
                              count(*) FILTER (WHERE c.comppct_r IS NOT NULL
                                  AND (c.comppct_r < 0 OR c.comppct_r > 100))::int,
                              count(*) FILTER (WHERE m.mukey IS NULL)::int
                       FROM screening.ssurgo_components_staging c
                       LEFT JOIN screening.ssurgo_map_units_staging m
                         ON m.batch_id=c.batch_id AND m.mukey=c.mukey
                       WHERE c.batch_id=%s""",
                    (batch[0], batch[1], batch_id),
                ).fetchone()
                checks = {
                    "map_unit_count": map_stats[0],
                    "component_count": component_stats[0],
                    "invalid_map_unit_count": map_stats[1],
                    "source_linkage_mismatch_count": map_stats[2] + component_stats[1],
                    "missing_required_field_count": map_stats[3] + component_stats[2],
                    "invalid_component_percentage_count": component_stats[3],
                    "orphan_component_count": component_stats[4],
                    "source_crs": batch[2],
                    "canonical_crs": batch[3],
                    "analysis_crs": batch[4],
                    "hydric_interpretation": "component-level soil information only; not wetlands mapping or a regulatory determination",
                }
                failure_keys = {
                    "invalid_map_unit_count",
                    "source_linkage_mismatch_count",
                    "missing_required_field_count",
                    "invalid_component_percentage_count",
                    "orphan_component_count",
                }
                failures = {
                    key: checks[key]
                    for key in failure_keys
                    if isinstance(checks[key], int) and checks[key] > 0
                }
                if checks["map_unit_count"] == 0:
                    failures["map_unit_count"] = 0
                if checks["component_count"] == 0:
                    failures["component_count"] = 0
                if failures:
                    connection.execute(
                        """UPDATE screening.ssurgo_ingestion_batches
                           SET validation_status='failed',promotion_status='failed',
                               validation_json=%s::jsonb,error_json=%s::jsonb,
                               validated_at=now() WHERE batch_id=%s""",
                        (_json(checks), _json({"qa_failures": failures}), batch_id),
                    )
                else:
                    connection.execute(
                        """UPDATE screening.ssurgo_ingestion_batches
                           SET validation_status='validated',promotion_status='validated',
                               validation_json=%s::jsonb,error_json=NULL,
                               validated_at=now() WHERE batch_id=%s""",
                        (_json(checks), batch_id),
                    )
        except Exception as exc:
            if isinstance(exc, KeyError):
                raise
            with self._transaction() as connection:
                connection.execute(
                    """UPDATE screening.ssurgo_ingestion_batches
                       SET validation_status='failed',promotion_status='failed',
                           error_json=%s::jsonb,validated_at=now() WHERE batch_id=%s""",
                    (_json({"error": str(exc)}), batch_id),
                )
            raise
        return self.get_ssurgo_batch(batch_id) or {"batch_id": batch_id}

    def promote_ssurgo_batch(
        self, batch_id: str, *, promotion_status: str = "fixture_only"
    ) -> dict[str, Any]:
        """Promote a validated batch atomically as a non-active representative fixture."""
        if promotion_status != "fixture_only":
            raise ValueError("This representative SSURGO slice only permits fixture_only promotion")
        with self._transaction() as connection:
            batch = connection.execute(
                """SELECT source_snapshot_id,source_version_id,promotion_status,
                          validation_status FROM screening.ssurgo_ingestion_batches
                   WHERE batch_id=%s FOR UPDATE""",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise KeyError(f"Unknown SSURGO batch: {batch_id}")
            if batch[2] == "fixture_only":
                return {
                    "batch_id": batch_id,
                    "source_snapshot_id": batch[0],
                    "source_version_id": batch[1],
                    "promotion_status": "fixture_only",
                    "idempotent": True,
                }
            if batch[2] != "validated" or batch[3] != "validated":
                raise ValueError("Only a successfully validated SSURGO batch may be promoted")
            conflict = connection.execute(
                """SELECT count(*)::int FROM screening.ssurgo_map_units_staging s
                   JOIN screening.ssurgo_map_units c
                     ON c.source_snapshot_id=%s AND c.source_version_id=%s AND c.mukey=s.mukey
                   WHERE s.batch_id=%s
                     AND (c.musym IS DISTINCT FROM s.musym
                          OR c.muname IS DISTINCT FROM s.muname
                          OR NOT ST_Equals(c.geometry,s.geometry))""",
                (batch[0], batch[1], batch_id),
            ).fetchone()[0]
            if conflict:
                raise ValueError("Existing SSURGO canonical rows conflict with this source version")
            connection.execute(
                """INSERT INTO screening.ssurgo_map_units
                   (source_snapshot_id,source_version_id,batch_id,mukey,areasymbol,areaname,
                    musym,muname,source_crs,canonical_crs,analysis_crs,source_geometry,geometry,
                    geometry_status,analysis_area_sqm,source_geometry_piece_count,promotion_status,
                    provenance)
                   SELECT source_snapshot_id,source_version_id,batch_id,mukey,areasymbol,areaname,
                          musym,muname,source_crs,canonical_crs,analysis_crs,source_geometry,geometry,
                          geometry_status,analysis_area_sqm,source_geometry_piece_count,
                          'fixture_only',provenance
                   FROM screening.ssurgo_map_units_staging WHERE batch_id=%s
                   ON CONFLICT (source_snapshot_id,source_version_id,mukey) DO NOTHING""",
                (batch_id,),
            )
            connection.execute(
                """INSERT INTO screening.ssurgo_components
                   (source_snapshot_id,source_version_id,batch_id,mukey,cokey,comppct_r,
                    hydricrating,hydricon,promotion_status,provenance)
                   SELECT source_snapshot_id,source_version_id,batch_id,mukey,cokey,comppct_r,
                          hydricrating,hydricon,'fixture_only',provenance
                   FROM screening.ssurgo_components_staging WHERE batch_id=%s
                   ON CONFLICT (source_snapshot_id,source_version_id,mukey,cokey) DO NOTHING""",
                (batch_id,),
            )
            counts = connection.execute(
                """SELECT
                      (SELECT count(*) FROM screening.ssurgo_map_units_staging WHERE batch_id=%s),
                      (SELECT count(*) FROM screening.ssurgo_components_staging WHERE batch_id=%s),
                      (SELECT count(*) FROM screening.ssurgo_map_units
                       WHERE source_snapshot_id=%s AND source_version_id=%s),
                      (SELECT count(*) FROM screening.ssurgo_components
                       WHERE source_snapshot_id=%s AND source_version_id=%s)""",
                (batch_id, batch_id, batch[0], batch[1], batch[0], batch[1]),
            ).fetchone()
            if counts[0] != counts[2] or counts[1] != counts[3]:
                raise RuntimeError("SSURGO promotion count reconciliation failed")
            connection.execute(
                """UPDATE screening.ssurgo_ingestion_batches
                   SET promotion_status='fixture_only',promoted_at=now() WHERE batch_id=%s""",
                (batch_id,),
            )
        return self.get_ssurgo_batch(batch_id) or {"batch_id": batch_id}

    def get_ssurgo_map_units(
        self, source_snapshot_id: str, source_version_id: str
    ) -> dict[str, Any]:
        """Return promoted SSURGO map units with their component joins."""
        with self._transaction() as connection:
            map_units = connection.execute(
                """SELECT mukey,areasymbol,areaname,musym,muname,source_crs,canonical_crs,
                          analysis_crs,ST_AsText(source_geometry),ST_AsText(geometry),
                          geometry_status,analysis_area_sqm,source_geometry_piece_count,
                          promotion_status,provenance
                   FROM screening.ssurgo_map_units
                   WHERE source_snapshot_id=%s AND source_version_id=%s ORDER BY mukey""",
                (source_snapshot_id, source_version_id),
            ).fetchall()
            components = connection.execute(
                """SELECT mukey,cokey,comppct_r,hydricrating,hydricon,promotion_status,provenance
                   FROM screening.ssurgo_components
                   WHERE source_snapshot_id=%s AND source_version_id=%s
                   ORDER BY mukey,cokey""",
                (source_snapshot_id, source_version_id),
            ).fetchall()
        component_keys = (
            "mukey",
            "cokey",
            "comppct_r",
            "hydricrating",
            "hydricon",
            "promotion_status",
            "provenance",
        )
        by_mukey: dict[str, list[dict[str, Any]]] = {}
        for row in components:
            item = dict(zip(component_keys, row, strict=True))
            by_mukey.setdefault(item["mukey"], []).append(item)
        map_unit_keys = (
            "mukey",
            "areasymbol",
            "areaname",
            "musym",
            "muname",
            "source_crs",
            "canonical_crs",
            "analysis_crs",
            "source_geometry_wkt",
            "geometry_wkt",
            "geometry_status",
            "analysis_area_sqm",
            "source_geometry_piece_count",
            "promotion_status",
            "provenance",
        )
        result = []
        for row in map_units:
            item = dict(zip(map_unit_keys, row, strict=True))
            item["components"] = by_mukey.get(item["mukey"], [])
            result.append(item)
        return {
            "source_snapshot_id": source_snapshot_id,
            "source_version_id": source_version_id,
            "map_units": result,
            "map_unit_count": len(result),
            "component_count": sum(len(item["components"]) for item in result),
        }

    def analyze_ssurgo_regional_coverage(
        self, batch_ids: list[str], aoi_id: str, aoi_revision: int
    ) -> dict[str, Any]:
        """Analyze existing regional staging rows in a read-only transaction."""
        if not batch_ids or len(batch_ids) != len(set(batch_ids)):
            raise ValueError("Coverage analysis requires a unique nonempty batch list")
        query = """
            WITH aoi AS MATERIALIZED (
                SELECT geometry AS geom,
                       ST_Area(ST_Transform(geometry, 5070)) AS area_sqm,
                       ST_AsGeoJSON(geometry, 9, 0)::jsonb AS geojson
                FROM screening.aoi_revisions
                WHERE aoi_id=%s AND aoi_revision=%s
            ), selected AS MATERIALIZED (
                SELECT f.batch_id,b.package_areasymbol,b.package_name,
                       b.source_snapshot_id,
                       b.source_version_id,b.candidate_id,b.ingestion_run_id,
                       b.source_crs,b.analysis_crs,f.stable_feature_id,
                       f.derived_geometry AS geom,
                       ST_Area(ST_Transform(f.derived_geometry,5070)) AS feature_area_sqm
                FROM screening.ssurgo_regional_features_staging f
                JOIN screening.ssurgo_regional_staging_batches b USING (batch_id)
                WHERE f.batch_id = ANY(%s)
            ), clipped AS MATERIALIZED (
                SELECT s.*,
                       ST_Intersection(s.geom,a.geom) AS clipped,
                       ST_Area(ST_Transform(ST_Intersection(s.geom,a.geom),5070))
                           AS clipped_area_sqm
                FROM selected s CROSS JOIN aoi a
                WHERE ST_Intersects(s.geom,a.geom)
            ), package_union AS MATERIALIZED (
                SELECT batch_id,package_areasymbol,package_name,source_snapshot_id,
                       source_version_id,candidate_id,ingestion_run_id,
                       source_crs,analysis_crs,
                       ST_UnaryUnion(ST_Collect(clipped)) AS geom,
                       count(*)::int AS intersecting_feature_count,
                       sum(clipped_area_sqm) AS sum_feature_intersection_area_sqm
                FROM clipped
                GROUP BY batch_id,package_areasymbol,package_name,source_snapshot_id,
                         source_version_id,candidate_id,ingestion_run_id,
                         source_crs,analysis_crs
            ), package_stats AS MATERIALIZED (
                SELECT p.*,
                       ST_Area(ST_Transform(p.geom,5070)) AS coverage_area_sqm,
                       t.feature_count,
                       t.feature_area_sqm,
                       t.feature_area_sqm - p.sum_feature_intersection_area_sqm
                           AS outside_feature_area_sqm
                FROM package_union p
                JOIN (
                    SELECT batch_id,count(*)::int AS feature_count,
                           sum(feature_area_sqm) AS feature_area_sqm
                    FROM selected GROUP BY batch_id
                ) t USING (batch_id)
            ), all_union AS MATERIALIZED (
                SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom
                FROM package_stats
            ), pair_geometries AS MATERIALIZED (
                SELECT p1.package_areasymbol AS package_a,
                       p2.package_areasymbol AS package_b,
                       ST_Intersection(p1.geom,p2.geom) AS geom
                FROM package_stats p1
                JOIN package_stats p2
                  ON p1.package_areasymbol < p2.package_areasymbol
                 AND ST_Intersects(p1.geom,p2.geom)
            ), pair_stats AS (
                SELECT package_a,package_b,geom,
                       ST_Area(ST_Transform(geom,5070)) AS area_sqm
                FROM pair_geometries
            ), aoi_gap AS (
                SELECT ST_Difference(a.geom,COALESCE(u.geom,
                           ST_GeomFromText('GEOMETRYCOLLECTION EMPTY',4326))) AS geom
                FROM aoi a CROSS JOIN all_union u
            )
            SELECT jsonb_build_object(
                'aoi', (SELECT jsonb_build_object(
                    'aoi_id',%s::text,'aoi_revision',%s::integer,'area_sqm',area_sqm,
                    'geometry',geojson) FROM aoi),
                'coverage', jsonb_build_object(
                    'covered_area_sqm',COALESCE(ST_Area(ST_Transform(u.geom,5070)),0),
                    'uncovered_area_sqm',COALESCE(a.area_sqm,0) -
                        COALESCE(ST_Area(ST_Transform(u.geom,5070)),0),
                    'outside_aoi_feature_area_sqm',
                        COALESCE((SELECT sum(feature_area_sqm -
                            sum_feature_intersection_area_sqm) FROM package_stats),0),
                    'outside_aoi_union_area_sqm',
                        COALESCE((SELECT ST_Area(ST_Transform(
                            ST_Difference(ST_UnaryUnion(ST_Collect(s.geom)),a.geom),5070))
                            FROM selected s),0),
                    'overlap_area_sqm',COALESCE((SELECT sum(area_sqm)
                        FROM pair_stats WHERE area_sqm > 0),0),
                    'overlap_pair_count',COALESCE((SELECT count(*)::int
                        FROM pair_stats WHERE area_sqm > 0),0),
                    'gap_component_count',COALESCE(ST_NumGeometries(g.geom),0),
                    'within_package_overlap_area_sqm',COALESCE((SELECT sum(
                        sum_feature_intersection_area_sqm-coverage_area_sqm)
                        FROM package_stats),0)),
                'gap_geometry',(SELECT ST_AsGeoJSON(geom,9,0)::jsonb FROM aoi_gap),
                'packages',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'batch_id',batch_id,'package_areasymbol',package_areasymbol,
                    'package_name',package_name,
                    'source_snapshot_id',source_snapshot_id,
                    'source_version_id',source_version_id,'candidate_id',candidate_id,
                    'ingestion_run_id',ingestion_run_id,'source_crs',source_crs,
                    'analysis_crs',analysis_crs,'feature_count',feature_count,
                    'intersecting_feature_count',intersecting_feature_count,
                    'feature_area_sqm',feature_area_sqm,
                    'coverage_area_sqm',coverage_area_sqm,
                    'sum_feature_intersection_area_sqm',sum_feature_intersection_area_sqm,
                    'outside_feature_area_sqm',outside_feature_area_sqm,
                    'coverage_geometry',ST_AsGeoJSON(geom,9,0)::jsonb)
                    ORDER BY package_areasymbol) FROM package_stats),'[]'::jsonb),
                'overlaps',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'package_a',package_a,'package_b',package_b,'area_sqm',area_sqm,
                    'geometry',ST_AsGeoJSON(geom,9,0)::jsonb)
                    ORDER BY package_a,package_b) FROM pair_stats
                    WHERE area_sqm > 0),'[]'::jsonb)) AS result
            FROM aoi a CROSS JOIN all_union u CROSS JOIN aoi_gap g
        """
        connection = self._connect()
        try:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                row = connection.execute(
                    query,
                    (aoi_id, aoi_revision, batch_ids, aoi_id, aoi_revision),
                ).fetchone()
        finally:
            connection.close()
        if row is None or row[0] is None:
            raise KeyError(f"Unknown AOI revision: {aoi_id}/{aoi_revision}")
        result = row[0]
        if isinstance(result, str):
            result = json.loads(result)
        result["batch_ids"] = list(batch_ids)
        return result

    def screen_ssurgo_snapshot(
        self, source_snapshot_id: str, source_version_id: str, aoi_geometry_wkt: str
    ) -> dict[str, Any]:
        """Screen only the explicitly fixture-only SSURGO version in a job snapshot.

        The source pair is part of every predicate. This method deliberately has no
        latest-version or active-pointer behavior and cannot consume a non-fixture
        canonical row in this representative slice.
        """
        with self._transaction() as connection:
            batch = connection.execute(
                """SELECT b.batch_id,b.validation_status,b.coverage_status,b.observation_status,
                          b.promotion_status,b.source_url,b.provider_release,b.retrieved_at::text,
                          b.terms_url,b.artifact_path,b.artifact_sha256,b.artifact_size_bytes,
                          b.source_crs,b.canonical_crs,b.analysis_crs,
                          (SELECT count(*) FROM screening.ssurgo_map_units m
                           WHERE m.source_snapshot_id=b.source_snapshot_id
                             AND m.source_version_id=b.source_version_id) AS canonical_count
                   FROM screening.ssurgo_ingestion_batches b
                   WHERE b.source_snapshot_id=%s AND b.source_version_id=%s""",
                (source_snapshot_id, source_version_id),
            ).fetchone()
            provenance = {
                "source_snapshot_id": source_snapshot_id,
                "source_version_id": source_version_id,
            }
            if batch is None:
                return {
                    "status": "unavailable",
                    "reason": "No SSURGO canonical fixture batch matches the immutable source snapshot.",
                    "provenance": provenance,
                }
            provenance.update(
                {
                    "batch_id": batch[0],
                    "source_url": batch[5],
                    "provider_release": batch[6],
                    "retrieved_at": batch[7],
                    "terms_url": batch[8],
                    "artifact_path": batch[9],
                    "sha256": batch[10],
                    "size_bytes": batch[11],
                    "source_crs": batch[12],
                    "canonical_crs": batch[13],
                    "analysis_crs": batch[14],
                    "validation_status": batch[1],
                    "coverage_status": batch[2],
                    "observation_status": batch[3],
                    "promotion_status": batch[4],
                }
            )
            if batch[4] != "fixture_only" or batch[15] == 0:
                return {
                    "status": "unavailable",
                    "reason": (
                        "The exact SSURGO source pair has no promoted fixture-only canonical records."
                    ),
                    "provenance": provenance,
                }

            aoi = connection.execute(
                """SELECT ST_IsEmpty(g),ST_IsValid(g),ST_GeometryType(g),ST_SRID(g),
                          ST_Area(ST_Transform(g,5070))
                   FROM (SELECT ST_SetSRID(ST_GeomFromText(%s),4326) AS g) aoi""",
                (aoi_geometry_wkt,),
            ).fetchone()
            if aoi[0] or not aoi[1] or aoi[2] not in {"ST_Polygon", "ST_MultiPolygon"}:
                raise ValueError(
                    "SSURGO screening AOI must be a valid WGS84 Polygon or MultiPolygon"
                )

            coverage = connection.execute(
                """WITH aoi AS (
                         SELECT ST_SetSRID(ST_GeomFromText(%s),4326) AS geometry
                       ), selected AS (
                         SELECT ST_Intersection(m.geometry,aoi.geometry) AS geometry
                         FROM screening.ssurgo_map_units m CROSS JOIN aoi
                         WHERE m.source_snapshot_id=%s AND m.source_version_id=%s
                           AND m.promotion_status='fixture_only'
                           AND ST_Intersects(m.geometry,aoi.geometry)
                       )
                       SELECT ST_Area(ST_Transform(aoi.geometry,5070)),
                              COALESCE((SELECT ST_Area(ST_Transform(
                                  ST_UnaryUnion(ST_Collect(geometry)),5070)) FROM selected),0)
                       FROM aoi""",
                (aoi_geometry_wkt, source_snapshot_id, source_version_id),
            ).fetchone()
            rows = connection.execute(
                """WITH aoi AS (
                         SELECT ST_SetSRID(ST_GeomFromText(%s),4326) AS geometry
                       ), selected AS (
                         SELECT m.mukey,m.areasymbol,m.areaname,m.musym,m.muname,
                                m.source_geometry_piece_count,
                                ST_Intersection(m.geometry,aoi.geometry) AS clipped
                         FROM screening.ssurgo_map_units m CROSS JOIN aoi
                         WHERE m.source_snapshot_id=%s AND m.source_version_id=%s
                           AND m.promotion_status='fixture_only'
                           AND ST_Intersects(m.geometry,aoi.geometry)
                       )
                       SELECT s.mukey,s.areasymbol,s.areaname,s.musym,s.muname,
                              s.source_geometry_piece_count,ST_AsGeoJSON(s.clipped),
                              count(c.cokey)::int,
                              COALESCE(jsonb_agg(jsonb_build_object(
                                  'mukey',c.mukey,'cokey',c.cokey,
                                  'comppct_r',c.comppct_r,
                                  'hydricrating',c.hydricrating,'hydricon',c.hydricon
                              ) ORDER BY c.cokey) FILTER (WHERE c.cokey IS NOT NULL),
                              '[]'::jsonb)
                       FROM selected s
                       LEFT JOIN screening.ssurgo_components c
                         ON c.source_snapshot_id=%s AND c.source_version_id=%s
                        AND c.mukey=s.mukey AND c.promotion_status='fixture_only'
                       GROUP BY s.mukey,s.areasymbol,s.areaname,s.musym,s.muname,
                                s.source_geometry_piece_count,s.clipped
                       ORDER BY s.mukey""",
                (
                    aoi_geometry_wkt,
                    source_snapshot_id,
                    source_version_id,
                    source_snapshot_id,
                    source_version_id,
                ),
            ).fetchall()

        aoi_area_sqm = float(coverage[0])
        covered_area_sqm = float(coverage[1])
        covered_percentage = covered_area_sqm / aoi_area_sqm * 100 if aoi_area_sqm else 0.0
        features: list[dict[str, Any]] = []
        component_records: list[dict[str, Any]] = []
        hydric_indicator_records: list[dict[str, Any]] = []
        mapunit_count = 0
        for row in rows:
            component_values = row[8]
            if isinstance(component_values, str):
                component_values = json.loads(component_values)
            component_values = list(component_values or [])
            component_records.extend(component_values)
            hydric_values = [
                component
                for component in component_values
                if component.get("hydricrating") is not None
                or component.get("hydricon") is not None
            ]
            hydric_indicator_records.extend(hydric_values)
            positive_count = sum(
                1
                for component in component_values
                if str(component.get("hydricrating") or "").strip().lower() == "yes"
            )
            features.append(
                {
                    "type": "Feature",
                    "geometry": json.loads(row[6]),
                    "properties": {
                        "mukey": row[0],
                        "areasymbol": row[1],
                        "areaname": row[2],
                        "musym": row[3],
                        "muname": row[4],
                        "source_geometry_piece_count": row[5],
                        "component_record_count": row[7],
                        "hydric_indicator_record_count": len(hydric_values),
                        "hydric_positive_record_count": positive_count,
                        "source_snapshot_id": source_snapshot_id,
                        "source_version_id": source_version_id,
                        "source_status": "fixture_only",
                        "hydric_interpretation": (
                            "Hydric-soil information; not a wetlands inventory or regulatory determination."
                        ),
                    },
                }
            )
            mapunit_count += 1

        if not rows:
            screening_status = "uncovered"
            observation_status = "not_covered"
        elif hydric_indicator_records:
            screening_status = "observed"
            observation_status = "data_observed"
        else:
            screening_status = "no_indicator_observed"
            observation_status = "data_observed"
        coverage_status = "complete" if covered_percentage >= 99.999999 else "partial"
        return {
            "status": "available",
            "screening_status": screening_status,
            "coverage_status": coverage_status,
            "observation_status": observation_status,
            "provenance": provenance,
            "features": features,
            "metrics": {
                "source_status": "fixture_only",
                "screening_status": screening_status,
                "aoi_area_sqm": round(aoi_area_sqm, 3),
                "covered_aoi_area_sqm": round(covered_area_sqm, 3),
                "uncovered_aoi_area_sqm": round(max(aoi_area_sqm - covered_area_sqm, 0.0), 3),
                "covered_aoi_percentage": round(covered_percentage, 6),
                "intersecting_mapunit_count": mapunit_count,
                "component_record_count": len(component_records),
                "component_records": component_records,
                "hydric_indicator_record_count": len(hydric_indicator_records),
                "hydric_indicator_records": hydric_indicator_records,
                "hydric_positive_record_count": sum(
                    1
                    for component in hydric_indicator_records
                    if str(component.get("hydricrating") or "").strip().lower() == "yes"
                ),
                "hydric_interpretation": (
                    "Hydric-soil information; not a wetlands inventory or regulatory determination."
                ),
            },
        }


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
