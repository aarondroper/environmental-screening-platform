"""NRCS SSURGO: survey-area packages from Web Soil Survey → versioned PostGIS tables.

Release detection uses Soil Data Access (`sacatalog.saverest` per survey area), so an
unchanged release is detected without downloading. Each package is a ZIP holding
shapefiles (`spatial/`) and headerless pipe-delimited tables (`tabular/`).
"""

import csv
import hashlib
import io
import logging
import shutil
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
import pyogrio.raw  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.orm import Session

from esp.catalog import DatasetInfo

log = logging.getLogger(__name__)

INFO = DatasetInfo(
    id="ssurgo",
    title="SSURGO hydric soil rating",
    provider="USDA Natural Resources Conservation Service",
    license="Public domain",
    homepage="https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
)

SDA_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"
WSS_PACKAGE_URL = (
    "https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/wss_SSA_{area}_[{date}].zip"
)

# Headerless table layouts (SSURGO 2.3.x). Column counts are checked as a schema gate.
MAPUNIT_COLUMNS, MAPUNIT_MUSYM, MAPUNIT_MUNAME = 24, 0, 1
MUAGGATT_COLUMNS, MUAGGATT_HYDCLPRS = 40, 37


class SchemaError(Exception):
    pass


# --- Acquisition ----------------------------------------------------------------------


class PackageSource(Protocol):
    def releases(self, areas: list[str]) -> dict[str, str]:
        """Current release identifier (saverest timestamp) per survey area."""
        ...

    def download(self, area: str, release: str, dest_dir: Path) -> tuple[str, Path]:
        """Download one package; returns (url, local path)."""
        ...


class WebSoilSurvey:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def releases(self, areas: list[str]) -> dict[str, str]:
        quoted = ",".join(f"'{a}'" for a in areas if a.isalnum())
        query = f"SELECT areasymbol, saverest FROM sacatalog WHERE areasymbol IN ({quoted})"
        response = self.client.post(SDA_URL, json={"query": query, "format": "JSON"})
        response.raise_for_status()
        rows = response.json().get("Table", [])
        found = {
            area: datetime.strptime(saverest, "%m/%d/%Y %I:%M:%S %p").isoformat()
            for area, saverest in rows
        }
        missing = set(areas) - set(found)
        if missing:
            raise ValueError(f"unknown SSURGO survey areas: {sorted(missing)}")
        return found

    def download(self, area: str, release: str, dest_dir: Path) -> tuple[str, Path]:
        url = WSS_PACKAGE_URL.format(area=area, date=release[:10])
        dest = dest_dir / f"{area}.zip"
        with self.client.stream("GET", url, timeout=300) as response:
            response.raise_for_status()
            with dest.open("wb") as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
        if not zipfile.is_zipfile(dest):
            raise ValueError(f"{url} did not return a ZIP archive")
        return url, dest


