"""Ingest → submit via API → worker → results, against real PostGIS."""

import csv
import io
import zipfile
from pathlib import Path
from typing import Any

import pyogrio.raw
import pytest
import shapely
from fastapi.testclient import TestClient
from pyproj import Geod
from shapely.geometry import box, mapping
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from esp import jobs
from esp.api.main import app
from esp.ingest import ingest_ssurgo
from esp.models import ScreeningJob
from esp.worker import work_once
from tests.ssurgo_packages import FIXTURE
from tests.test_ssurgo_ingest import RELEASE, LocalPackages

# Inside the fixture window (-105.08, 40.57, -105.04, 40.60).
INSIDE = box(-105.075, 40.575, -105.0405, 40.597)
# Western half outside the window (but inside Colorado and SSURGO-free in the fixture).
STRADDLING = box(-105.10, 40.575, -105.06, 40.595)
OUTSIDE_COVERAGE = box(-106.0, 39.0, -105.98, 39.02)

client = TestClient(app)


@pytest.fixture
def loaded(sessions: sessionmaker[Session], tmp_path: Path) -> sessionmaker[Session]:
    ingest_ssurgo(sessions, LocalPackages(FIXTURE, RELEASE), ["CO644"], tmp_path)
    return sessions


def _submit(geometry: shapely.Geometry, **headers: str) -> dict[str, Any]:
    response = client.post(
        "/api/screenings",
        json={"name": "Test site", "geometry": mapping(geometry)},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return dict(response.json())


def _run_all(sessions: sessionmaker[Session]) -> None:
    while work_once(sessions, "test-worker"):
        pass


def _screen(sessions: sessionmaker[Session], geometry: shapely.Geometry) -> dict[str, Any]:
    job = _submit(geometry)
    assert job["status"] == "queued"
    _run_all(sessions)
    result = client.get(f"/api/screenings/{job['id']}").json()
    assert result["status"] == "succeeded"
    return dict(result)


def _independent_hydric_area(aoi: shapely.Geometry, klass: range) -> float:
    """Geodesic area (m²) of fixture polygons in a hydric % range, clipped to `aoi`."""
    with zipfile.ZipFile(FIXTURE) as zf, zf.open("CO644/tabular/muaggatt.txt") as raw:
        rows = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"), delimiter="|")
        hydric = {r[-1]: int(r[37]) for r in rows if r[37]}
    meta, _, wkbs, fields = pyogrio.raw.read(f"/vsizip/{FIXTURE}/CO644/spatial/soilmu_a_co644.shp")
    mukeys = fields[[f.lower() for f in meta["fields"]].index("mukey")]
    geod = Geod(ellps="WGS84")
    total = 0.0
    for mukey, wkb in zip(mukeys, wkbs, strict=True):
        if hydric.get(mukey, -1) in klass:
            piece = shapely.intersection(shapely.from_wkb(wkb), aoi)
            total += abs(geod.geometry_area_perimeter(piece)[0])
    return total


def _classes(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    (ssurgo,) = [r for r in result["results"] if r["dataset_id"] == "ssurgo"]
    return {c["class"]: c for c in ssurgo["metrics"]["classes"]}


def test_screening_inside_coverage_is_complete_and_matches_independent_calculation(
    loaded: sessionmaker[Session],
) -> None:
    result = _screen(loaded, INSIDE)

    (ssurgo,) = result["results"]
    assert ssurgo["status"] == "complete"
    assert ssurgo["version_id"] == result["dataset_versions"]["ssurgo"]
    metrics = ssurgo["metrics"]
    assert metrics["covered_pct"] == pytest.approx(100, abs=0.01)
    classes = _classes(result)
    assert sum(c["area_m2"] for c in classes.values()) == pytest.approx(
        metrics["aoi_area_m2"], rel=1e-4
    )
    assert sum(c["pct_of_aoi"] for c in classes.values()) == pytest.approx(100, abs=0.05)
    expected = _independent_hydric_area(INSIDE, range(66, 100))
    assert expected > 0
    assert classes["hydric_66_99"]["area_m2"] == pytest.approx(expected, rel=1e-3)
    assert classes["hydric_0"]["area_m2"] == pytest.approx(
        _independent_hydric_area(INSIDE, range(0, 1)), rel=1e-3
    )


def test_partial_coverage_reports_uncovered_area_not_absence(
    loaded: sessionmaker[Session],
) -> None:
    (ssurgo,) = _screen(loaded, STRADDLING)["results"]

    assert ssurgo["status"] == "partial_coverage"
    covered = ssurgo["metrics"]["covered_pct"]
    assert covered == pytest.approx(50, abs=1)
    assert sum(c["pct_of_aoi"] for c in ssurgo["metrics"]["classes"]) == pytest.approx(
        covered, abs=0.05
    )


def test_aoi_outside_dataset_coverage_is_not_covered(loaded: sessionmaker[Session]) -> None:
    (ssurgo,) = _screen(loaded, OUTSIDE_COVERAGE)["results"]

    assert ssurgo["status"] == "not_covered"
    assert ssurgo["metrics"]["covered_pct"] == 0
    assert all(c["area_m2"] == 0 for c in ssurgo["metrics"]["classes"])


def test_dataset_without_active_version_is_unavailable(sessions: sessionmaker[Session]) -> None:
    from esp.catalog import ensure_dataset
    from esp.sources.ssurgo import INFO

    with sessions() as session:
        ensure_dataset(session, INFO)
        session.commit()

    (ssurgo,) = _screen(sessions, INSIDE)["results"]

    assert ssurgo["status"] == "unavailable" and ssurgo["version_id"] is None


def test_features_are_clipped_to_aoi_and_carry_hydric_class(loaded: sessionmaker[Session]) -> None:
    job = _submit(INSIDE)

    features = client.get(f"/api/screenings/{job['id']}/features/ssurgo").json()

    assert features["type"] == "FeatureCollection" and features["features"]
    union = shapely.union_all([shapely.geometry.shape(f["geometry"]) for f in features["features"]])
    assert INSIDE.buffer(1e-9).contains(union)
    assert union.area == pytest.approx(INSIDE.area, rel=1e-6)
    assert {f["properties"]["class"] for f in features["features"]} >= {"hydric_0", "hydric_66_99"}


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        (
            {
                "type": "Polygon",
                "coordinates": [
                    [[-105, 40], [-104.9, 40.1], [-104.9, 40], [-105, 40.1], [-105, 40]]
                ],
            },
            "invalid",
        ),
        (mapping(box(-110.5, 40, -110.4, 40.1)), "within Colorado"),
        (mapping(box(-105.5, 39.5, -105.0, 40.0)), "accepts up to"),
    ],
)
def test_rejects_unusable_aois(database_url: str, geometry: dict[str, Any], message: str) -> None:
    response = client.post("/api/screenings", json={"name": "x", "geometry": geometry})

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_rejects_non_polygon_geometry(database_url: str) -> None:
    response = client.post(
        "/api/screenings",
        json={"name": "x", "geometry": {"type": "Point", "coordinates": [-105, 40]}},
    )
    assert response.status_code == 422


