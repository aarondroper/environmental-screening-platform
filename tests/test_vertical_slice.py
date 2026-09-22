from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import shapefile
from pyproj import CRS
from rasterio import Affine
from shapely.geometry import Polygon, mapping

from environmental_screening_platform.adapters import (
    ProviderData,
    _horn_slope,
    acquire_nlcd,
    acquire_ssurgo,
    non_operational_sources,
    parse_boundary_archive,
    unavailable,
)
from environmental_screening_platform.models import (
    Acquisition,
    AttemptStatus,
    Coverage,
    Maturity,
    Observation,
    SourceResult,
    classify_constraint_observation,
)
from environmental_screening_platform.store import fetch_raw, read_json, write_json
from environmental_screening_platform.workflow import (
    create_job,
    create_project,
    export_result,
    retry_job,
    revise_aoi,
    run_job,
    transition_job,
)


def test_job_state_machine_rejects_illegal_transitions() -> None:
    assert transition_job("queued", "processing") == "processing"
    assert transition_job("processing", "completed") == "completed"
    assert transition_job("failed", "queued") == "queued"
    with pytest.raises(ValueError, match="Invalid job transition"):
        transition_job("completed", "queued")


@pytest.mark.parametrize(
    ("coverage", "maturity", "count", "expected"),
    [
        (Coverage.UNAVAILABLE, Maturity.VALIDATED, 0, Observation.UNAVAILABLE),
        (Coverage.PARTIAL, Maturity.VALIDATED, 0, Observation.NOT_COVERED),
        (Coverage.UNKNOWN, Maturity.VALIDATED, 0, Observation.INCOMPLETE_SOURCE),
        (Coverage.COMPLETE, Maturity.ACCESS_BLOCKED, 0, Observation.INCOMPLETE_SOURCE),
        (Coverage.COMPLETE, Maturity.VALIDATED, 0, Observation.INCOMPLETE_SOURCE),
        (Coverage.COMPLETE, Maturity.VALIDATED, 2, Observation.CONSTRAINT_OBSERVED),
    ],
)
def test_unknown_or_incomplete_never_becomes_absence(coverage, maturity, count, expected) -> None:
    assert (
        classify_constraint_observation(
            intersecting_features=count, coverage_status=coverage, validation_status=maturity
        )
        == expected
    )


def test_pending_and_quarantine_override_absence() -> None:
    assert (
        classify_constraint_observation(
            intersecting_features=0,
            coverage_status=Coverage.COMPLETE,
            validation_status=Maturity.VALIDATED,
            pending=True,
        )
        == Observation.PENDING_DATA
    )
    assert (
        classify_constraint_observation(
            intersecting_features=0,
            coverage_status=Coverage.COMPLETE,
            validation_status=Maturity.VALIDATED,
            quarantined=True,
        )
        == Observation.GEOMETRY_QUARANTINED
    )


def test_absence_requires_complete_validation_scope() -> None:
    assert (
        classify_constraint_observation(
            intersecting_features=0,
            coverage_status=Coverage.COMPLETE,
            validation_status=Maturity.VALIDATED,
            validation_scope_complete=True,
        )
        == Observation.NO_CONSTRAINT_OBSERVED
    )


def test_source_maturity_stays_distinct_from_attempt_failure() -> None:
    result = unavailable("annual_nlcd", RuntimeError("provider timeout"))
    assert result.validation_status == Maturity.VALIDATED
    assert result.attempt_status == AttemptStatus.FAILED
    assert result.coverage_status == Coverage.UNAVAILABLE
    assert result.observation_status == Observation.UNAVAILABLE
    assert result.metrics == {}
    padus, fema = non_operational_sources()
    assert padus.validation_status == Maturity.CONDITIONALLY_VALIDATED
    assert padus.observation_status == Observation.INCOMPLETE_SOURCE
    assert padus.metrics["prior_validation_sample"]["repaired_candidates_quarantined"] == 3
    assert fema.validation_status == Maturity.ACCESS_BLOCKED
    assert "Selected source; provider access blocked" in (fema.reason or "")


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        url: str = "https://provider.example/data",
        content_type: str = "application/octet-stream",
        status_code: int = 200,
    ) -> None:
        self.body = body
        self.url = url
        self.status_code = status_code
        self.headers = {"Content-Length": str(len(body)), "Content-Type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")
        return

    def iter_content(self, size: int):
        yield self.body

    def close(self) -> None:
        return


class FakeSession:
    def __init__(
        self,
        body: bytes = b"fixture bytes",
        content_type: str = "application/octet-stream",
        responses: list[FakeResponse] | None = None,
    ) -> None:
        self.body = body
        self.content_type = content_type
        self.responses = responses or []
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(self.body, url + "?v=1", self.content_type)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(self.body, url, self.content_type)


