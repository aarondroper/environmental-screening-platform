from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import Polygon, mapping

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.ssurgo_aoi import (
    SsurgoPlanRejected,
    build_sda_discovery_query,
    ingest_ssurgo_aoi,
    parse_sda_discovery,
    resolve_package,
)
from environmental_screening_platform.workflow import create_project


class _Response:
    def __init__(self, body: bytes, url: str, *, content_type: str) -> None:
        self.body = body
        self.url = url
        self.status_code = 200
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
            "ETag": '"fixture"',
            "Last-Modified": "Thu, 24 Sep 2026 00:00:00 GMT",
        }

    def raise_for_status(self) -> None:
        return

    def iter_content(self, _size: int):
        yield self.body

    def close(self) -> None:
        return


class _Session:
    def __init__(self, discovery: bytes, packages: dict[str, bytes]) -> None:
        self.discovery = discovery
        self.packages = packages
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.post_calls.append({"url": url, **kwargs})
        return _Response(self.discovery, url, content_type="application/json")

    def get(self, url: str, **_kwargs: Any) -> _Response:
        self.get_calls.append(url)
        return _Response(self.packages[url], url, content_type="application/.zip")


def _package(symbol: str, *, valid: bool = True) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if valid:
            archive.writestr(f"soil_{symbol.lower()}/spatial/mupolygon.shp", b"shape")
            archive.writestr(f"soil_{symbol.lower()}/tabular/soils.txt", b"tabular")
        else:
            archive.writestr("unrelated/readme.txt", b"not a package")
    return stream.getvalue()


def _project(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    data_root = tmp_path / "external"
    aoi_path = tmp_path / "aoi.geojson"
    aoi_path.write_text(
        json.dumps(
            mapping(
                Polygon(
                    [
                        (-77.04, 38.90),
                        (-77.04, 38.905),
                        (-77.03, 38.905),
                        (-77.03, 38.90),
                        (-77.04, 38.90),
                    ]
                )
            )
        ),
        encoding="utf-8",
    )
    return data_root, create_project("generic SSURGO", aoi_path, data_root)


def _discovery(symbol: str = "DC001") -> bytes:
    return json.dumps(
        {
            "Table": [
                [
                    "areasymbol",
                    "areaname",
                    "saversion",
                    "saverest",
                    "mbrminx",
                    "mbrminy",
                    "mbrmaxx",
                    "mbrmaxy",
                ],
                [
                    symbol,
                    "District of Columbia",
                    "19",
                    "9/9/2025 1:02:53 AM",
                    -77.1,
                    38.7,
                    -76.9,
                    39.0,
                ],
            ],
        }
    ).encode()


def test_discovery_query_and_package_url_are_dynamic() -> None:
    geometry = Polygon([(-77.1, 38.8), (-77.1, 38.9), (-77.0, 38.9), (-77.0, 38.8)])
    query = build_sda_discovery_query(geometry)
    assert "SDA_Get_Areasymbol_from_intersection_with_WktWgs84" in query
    assert "sacatalog" in query
    area = parse_sda_discovery(_discovery())[0]
    package = resolve_package(area)
    assert package["areasymbol"] == "DC001"
    assert package["package_url"].endswith("wss_SSA_DC001_soildb_US_2003_[2025-09-09].zip")


def test_generic_ssurgo_acquisition_plans_before_download_and_stays_inactive(
    tmp_path: Path,
) -> None:
    data_root, created = _project(tmp_path)
    package_area = resolve_package(parse_sda_discovery(_discovery())[0])
    session = _Session(_discovery(), {package_area["package_url"]: _package("DC001")})

    result = ingest_ssurgo_aoi(
        data_root,
        project_id=created["project"]["project_id"],
        session=session,
    )

    assert result["status"] == "completed_validation_only"
    assert result["plan"]["plan_status"] == "ready"
    assert result["plan"]["aoi"]["geometry_sha256"] == created["aoi_revision"]["geometry_sha256"]
    assert len(session.post_calls) == 1
    assert session.get_calls == [package_area["package_url"]] * 2  # preflight, then body
    candidates = SQLiteSourceRepository(data_root).list_candidates("ssurgo")
    assert len(candidates) == 1
    assert candidates[0]["status"] == "incomplete"
    assert candidates[0]["promotion_status"] == "not_promoted"
    assert candidates[0]["aoi_id"] == created["aoi_revision"]["aoi_id"]
    assert (
        candidates[0]["validation"]["source_provenance"]["aoi_geometry_sha256"]
        == created["aoi_revision"]["geometry_sha256"]
    )
    manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    assert any(item.get("plan_id") == result["plan"]["plan_id"] for item in manifest["artifacts"])


def test_repeated_discovery_produces_same_plan_identity(tmp_path: Path) -> None:
    data_root, created = _project(tmp_path)
    package_area = resolve_package(parse_sda_discovery(_discovery())[0])
    session = _Session(_discovery(), {package_area["package_url"]: _package("DC001")})

    first = ingest_ssurgo_aoi(
        data_root,
        project_id=created["project"]["project_id"],
        session=session,
    )
    second = ingest_ssurgo_aoi(
        data_root,
        project_id=created["project"]["project_id"],
        session=session,
    )

    assert first["plan"]["plan_id"] == second["plan"]["plan_id"]
    assert len(SQLiteSourceRepository(data_root).list_candidates("ssurgo")) == 2


def test_total_limit_rejects_after_metadata_preflight_without_package_body(tmp_path: Path) -> None:
    data_root, created = _project(tmp_path)
    package_area = resolve_package(parse_sda_discovery(_discovery())[0])
    session = _Session(_discovery(), {package_area["package_url"]: _package("DC001")})

    with pytest.raises(SsurgoPlanRejected, match="configured total limit"):
        ingest_ssurgo_aoi(
            data_root,
            project_id=created["project"]["project_id"],
            session=session,
            max_total_bytes=1,
        )
    assert session.get_calls == [package_area["package_url"]]
    assert not SQLiteSourceRepository(data_root).list_candidates("ssurgo")


def test_invalid_package_is_retained_as_failed_candidate(tmp_path: Path) -> None:
    data_root, created = _project(tmp_path)
    package_area = resolve_package(parse_sda_discovery(_discovery())[0])
    session = _Session(_discovery(), {package_area["package_url"]: _package("DC001", valid=False)})

    result = ingest_ssurgo_aoi(
        data_root,
        project_id=created["project"]["project_id"],
        session=session,
    )

    assert result["status"] == "partial_failure"
    candidate = SQLiteSourceRepository(data_root).list_candidates("ssurgo")[0]
    assert candidate["status"] == "failed"
    assert "lacks expected" in candidate["error"]["message"]
    assert candidate["acquisition_attempts"]