def test_idempotency_key_returns_the_same_screening(loaded: sessionmaker[Session]) -> None:
    first = _submit(INSIDE, **{"Idempotency-Key": "abc-123"})
    second = _submit(INSIDE, **{"Idempotency-Key": "abc-123"})

    assert first["id"] == second["id"]


def test_dataset_failure_is_isolated(
    loaded: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setitem(jobs.SCREENERS, "ssurgo", broken)

    result = _screen(loaded, INSIDE)

    (ssurgo,) = result["results"]
    assert ssurgo["status"] == "failed" and ssurgo["error"] == "boom"


def test_transient_job_failure_is_retried_without_duplicating_results(
    loaded: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_upsert = jobs._upsert_result
    calls = {"n": 0}

    def flaky(session: Session, values: dict[str, Any]) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("database went away")
        real_upsert(session, values)

    monkeypatch.setattr(jobs, "_upsert_result", flaky)
    monkeypatch.setattr(jobs, "RETRY_DELAY_SECONDS", 0)
    job = _submit(INSIDE)

    _run_all(loaded)

    result = client.get(f"/api/screenings/{job['id']}").json()
    assert result["status"] == "succeeded" and result["attempts"] == 2
    with loaded() as session:
        rows = session.execute(
            text("SELECT count(*) FROM screening_results WHERE job_id = :j"), {"j": job["id"]}
        ).scalar_one()
    assert rows == 1


def test_job_abandoned_by_a_dead_worker_is_reclaimed(loaded: sessionmaker[Session]) -> None:
    job = _submit(INSIDE)
    with loaded() as session:
        session.execute(
            text(
                "UPDATE screening_jobs SET status = 'running', attempts = 1, locked_by = 'dead',"
                " locked_at = now() - interval '1 hour' WHERE id = :j"
            ),
            {"j": job["id"]},
        )
        session.commit()

    _run_all(loaded)

    with loaded() as session:
        reclaimed = session.get(ScreeningJob, job["id"])
        assert reclaimed is not None
        assert reclaimed.status == "succeeded" and reclaimed.locked_by == "test-worker"


def test_datasets_endpoint_reports_active_version_and_last_run(
    loaded: sessionmaker[Session],
) -> None:
    (ssurgo,) = client.get("/api/datasets").json()

    assert ssurgo["id"] == "ssurgo"
    assert ssurgo["active_version"]["provider_release"] == RELEASE
    assert ssurgo["active_version"]["stats"]["polygons"] == 64
    assert ssurgo["last_run"]["status"] == "succeeded"
