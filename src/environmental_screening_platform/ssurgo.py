"""Project-owned parsing and validation records for the SSURGO spatial slice.

The parser accepts the bounded SDA response already acquired outside Git. It
does not acquire or infer full regional SSURGO coverage. Hydric attributes are
retained as component-level soil information only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely import wkt
from shapely.geometry import MultiPolygon
from shapely.ops import transform, unary_union

SSURGO_SOURCE_CRS = "EPSG:4326"
SSURGO_CANONICAL_CRS = "EPSG:4326"
SSURGO_ANALYSIS_CRS = "EPSG:5070"
SSURGO_SOURCE_ID = "ssurgo"
SSURGO_TERMS_URL = (
    "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo"
)
SSURGO_DEFAULT_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"


@dataclass(frozen=True)
class SsurgoComponentRecord:
    mukey: str
    cokey: str
    comppct_r: float | None
    hydricrating: str | None
    hydricon: str | None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SsurgoMapUnitRecord:
    mukey: str
    musym: str
    muname: str
    geometry_wkt: str
    source_geometry_piece_count: int
    analysis_area_sqm: float
    components: tuple[SsurgoComponentRecord, ...]
    geometry_status: str = "valid"
    areasymbol: str | None = None
    areaname: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SsurgoBatchRecord:
    batch_id: str
    source_snapshot_id: str
    source_version_id: str
    artifact_path: str
    artifact_sha256: str
    artifact_size_bytes: int
    source_url: str
    provider_release: str
    retrieved_at: str | None
    terms_url: str
    map_units: tuple[SsurgoMapUnitRecord, ...]
    ingestion_run_id: str | None = None
    candidate_id: str | None = None
    source_crs: str = SSURGO_SOURCE_CRS
    canonical_crs: str = SSURGO_CANONICAL_CRS
    analysis_crs: str = SSURGO_ANALYSIS_CRS
    coverage_status: str = "partial"
    observation_status: str = "data_observed"
    provenance: dict[str, Any] = field(default_factory=dict)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _multipolygon(geometry: Any) -> MultiPolygon:
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("SSURGO map-unit geometry is empty or invalid")
    if geometry.geom_type == "Polygon":
        return MultiPolygon([geometry])
    if geometry.geom_type == "MultiPolygon":
        return geometry
    raise ValueError(f"SSURGO map-unit geometry is not polygonal: {geometry.geom_type}")


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 100:
        raise ValueError(f"SSURGO comppct_r is outside 0..100: {value!r}")
    return number


def _metadata(metadata_path: Path | None) -> dict[str, Any]:
    if metadata_path is None:
        return {}
    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("SSURGO acquisition metadata must be a JSON object")
    return value


def parse_ssurgo_fixture(
    artifact_path: Path,
    *,
    batch_id: str,
    source_snapshot_id: str,
    source_version_id: str,
    metadata_path: Path | None = None,
    ingestion_run_id: str | None = None,
    candidate_id: str | None = None,
) -> SsurgoBatchRecord:
    """Parse one acquired SDA JSON response into deterministic staging records."""
    body = artifact_path.read_bytes()
    checksum = _sha256(body)
    metadata = _metadata(metadata_path)
    if metadata.get("sha256") not in (None, checksum):
        raise ValueError("SSURGO artifact checksum does not match acquisition metadata")
    if metadata.get("size_bytes") not in (None, len(body)):
        raise ValueError("SSURGO artifact size does not match acquisition metadata")
    if metadata.get("version_id") not in (None, source_version_id):
        raise ValueError("SSURGO source version does not match acquisition metadata")

    payload = json.loads(body)
    table = payload.get("Table") if isinstance(payload, dict) else None
    if not isinstance(table, list) or len(table) < 2 or not isinstance(table[0], list):
        raise ValueError("SSURGO fixture must contain a non-empty SDA Table")
    columns = [str(value).lower() for value in table[0]]
    required = {"mukey", "musym", "muname", "cokey", "comppct_r", "hydricrating", "hydricon"}
    if not required.issubset(columns):
        raise ValueError(
            f"SSURGO fixture is missing required columns: {sorted(required - set(columns))}"
        )
    if "polygon_wkt" not in columns:
        raise ValueError("SSURGO fixture must include polygon_wkt for the spatial slice")

    rows = [dict(zip(columns, row, strict=True)) for row in table[1:]]
    if not rows:
        raise ValueError("SSURGO fixture contains no map-unit/component rows")
    grouped_geometries: dict[str, dict[str, Any]] = {}
    mapunit_values: dict[str, tuple[str, str, str | None, str | None]] = {}
    components: dict[tuple[str, str], SsurgoComponentRecord] = {}
    for row in rows:
        mukey = str(row.get("mukey") or "").strip()
        cokey = str(row.get("cokey") or "").strip()
        musym = str(row.get("musym") or "").strip()
        muname = str(row.get("muname") or "").strip()
        if not mukey or not cokey or not musym or not muname:
            raise ValueError("SSURGO fixture has an empty required identifier or name")
        values = (
            musym,
            muname,
            str(row["areasymbol"]).strip() if row.get("areasymbol") else None,
            str(row["areaname"]).strip() if row.get("areaname") else None,
        )
        previous_values = mapunit_values.setdefault(mukey, values)
        if previous_values != values:
            raise ValueError(f"Conflicting SSURGO map-unit values for {mukey}")
        geometry_text = str(row["polygon_wkt"] or "").strip()
        if not geometry_text:
            raise ValueError(f"SSURGO map unit {mukey} has no polygon geometry")
        geometry = _multipolygon(wkt.loads(geometry_text))
        grouped_geometries.setdefault(mukey, {})[geometry_text] = geometry
        component = SsurgoComponentRecord(
            mukey=mukey,
            cokey=cokey,
            comppct_r=_number(row.get("comppct_r")),
            hydricrating=(
                str(row["hydricrating"]) if row.get("hydricrating") is not None else None
            ),
            hydricon=(str(row["hydricon"]) if row.get("hydricon") is not None else None),
            provenance={"source_row_columns": columns},
        )
        key = (mukey, cokey)
        if key in components and components[key] != component:
            raise ValueError(f"Conflicting SSURGO component values for {mukey}/{cokey}")
        components[key] = component

    to_analysis = Transformer.from_crs(
        SSURGO_CANONICAL_CRS, SSURGO_ANALYSIS_CRS, always_xy=True
    ).transform
    map_units: list[SsurgoMapUnitRecord] = []
    for mukey in sorted(grouped_geometries):
        pieces = list(grouped_geometries[mukey].values())
        union = _multipolygon(unary_union(pieces))
        unit_components = tuple(
            component
            for (component_mukey, _), component in sorted(components.items())
            if component_mukey == mukey
        )
        if not unit_components:
            raise ValueError(f"SSURGO map unit {mukey} has no related components")
        musym, muname, areasymbol, areaname = mapunit_values[mukey]
        map_units.append(
            SsurgoMapUnitRecord(
                mukey=mukey,
                musym=musym,
                muname=muname,
                geometry_wkt=union.wkt,
                source_geometry_piece_count=len(pieces),
                analysis_area_sqm=transform(to_analysis, union).area,
                components=unit_components,
                areasymbol=areasymbol,
                areaname=areaname,
                provenance={
                    "normalization": "distinct provider polygon pieces unioned by mukey; source and canonical CRS both EPSG:4326",
                    "source_geometry_piece_count": len(pieces),
                },
            )
        )
    return SsurgoBatchRecord(
        batch_id=batch_id,
        source_snapshot_id=source_snapshot_id,
        source_version_id=source_version_id,
        artifact_path=str(artifact_path),
        artifact_sha256=checksum,
        artifact_size_bytes=len(body),
        source_url=str(metadata.get("source_url") or SSURGO_DEFAULT_URL),
        provider_release=str(
            metadata.get("release") or "Current SDA SSURGO tabular and map-unit spatial query"
        ),
        retrieved_at=str(metadata["acquired_at"]) if metadata.get("acquired_at") else None,
        terms_url=str(metadata.get("terms_url") or SSURGO_TERMS_URL),
        map_units=tuple(map_units),
        ingestion_run_id=ingestion_run_id,
        candidate_id=candidate_id,
        provenance={
            "provider": metadata.get("provider", "USDA NRCS Soil Data Access"),
            "validation_scope": "Representative Boulder-area SDA response only; not full regional SSURGO coverage",
            "hydric_interpretation": "component-level soil information only; not wetlands mapping or a regulatory determination",
            "request_parameters": metadata.get("request_parameters", {}),
        },
    )