def test_raw_acquisition_records_checksum_and_exact_request(tmp_path: Path) -> None:
    session = FakeSession()
    raw_root = tmp_path / "external-data"
    body, acquired = fetch_raw(
        session,
        source_id="sample",
        provider="fixture provider",
        release="r1",
        url="https://provider.example/data",
        params={"year": 2025},
        data_root=raw_root,
        terms_url="https://provider.example/terms",
        max_bytes=100,
    )
    assert body == b"fixture bytes"
    assert acquired.sha256 == hashlib.sha256(body).hexdigest()
    assert acquired.size_bytes == len(body)
    assert Path(acquired.raw_path).read_bytes() == body
    event_path = next(Path(acquired.raw_path).parent.glob("acquisitions/*.json"))
    sidecar = read_json(event_path)
    assert sidecar["sha256"] == acquired.sha256
    assert sidecar["request_parameters"] == {"year": 2025}
    assert sidecar["source_url"] == "https://provider.example/data?v=1"
    _, second_acquisition = fetch_raw(
        session,
        source_id="sample",
        provider="fixture provider",
        release="r1",
        url="https://provider.example/data",
        params={"year": 2025},
        data_root=raw_root,
        terms_url="https://provider.example/terms",
        max_bytes=100,
    )
    assert second_acquisition.sha256 == acquired.sha256
    assert len(list(Path(acquired.raw_path).parent.glob("acquisitions/*.json"))) == 2


