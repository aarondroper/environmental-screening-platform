"""Per-dataset screening metrics against a pinned dataset version.

Metrics are transparent physical quantities (areas, percentages of the AOI); there is no
composite score. Area not covered by a dataset is reported as such, never as absence.
"""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# NRCS Web Soil Survey "Hydric Rating by Map Unit" classes over muaggatt.hydclprs
# (percent of the map unit made up of hydric components). A soil indicator only:
# not a wetland delineation or jurisdictional determination.
HYDRIC_CLASSES: list[tuple[str, str]] = [
    ("hydric_100", "100% hydric components"),
    ("hydric_66_99", "66–99% hydric components"),
    ("hydric_33_65", "33–65% hydric components"),
    ("hydric_1_32", "1–32% hydric components"),
    ("hydric_0", "Less than 1% hydric components"),
    ("not_rated", "Not rated"),
]
_HYDRIC_CLASS_SQL = """
    CASE WHEN m.hydric_pct IS NULL THEN 'not_rated'
         WHEN m.hydric_pct >= 100 THEN 'hydric_100'
         WHEN m.hydric_pct >= 66 THEN 'hydric_66_99'
         WHEN m.hydric_pct >= 33 THEN 'hydric_33_65'
         WHEN m.hydric_pct >= 1 THEN 'hydric_1_32'
         ELSE 'hydric_0' END
"""
# Coverage below this share of the AOI is reported as partial rather than complete
# (tolerates floating-point slivers along survey-area edges).
COMPLETE_COVERAGE = 0.999


def _coverage(session: Session, aoi_id: uuid.UUID, version_id: str) -> tuple[float, float]:
    row = session.execute(
        text(
            """
            SELECT ST_Area(a.geom::geography),
                   coalesce(ST_Area(ST_Intersection(a.geom, v.coverage)::geography), 0)
            FROM aois a, dataset_versions v WHERE a.id = :aoi AND v.id = :v
            """
        ),
        {"aoi": aoi_id, "v": version_id},
    ).one()
    return float(row[0]), float(row[1])


def screen_ssurgo(
    session: Session, aoi_id: uuid.UUID, version_id: str
) -> tuple[str, dict[str, Any]]:
    aoi_m2, covered_m2 = _coverage(session, aoi_id, version_id)
    rows = session.execute(
        text(
            f"""
            SELECT {_HYDRIC_CLASS_SQL} AS class,
                   sum(ST_Area(ST_Intersection(p.geom, a.geom)::geography)) AS area_m2,
                   count(DISTINCT p.mukey) AS mapunits
            FROM aois a
            JOIN ssurgo_polygons p ON p.version_id = :v AND ST_Intersects(p.geom, a.geom)
            JOIN ssurgo_mapunits m ON m.version_id = p.version_id AND m.mukey = p.mukey
            WHERE a.id = :aoi
            GROUP BY 1
            """
        ),
        {"aoi": aoi_id, "v": version_id},
    ).all()
    by_class = {r[0]: r for r in rows}
    classes = [
        {
            "class": key,
            "label": label,
            "area_m2": round(float(by_class[key][1]), 1) if key in by_class else 0.0,
            "pct_of_aoi": round(100 * float(by_class[key][1]) / aoi_m2, 2)
            if key in by_class
            else 0.0,
            "mapunits": int(by_class[key][2]) if key in by_class else 0,
        }
        for key, label in HYDRIC_CLASSES
    ]
    coverage = covered_m2 / aoi_m2 if aoi_m2 else 0.0
    status = (
        "complete"
        if coverage >= COMPLETE_COVERAGE
        else "partial_coverage"
        if covered_m2 > 0
        else "not_covered"
    )
    return status, {
        "aoi_area_m2": round(aoi_m2, 1),
        "covered_area_m2": round(covered_m2, 1),
        "covered_pct": round(100 * coverage, 2),
        "classes": classes,
    }


def ssurgo_features(session: Session, aoi_id: uuid.UUID, version_id: str) -> dict[str, Any]:
    """Soil map unit polygons clipped to the AOI, as a GeoJSON FeatureCollection."""
    collection: dict[str, Any] = session.execute(
        text(
            f"""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', coalesce(json_agg(json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(clipped, 6)::json,
                    'properties', json_build_object(
                        'mukey', mukey, 'muname', muname, 'hydric_pct', hydric_pct,
                        'class', class))), '[]'::json))
            FROM (
                SELECT p.mukey, m.muname, m.hydric_pct, {_HYDRIC_CLASS_SQL} AS class,
                       ST_CollectionExtract(ST_Intersection(p.geom, a.geom), 3) AS clipped
                FROM aois a
                JOIN ssurgo_polygons p ON p.version_id = :v AND ST_Intersects(p.geom, a.geom)
                JOIN ssurgo_mapunits m ON m.version_id = p.version_id AND m.mukey = p.mukey
                WHERE a.id = :aoi
            ) f
            WHERE NOT ST_IsEmpty(clipped)
            """
        ),
        {"aoi": aoi_id, "v": version_id},
    ).scalar_one()
    return dict(collection)


SCREENERS = {"ssurgo": screen_ssurgo}
FEATURES = {"ssurgo": ssurgo_features}
