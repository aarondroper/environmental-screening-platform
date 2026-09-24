from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.ingestion import ingest_ssurgo_regional_packages
from environmental_screening_platform.ssurgo_packages import (
    SsurgoPackageSpec,
    validate_ssurgo_package,
)


class PackageResponse:
    def __init__(self, body: bytes, url: str, *, status_code: int = 200) -> None:
        self.body = body
        self.url = url
        self.status_code = status_code
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/.zip",
            "ETag": '"fixture"',
            "Last-Modified": "Thu, 24 Sep 2026 00:00:00 GMT",
            "Accept-Ranges": "bytes",
        }

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, _size: int):
        yield self.body

    def close(self) -> None:
        return


class PackageSession:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs: Any) -> PackageResponse:
        self.calls.append(url)
        body = self.bodies[url]
        return PackageResponse(body, url)


def _package_bytes(symbol: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"soil_{symbol.lower()}/spatial/mupolygon.shp", b"shape fixture")
        archive.writestr(f"soil_{symbol.lower()}/tabular/soils.txt", b"tabular fixture")
    return stream.getvalue()


def _sizing_record(path: Path, *, bad_symbol: str | None = None) -> dict[str, Any]:
    symbols = [
        "CO001",
        "CO075",
        "CO087",
        "CO617",
        "CO618",
        "CO641",
        "CO642",
        "CO643",
        "CO644",
        "CO645",
        "CO646",
        "CO647",
        "CO650",
        "CO651",
        "NE105",
        "WY601",
        "WY621",
        "WY632",
        "WY721",
    ]
    areas = []
    for index, symbol in enumerate(symbols):
        url = f"https://websoilsurvey.sc.egov.usda.gov/test/{symbol}.zip"
        body = _package_bytes(symbol)
        areas.append(
            {
                "areasymbol": symbol,
                "areaname": f"{symbol} fixture survey area",
                "provider_package_identifier": f"wss_SSA_{symbol}.zip",
                "saversion": 1,
                "saverest_provider": "2026-09-24",
                "package_url": url,
                "format": "SSURGO survey-area ZIP",
                "compressed_size_bytes": len(body) + (1 if symbol == bad_symbol else 0),
                "size_status": "reported_by_provider_http_content_length",
                "mapunit_count": index + 1,
            }
        )
    record = {
        "approved_boundary": {
            "counties": [
                {"geoid": "08013"},
                {"geoid": "08069"},
                {"geoid": "08123"},
            ],
            "vintage": 2025,
            "union_geometry_type": "MultiPolygon",
            "union_component_count": 3,
            "union_valid": True,
        },
        "survey_areas": areas,
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return record


def test_package_validator_checks_crc_structure_and_identifier() -> None:
    spec = SsurgoPackageSpec(
        areasymbol="CO001",
        areaname="fixture",
        provider_package_identifier="fixture.zip",
        saversion=1,
        saverest_provider="2026-09-24",
        package_url="https://websoilsurvey.sc.egov.usda.gov/CO001.zip",
        format="SSURGO survey-area ZIP",
        provider_reported_size_bytes=1,
        mapunit_count=1,
    )
    validation = validate_ssurgo_package(_package_bytes("CO001"), spec)
    assert validation["archive_valid"] is True
    assert validation["crc_test"] == "passed"
    assert validation["has_spatial_directory"] is True
    assert validation["has_tabular_directory"] is True


def test_regional_acquisition_records_all_packages_as_inactive_candidates(tmp_path: Path) -> None:
    sizing_path = tmp_path / "sizing.json"
    record = _sizing_record(sizing_path)
    bodies = {
        row["package_url"]: _package_bytes(row["areasymbol"]) for row in record["survey_areas"]
    }
    repository = SQLiteSourceRepository(tmp_path)
    batch = ingest_ssurgo_regional_packages(
        tmp_path,
        sizing_record=sizing_path,
        repository=repository,
        session=PackageSession(bodies),
    )

    assert batch["status"] == "completed_validation_only"
    assert batch["acquired_count"] == 19
    assert batch["validated_archive_count"] == 19
    assert batch["promotion_status"] == "not_promoted"
    assert batch["production_ready"] is False
    candidates = repository.list_candidates("ssurgo")
    assert len(candidates) == 19
    assert {candidate["status"] for candidate in candidates} == {"incomplete"}
    assert len(repository.list_versions("ssurgo")) == 19
    assert repository.get_active("ssurgo") is None
    assert all(
        candidate["validation"]["metrics"]["size_status"]
        == "provider_reported_and_locally_measured"
        for candidate in candidates
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    package_entries = [
        entry for entry in manifest["artifacts"] if "survey-area package" in entry["source"]
    ]
    assert len(package_entries) == 19
    assert all(
        entry["provider_reported_size_bytes"] == entry["actual_size_bytes"]
        for entry in package_entries
    )


def test_regional_acquisition_retains_bad_package_failure_and_other_results(tmp_path: Path) -> None:
    sizing_path = tmp_path / "sizing.json"
    record = _sizing_record(sizing_path)
    bodies = {
        row["package_url"]: _package_bytes(row["areasymbol"]) for row in record["survey_areas"]
    }
    bad_url = next(
        row["package_url"] for row in record["survey_areas"] if row["areasymbol"] == "CO001"
    )
    bodies[bad_url] = b"not a zip archive"
    repository = SQLiteSourceRepository(tmp_path)
    batch = ingest_ssurgo_regional_packages(
        tmp_path,
        sizing_record=sizing_path,
        repository=repository,
        session=PackageSession(bodies),
    )

    assert batch["status"] == "failed"
    assert batch["failed_count"] == 1
    failed = [
        candidate
        for candidate in repository.list_candidates("ssurgo")
        if candidate["status"] == "failed"
    ]
    assert len(failed) == 1
    assert failed[0]["artifact_path"] is not None
    assert Path(failed[0]["artifact_path"]).is_file()
    assert (
        len(
            [
                candidate
                for candidate in repository.list_candidates("ssurgo")
                if candidate["status"] == "incomplete"
            ]
        )
        == 18
    )
    assert repository.get_active("ssurgo") is None
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert any("CO001" in entry["source"] for entry in manifest["failed_attempts"])


def test_regional_acquisition_rejects_provider_size_mismatch(tmp_path: Path) -> None:
    sizing_path = tmp_path / "sizing.json"
    record = _sizing_record(sizing_path, bad_symbol="CO001")
    bodies = {
        row["package_url"]: _package_bytes(row["areasymbol"]) for row in record["survey_areas"]
    }
    repository = SQLiteSourceRepository(tmp_path)
    batch = ingest_ssurgo_regional_packages(
        tmp_path,
        sizing_record=sizing_path,
        repository=repository,
        session=PackageSession(bodies),
    )
    assert batch["failed_count"] == 1
    failed = next(
        candidate
        for candidate in repository.list_candidates("ssurgo")
        if candidate["status"] == "failed"
    )
    assert "provider size changed" in failed["error"]["message"]


def test_repeated_regional_acquisition_reuses_content_addressed_versions(tmp_path: Path) -> None:
    sizing_path = tmp_path / "sizing.json"
    record = _sizing_record(sizing_path)
    bodies = {
        row["package_url"]: _package_bytes(row["areasymbol"]) for row in record["survey_areas"]
    }
    repository = SQLiteSourceRepository(tmp_path)
    first = ingest_ssurgo_regional_packages(
        tmp_path,
        sizing_record=sizing_path,
        repository=repository,
        session=PackageSession(bodies),
    )
    second = ingest_ssurgo_regional_packages(
        tmp_path,
        sizing_record=sizing_path,
        repository=repository,
        session=PackageSession(bodies),
    )

    assert first["status"] == second["status"] == "completed_validation_only"
    assert len(repository.list_versions("ssurgo")) == 19
    assert len(repository.list_candidates("ssurgo")) == 38
    assert repository.get_active("ssurgo") is None
