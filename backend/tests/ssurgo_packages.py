"""Build SSURGO survey-area packages in the Web Soil Survey layout, for tests.

`python -m tests.ssurgo_packages <full CO644 package.zip>` regenerates the checked-in
fixture `tests/fixtures/ssurgo/CO644.zip`: the real Larimer County Area package (public
domain, NRCS) clipped to a ~12 km² window along the Cache la Poudre River in Fort Collins.
"""

import csv
import io
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pyogrio.raw
import shapely
from shapely.geometry import box

FIXTURE = Path(__file__).parent / "fixtures" / "ssurgo" / "CO644.zip"
WINDOW = box(-105.08, 40.57, -105.04, 40.60)
WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def build_package(
    dest: Path,
    area: str,
    mapunit_rows: list[list[str]],
    muaggatt_rows: list[list[str]],
    polygons: list[tuple[str, shapely.Geometry]],
    boundary: shapely.Geometry,
) -> Path:
    """Write a package ZIP. `polygons` are (mukey, polygon) pairs in EPSG:4326."""
    with tempfile.TemporaryDirectory() as tmp:
        spatial = Path(tmp) / area / "spatial"
        spatial.mkdir(parents=True)
        a = area.lower()
        _write_shp(
            spatial / f"soilmu_a_{a}.shp",
            [g for _, g in polygons],
            {
                "AREASYMBOL": [area] * len(polygons),
                "SPATIALVER": ["1"] * len(polygons),
                "MUSYM": ["x"] * len(polygons),
                "MUKEY": [k for k, _ in polygons],
            },
        )
        _write_shp(spatial / f"soilsa_a_{a}.shp", [boundary], {"AREASYMBOL": [area]})
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(spatial.iterdir()):
                zf.write(path, f"{area}/spatial/{path.name}")
            zf.writestr(f"{area}/tabular/mapunit.txt", _pipe(mapunit_rows))
            zf.writestr(f"{area}/tabular/muaggatt.txt", _pipe(muaggatt_rows))
    return dest


def _write_shp(path: Path, geoms: list[shapely.Geometry], fields: dict[str, list[str]]) -> None:
    wkb = np.array([shapely.to_wkb(g) for g in geoms], dtype=object)
    pyogrio.raw.write(
        str(path),
        geometry=wkb,
        field_data=[np.array(v, dtype=object) for v in fields.values()],
        fields=list(fields),
        geometry_type="Polygon",
        crs="EPSG:4326",
        driver="ESRI Shapefile",
    )
    path.with_suffix(".prj").write_text(WGS84_PRJ)


def _pipe(rows: list[list[str]]) -> str:
    out = io.StringIO()
    csv.writer(out, delimiter="|", lineterminator="\n").writerows(rows)
    return out.getvalue()


def _read_table(zf: zipfile.ZipFile, member: str) -> list[list[str]]:
    with zf.open(member) as raw:
        return list(csv.reader(io.TextIOWrapper(raw, encoding="utf-8"), delimiter="|"))


def make_fixture(full_package: Path) -> None:
    src = f"/vsizip/{full_package}/CO644/spatial/soilmu_a_co644.shp"
    meta, _, geometry, fields = pyogrio.raw.read(src, bbox=WINDOW.bounds)
    mukeys = fields[[n.upper() for n in meta["fields"]].index("MUKEY")]
    polygons: list[tuple[str, shapely.Geometry]] = []
    for mukey, wkb in zip(mukeys, geometry, strict=True):
        clipped = shapely.intersection(shapely.from_wkb(wkb), WINDOW)
        for part in getattr(clipped, "geoms", [clipped]):
            if part.geom_type == "Polygon" and not part.is_empty:
                polygons.append((mukey, part))
    keep = {k for k, _ in polygons}
    with zipfile.ZipFile(full_package) as zf:
        mapunit = [r for r in _read_table(zf, "CO644/tabular/mapunit.txt") if r[-1] in keep]
        muaggatt = [r for r in _read_table(zf, "CO644/tabular/muaggatt.txt") if r[-1] in keep]
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    build_package(FIXTURE, "CO644", mapunit, muaggatt, polygons, WINDOW)
    print(f"{FIXTURE}: {len(polygons)} polygons, {len(keep)} map units")


if __name__ == "__main__":
    make_fixture(Path(sys.argv[1]))