class LocalPackageDir:
    """Packages already on disk as `<dir>/<AREA>.zip` (offline loads, CI smoke tests).

    The release identifier is derived from the file content, so re-running with the same
    files is detected as unchanged.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def releases(self, areas: list[str]) -> dict[str, str]:
        return {area: f"local-{_sha256(self.directory / f'{area}.zip')[:12]}" for area in areas}

    def download(self, area: str, release: str, dest_dir: Path) -> tuple[str, Path]:
        source = self.directory / f"{area}.zip"
        dest = dest_dir / source.name
        shutil.copyfile(source, dest)
        return source.resolve().as_uri(), dest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Parsing --------------------------------------------------------------------------


@dataclass
class Package:
    area: str
    path: Path
    mapunits: list[dict[str, Any]] = field(default_factory=list)

    def _member(self, suffix: str) -> str:
        return f"{self.area}/{suffix.format(a=self.area.lower())}"

    def vsi(self, suffix: str) -> str:
        return f"/vsizip/{self.path}/{self._member(suffix)}"


def _table(zf: zipfile.ZipFile, member: str, columns: int) -> list[list[str]]:
    with zf.open(member) as raw:
        rows = list(csv.reader(io.TextIOWrapper(raw, encoding="utf-8"), delimiter="|"))
    bad = {len(r) for r in rows} - {columns}
    if bad:
        raise SchemaError(f"{member}: expected {columns} columns, found {sorted(bad)}")
    return rows


def read_package(area: str, path: Path) -> Package:
    package = Package(area=area, path=path)
    with zipfile.ZipFile(path) as zf:
        mapunit = _table(zf, package._member("tabular/mapunit.txt"), MAPUNIT_COLUMNS)
        muaggatt = _table(zf, package._member("tabular/muaggatt.txt"), MUAGGATT_COLUMNS)
    hydric = {row[-1]: row[MUAGGATT_HYDCLPRS] for row in muaggatt}
    package.mapunits = [
        {
            "mukey": row[-1],
            "areasymbol": area,
            "musym": row[MAPUNIT_MUSYM],
            "muname": row[MAPUNIT_MUNAME],
            "hydric_pct": int(hydric[row[-1]]) if hydric.get(row[-1]) else None,
        }
        for row in mapunit
    ]
    return package


def read_layer(package: Package, suffix: str) -> tuple[dict[str, Any], Iterator[tuple[Any, ...]]]:
    """Read a shapefile layer; rejects anything not in WGS84 lon/lat."""
    meta, _, geometry, fields = pyogrio.raw.read(package.vsi(suffix))
    if meta["crs"] != "EPSG:4326":
        raise SchemaError(f"{suffix}: expected EPSG:4326, found {meta['crs']}")
    names = [n.lower() for n in meta["fields"]]
    columns = {name: fields[i] for i, name in enumerate(names)}
    return meta, zip(geometry, *(columns[n] for n in names), strict=True)


# --- Loading --------------------------------------------------------------------------


def load(session: Session, version_id: uuid.UUID, packages: list[Package]) -> dict[str, Any]:
    """Load packages into canonical tables under `version_id` (invisible until promoted).

    Raw geometries are copied into a temporary staging table first, then inserted as
    MultiPolygons; invalid ones are repaired with ST_MakeValid and flagged `repaired`.
    """
    conn = session.connection().connection.driver_connection
    assert conn is not None
    session.execute(
        text(
            "CREATE TEMP TABLE ssurgo_stage (mukey text, areasymbol text, wkb bytea)"
            " ON COMMIT DROP;"
            "CREATE TEMP TABLE ssurgo_stage_areas (areasymbol text, wkb bytea) ON COMMIT DROP"
        )
    )
    polygon_counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for package in packages:
            session.execute(
                text(
                    "INSERT INTO ssurgo_mapunits"
                    " (version_id, mukey, areasymbol, musym, muname, hydric_pct)"
                    " VALUES (:v, :mukey, :areasymbol, :musym, :muname, :hydric_pct)"
                ),
                [{"v": version_id, **mu} for mu in package.mapunits],
            )
            meta, rows = read_layer(package, "spatial/soilmu_a_{a}.shp")
            names = [n.lower() for n in meta["fields"]]
            mukey_i, area_i = names.index("mukey") + 1, names.index("areasymbol") + 1
            count = 0
            with cur.copy("COPY ssurgo_stage (mukey, areasymbol, wkb) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row((row[mukey_i], row[area_i], row[0]))
                    count += 1
            polygon_counts[package.area] = count
            _, boundary = read_layer(package, "spatial/soilsa_a_{a}.shp")
            with cur.copy("COPY ssurgo_stage_areas (areasymbol, wkb) FROM STDIN") as copy:
                for row in boundary:
                    copy.write_row((package.area, row[0]))

    session.execute(
        text(
            """
            INSERT INTO ssurgo_polygons (version_id, mukey, areasymbol, geom, repaired)
            SELECT :v, mukey, areasymbol,
                   CASE WHEN ST_IsValid(g) THEN ST_Multi(g)
                        ELSE ST_Multi(ST_CollectionExtract(ST_MakeValid(g), 3)) END,
                   NOT ST_IsValid(g)
            FROM (SELECT mukey, areasymbol, ST_SetSRID(ST_GeomFromWKB(wkb), 4326) AS g
                  FROM ssurgo_stage) s
            """
        ),
        {"v": version_id},
    )
    session.execute(
        text(
            """
            UPDATE dataset_versions SET coverage = (
                SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(
                    ST_Union(ST_SetSRID(ST_GeomFromWKB(wkb), 4326))), 3))
                FROM ssurgo_stage_areas)
            WHERE id = :v
            """
        ),
        {"v": version_id},
    )
    return {"polygons_by_area": polygon_counts}


# --- Validation -----------------------------------------------------------------------


def validate(
    session: Session, version_id: uuid.UUID, previous_id: uuid.UUID | None
) -> dict[str, Any]:
    """Quality gates a version must pass before it may be promoted."""
    v = {"v": version_id}
    q = session.execute(
        text(
            """
            SELECT count(*) AS polygons,
                   count(*) FILTER (WHERE repaired) AS repaired,
                   count(*) FILTER (WHERE ST_IsEmpty(geom) OR NOT ST_IsValid(geom)) AS invalid,
                   count(*) FILTER (WHERE NOT EXISTS (
                       SELECT 1 FROM ssurgo_mapunits m
                       WHERE m.version_id = p.version_id AND m.mukey = p.mukey)) AS orphans,
                   coalesce(sum(ST_Area(geom::geography)), 0) AS polygon_area_m2
            FROM ssurgo_polygons p WHERE version_id = :v
            """
        ),
        v,
    ).one()
    coverage_m2: float = session.execute(
        text(
            "SELECT coalesce(ST_Area(coverage::geography), 0) FROM dataset_versions WHERE id = :v"
        ),
        v,
    ).scalar_one()
    mapunits: int = session.execute(
        text("SELECT count(*) FROM ssurgo_mapunits WHERE version_id = :v"), v
    ).scalar_one()

    area_ratio = q.polygon_area_m2 / coverage_m2 if coverage_m2 else 0.0
    checks = [
        _check("has_polygons", q.polygons > 0, f"{q.polygons} polygons"),
        _check("has_mapunits", mapunits > 0, f"{mapunits} map units"),
        _check("geometries_valid", q.invalid == 0, f"{q.invalid} invalid or empty after repair"),
        _check(
            "repairs_rare",
            q.repaired <= 0.01 * max(q.polygons, 1),
            f"{q.repaired} of {q.polygons} source polygons repaired (limit 1%)",
        ),
        _check("mapunit_keys_resolve", q.orphans == 0, f"{q.orphans} polygons without map unit"),
        _check(
            "polygons_fill_survey_areas",
            0.99 <= area_ratio <= 1.01,
            f"polygon area / survey-area boundary area = {area_ratio:.4f} (expect 0.99-1.01)",
        ),
    ]
    if previous_id is not None:
        previous: int = session.execute(
            text("SELECT count(*) FROM ssurgo_polygons WHERE version_id = :p"), {"p": previous_id}
        ).scalar_one()
        checks.append(
            _check(
                "no_large_drop_vs_active",
                q.polygons >= 0.9 * previous,
                f"{q.polygons} polygons vs {previous} in active version (min 90%)",
            )
        )
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "stats": {
            "polygons": q.polygons,
            "mapunits": mapunits,
            "repaired_polygons": q.repaired,
            "coverage_km2": round(coverage_m2 / 1e6, 3),
        },
    }


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}