def test_raw_acquisition_is_bounded_and_requires_https(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        fetch_raw(
            FakeSession(),
            source_id="x",
            provider="x",
            release="x",
            url="http://bad.example",
            params=None,
            data_root=tmp_path,
            terms_url="https://example.org",
            max_bytes=100,
        )


def test_transient_provider_response_retries_then_records_success(tmp_path: Path) -> None:
    session = FakeSession(
        responses=[
            FakeResponse(b"temporary", status_code=503),
            FakeResponse(b"ok", url="https://provider.example/final"),
        ]
    )
    body, acquisition = fetch_raw(
        session,
        source_id="retry",
        provider="fixture",
        release="v1",
        url="https://provider.example",
        params=None,
        data_root=tmp_path,
        terms_url="https://provider.example/terms",
        max_bytes=100,
    )
    assert body == b"ok"
    assert acquisition.attempts == 2
    assert len(session.calls) == 2


def _geotiff_bytes(
    values: np.ndarray, *, crs: str, transform: Any, nodata: int | float | None
) -> bytes:
    from rasterio.io import MemoryFile

    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype=values.dtype,
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


def test_nlcd_window_metrics_are_deterministic_and_preserve_nodata(tmp_path: Path) -> None:
    from pyproj import Transformer
    from shapely.ops import transform as transform_geometry

    aoi = Polygon(
        [
            (-105.27, 40.01),
            (-105.269, 40.01),
            (-105.269, 40.011),
            (-105.27, 40.011),
            (-105.27, 40.01),
        ]
    )
    projected = transform_geometry(Transformer.from_crs(4326, 3857, always_xy=True).transform, aoi)
    minx, miny, maxx, maxy = projected.bounds
    raster_transform = Affine((maxx - minx) / 4, 0, minx, 0, -(maxy - miny) / 4, maxy)
    values = np.array(
        [[21, 21, 22, 22], [23, 23, 23, 250], [41, 41, 41, 41], [41, 41, 41, 41]], dtype="uint8"
    )
    body = _geotiff_bytes(values, crs="EPSG:3857", transform=raster_transform, nodata=250)
    first = acquire_nlcd(FakeSession(body, "image/tiff"), tmp_path / "raw1", aoi)
    second = acquire_nlcd(FakeSession(body, "image/tiff"), tmp_path / "raw2", aoi)
    assert first.result.metrics == second.result.metrics
    assert first.result.metrics["nodata_pixels"] == 1
    assert first.result.metrics["classes"]["21"]["class_name"] == "developed_open_space"
    assert first.result.observation_status == Observation.INCOMPLETE_SOURCE
    assert first.result.coverage_status == Coverage.PARTIAL


def test_ssurgo_components_keep_lineage_and_are_not_wetland_determinations(tmp_path: Path) -> None:
    aoi = Polygon(
        [
            (-105.27, 40.01),
            (-105.269, 40.01),
            (-105.269, 40.011),
            (-105.27, 40.011),
            (-105.27, 40.01),
        ]
    )
    table = [
        [
            "mukey",
            "musym",
            "muname",
            "cokey",
            "comppct_r",
            "hydricrating",
            "hydricon",
            "polygon_wkt",
        ],
        ["1", "A", "Unit A", "11", "65", "Yes", None, aoi.wkt],
        ["1", "A", "Unit A", "12", "35", "No", None, aoi.wkt],
    ]
    body = json.dumps({"Table": table}).encode()
    outcome = acquire_ssurgo(
        FakeSession(body, "application/json; charset=utf-8"), tmp_path / "ssurgo", aoi
    )
    metrics = outcome.result.metrics
    assert metrics["intersecting_mapunit_count"] == 1
    assert metrics["component_row_count"] == 2
    assert {row["cokey"] for row in metrics["component_hydric_indicators"]} == {"11", "12"}
    assert [row["comppct_r"] for row in metrics["component_hydric_indicators"]] == [65, 35]
    assert metrics["mapunit_coverage_fraction_of_aoi"] == 1.0
    assert "regulatory determination" in metrics["hydric_interpretation"]
    assert len(outcome.result.features) == 1
    assert outcome.result.features[0]["properties"]["mukey"] == "1"
    assert outcome.result.features[0]["geometry"]["type"] == "Polygon"
    with pytest.raises(ValueError, match="exceeds"):
        fetch_raw(
            FakeSession(b"too many bytes"),
            source_id="x",
            provider="x",
            release="x",
            url="https://provider.example",
            params=None,
            data_root=tmp_path,
            terms_url="https://example.org",
            max_bytes=3,
        )


def test_provider_redirect_must_remain_on_official_host(tmp_path: Path) -> None:
    session = FakeSession(
        responses=[FakeResponse(b"not trusted", url="https://unapproved.example/data")]
    )
    with pytest.raises(ValueError, match="unapproved host"):
        fetch_raw(
            session,
            source_id="redirect",
            provider="fixture",
            release="v1",
            url="https://provider.example/data",
            params=None,
            data_root=tmp_path,
            terms_url="https://provider.example/terms",
            max_bytes=100,
        )
    assert not (tmp_path / "raw").exists()


def test_2025_county_archive_parser_validates_exact_boundary_ids(tmp_path: Path) -> None:
    stem = tmp_path / "tl_2025_us_county"
    writer = shapefile.Writer(str(stem), shapeType=shapefile.POLYGON)
    writer.field("GEOID", "C", size=5)
    writer.field("NAME", "C", size=40)
    writer.field("STATEFP", "C", size=2)
    writer.field("COUNTYFP", "C", size=3)
    specs = [
        ("08013", "Boulder", "08", "013", -106.0),
        ("08069", "Larimer", "08", "069", -105.0),
        ("08123", "Weld", "08", "123", -104.0),
    ]
    for geoid, name, statefp, countyfp, x in specs:
        writer.poly([[(x, 40), (x + 0.2, 40), (x + 0.2, 40.2), (x, 40.2), (x, 40)]])
        writer.record(geoid, name, statefp, countyfp)
    writer.close()
    Path(f"{stem}.prj").write_text(CRS.from_epsg(4269).to_wkt())
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as archive:
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            archive.write(f"{stem}{suffix}", f"tl_2025_us_county{suffix}")
    body = package.getvalue()
    provenance = Acquisition(
        source_id="census_boundary",
        provider="US Census Bureau TIGER/Line",
        release="TIGER/Line 2025 county",
        source_url="https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip",
        acquired_at="2026-09-22T00:00:00+00:00",
        media_type="application/zip",
        raw_path="/external/fixture.zip",
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        terms_url="https://www.census.gov/",
    )
    result = parse_boundary_archive(body, provenance)
    assert result.result.metrics["county_geoids"] == ["08013", "08069", "08123"]
    assert result.result.metrics["union_components"] == 3
    assert result.result.metrics["crs"] == "EPSG:4269"


def test_horn_slope_is_reproducible_and_excludes_nodata() -> None:
    y, x = np.mgrid[0:7, 0:7]
    values = 2 * x + y
    valid = np.ones(values.shape, dtype=bool)
    first = _horn_slope(values, valid, 10, 10, valid)
    second = _horn_slope(values, valid, 10, 10, valid)
    assert np.array_equal(first, second)
    assert np.allclose(first, np.degrees(np.arctan(np.sqrt(0.2**2 + 0.1**2))))
    valid[3, 3] = False
    with_nodata = _horn_slope(values, valid, 10, 10, valid)
    assert len(with_nodata) < len(first)


def _cached_boundary(data_root: Path, polygon: Polygon) -> None:
    write_json(
        data_root / "workspace/reference/approved_counties.geojson",
        {
            "type": "FeatureCollection",
            "crs": "EPSG:4269",
            "features": [
                {"type": "Feature", "geometry": mapping(polygon), "properties": {"GEOID": "08013"}}
            ],
            "union_metrics": {
                "county_geoids": ["08013", "08069", "08123"],
                "union_area_sqmi": 7391.206,
            },
            "provenance": {"sha256": "boundary-fixture"},
        },
    )


def _aoi_file(tmp_path: Path, filename: str, bounds: tuple[float, float, float, float]) -> Path:
    x0, y0, x1, y1 = bounds
    polygon = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
    path = tmp_path / filename
    path.write_text(json.dumps({"type": "Feature", "geometry": mapping(polygon), "properties": {}}))
    return path


def _fixture_provider(source_id: str) -> ProviderData:
    result = SourceResult(
        source_id=source_id,
        validation_status=Maturity.VALIDATED,
        validation_scope="small deterministic test fixture",
        coverage_status=Coverage.COMPLETE,
        observation_status=Observation.DATA_OBSERVED,
        product_status="fixture",
        attempt_status=AttemptStatus.VALIDATED,
        metrics={"stable_count": 2},
        provenance={"sha256": "fixture-checksum", "version": "fixture-v1"},
    )
    return ProviderData(result, value={"fixture": True})


def test_project_aoi_revision_job_retry_unknown_handling_and_export(tmp_path: Path) -> None:
    data_root = tmp_path / "external-data"
    _cached_boundary(
        data_root, Polygon([(-106, 39), (-103, 39), (-103, 42), (-106, 42), (-106, 39)])
    )
    aoi_path = _aoi_file(tmp_path, "aoi.geojson", (-105.5, 40, -105.4, 40.1))
    project_data = create_project("fixture case", aoi_path, data_root)
    project_id = project_data["project"]["project_id"]
    revision_one = project_data["aoi_revision"]
    revision_two = revise_aoi(
        project_id, _aoi_file(tmp_path, "aoi-2.geojson", (-105.4, 40, -105.3, 40.1)), data_root
    )
    assert revision_one["aoi_id"] != revision_two["aoi_id"]
    assert (
        read_json(
            data_root
            / f"workspace/projects/{project_id}/aoi-revisions/{revision_one['aoi_id']}.json"
        )["revision"]
        == 1
    )

    job = create_job(project_id, data_root, revision_one["aoi_id"])
    complete = run_job(job["job_id"], data_root)
    assert complete["job_status"] == "completed"
    assert complete["job_attempt"] == 1
    assert len(complete["source_snapshot_ids"]) == 6
    assert set(complete["sources_without_active_version"]) == {
        "census_boundary",
        "annual_nlcd",
        "3dep",
        "ssurgo",
        "padus",
        "fema_nfhl",
    }
    assert [x["source_id"] for x in complete["source_results"]] == [
        "census_boundary",
        "annual_nlcd",
        "3dep",
        "ssurgo",
        "padus",
        "fema_nfhl",
    ]
    assert complete["source_results"][-2]["observation_status"] == "geometry_quarantined"
    assert (
        complete["source_results"][-2]["metrics"]["prior_validation_sample"][
            "repaired_candidates_quarantined"
        ]
        == 3
    )
    assert complete["source_results"][-1]["observation_status"] == "unavailable"
    assert complete["source_results"][-1]["metrics"] == {}
    assert complete["source_results"][0]["snapshot_status"] == "unknown"
    assert "No composite suitability score" in complete["limitations_notice"]

    outputs = export_result(job["job_id"], data_root, tmp_path / "exports")
    assert len(outputs) == 3
    exported = json.loads(outputs[0].read_text())
    assert exported["source_results"][-1]["coverage_status"] == "unavailable"
    assert exported["job_id"] == job["job_id"]
    assert exported["source_snapshot_ids"] == complete["source_snapshot_ids"]
    csv_content = outputs[1].read_text()
    assert "source_snapshot_id" in csv_content
    assert "fema_nfhl" in csv_content and "blocked" in csv_content
    geojson = json.loads(outputs[2].read_text())
    assert geojson["type"] == "FeatureCollection"
    assert geojson["features"][0]["properties"]["feature_type"] == "aoi_boundary"
    assert (
        "absent source features are not a no-constraint conclusion" in geojson["properties"]["note"]
    )

    with pytest.raises(ValueError, match="Only failed jobs"):
        retry_job(job["job_id"], data_root)


def test_raw_data_root_cannot_be_inside_repository(tmp_path: Path) -> None:
    from environmental_screening_platform.workflow import _ensure_external_data_root

    with pytest.raises(ValueError, match="outside the project repository"):
        _ensure_external_data_root(Path(__file__).resolve().parents[1] / "runtime-data")
