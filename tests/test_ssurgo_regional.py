from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import shapefile
from pyproj import CRS
from shapely.geometry import box

from environmental_screening_platform.ssurgo_packages import SsurgoPackageSpec
from environmental_screening_platform.ssurgo_regional import validate_ssurgo_package_archive

WGS84_WKT = CRS.from_epsg(4326).to_wkt()
LAYERS = {
    "soilmu_a": shapefile.POLYGON,
    "soilmu_l": shapefile.POLYLINE,
    "soilmu_p": shapefile.POINT,
    "soilsa_a": shapefile.POLYGON,
    "soilsf_l": shapefile.POLYLINE,
    "soilsf_p": shapefile.POINT,
}


def _write_layer(root: Path, layer: str, symbol: str, *, invalid: bool) -> None:
    spatial = root / "spatial"
    spatial.mkdir(parents=True, exist_ok=True)
    path = spatial / f"{layer}_{symbol.lower()}"
    writer = shapefile.Writer(str(path), shapeType=LAYERS[layer])
    if layer == "soilmu_a":
        writer.field("AREASYMBOL", "C", size=20)
        writer.field("MUKEY", "C", size=30)
        if invalid:
            writer.poly([[(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)]])
        else:
            writer.poly([[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]])
        writer.record(symbol, "100")
    else:
        writer.field("ID", "C", size=20)
    writer.close()
    path.with_suffix(".prj").write_text(WGS84_WKT, encoding="utf-8")


def _row(values: dict[int, str], width: int) -> list[str]:
    row = [""] * width
    for index, value in values.items():
        row[index] = value
    return row


def _write_table(root: Path, name: str, rows: list[list[str]]) -> None:
    tabular = root / "tabular"
    tabular.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter="|", quotechar='"', lineterminator="\n").writerows(rows)
    (tabular / name).write_text(stream.getvalue(), encoding="utf-8")


def _package_zip(tmp_path: Path, *, invalid: bool = False, bad_join: bool = False) -> Path:
    symbol = "CO001"
    root = tmp_path / symbol
    for layer in LAYERS:
        _write_layer(root, layer, symbol, invalid=invalid)
    (root / "spatial" / "version.txt").write_text("2.3.3\n", encoding="utf-8")
    _write_table(
        root,
        "mapunit.txt",
        [_row({0: "M1", 1: "Example map unit", 22: "L1", 23: "100"}, 24)],
    )
    component_mukey = "999" if bad_join else "100"
    _write_table(
        root,
        "comp.txt",
        [
            _row(
                {
                    1: "50",
                    21: "Farmable under natural conditions",
                    22: "Yes",
                    107: component_mukey,
                    108: "100:1",
                },
                109,
            )
        ],
    )
    _write_table(root, "legend.txt", [["", symbol, "Example survey area"]])
    _write_table(root, "sacatlog.txt", [[symbol, "Example survey area", "1", "09/24/2026"]])
    (root / "tabular" / "version.txt").write_text("2.3.3\n", encoding="utf-8")

    archive_path = tmp_path / f"{symbol}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(root.rglob("*")):
            if member.is_file():
                archive.write(member, member.relative_to(tmp_path).as_posix())
    return archive_path


def _spec() -> SsurgoPackageSpec:
    return SsurgoPackageSpec(
        areasymbol="CO001",
        areaname="Example survey area",
        provider_package_identifier="fixture.zip",
        saversion=1,
        saverest_provider="2026-09-24",
        package_url="https://websoilsurvey.sc.egov.usda.gov/CO001.zip",
        format="SSURGO survey-area ZIP",
        provider_reported_size_bytes=1,
        mapunit_count=1,
    )


def test_regional_validator_reads_actual_ssurgo_layers_tables_and_hydric_fields(
    tmp_path: Path,
) -> None:
    report = validate_ssurgo_package_archive(_package_zip(tmp_path), _spec(), box(-1, -1, 2, 2))

    assert report["status"] == "passed"
    assert report["archive"]["spatial_version"] == "2.3.3"
    assert report["spatial_layers"]["soilmu_a"]["crs"] == "EPSG:4326"
    assert report["spatial_layers"]["soilmu_a"]["record_count"] == 1
    assert report["tabular"]["unique_mapunit_count"] == 1
    assert report["tabular"]["unique_component_count"] == 1
    assert report["tabular"]["hydricrating_nonempty_count"] == 1
    assert report["coverage"]["coverage_status"] == "intersects"


def test_regional_validator_reports_invalid_original_geometry_without_repair(
    tmp_path: Path,
) -> None:
    archive = _package_zip(tmp_path, invalid=True)
    before = archive.read_bytes()
    report = validate_ssurgo_package_archive(archive, _spec(), box(-1, -1, 2, 2))

    assert report["status"] == "failed"
    invalid = report["spatial_layers"]["soilmu_a"]["invalid_geometries"]
    assert len(invalid) == 1
    assert invalid[0]["record_index"] == 0
    assert archive.read_bytes() == before


def test_regional_validator_reports_mapunit_component_referential_failure(tmp_path: Path) -> None:
    report = validate_ssurgo_package_archive(
        _package_zip(tmp_path, bad_join=True), _spec(), box(-1, -1, 2, 2)
    )

    assert report["status"] == "failed"
    assert report["tabular"]["missing_component_mapunit_ids"] == ["999"]


def test_regional_validator_retains_corrupt_archive_failure(tmp_path: Path) -> None:
    archive = tmp_path / "CO001.zip"
    archive.write_bytes(b"not a zip archive")

    report = validate_ssurgo_package_archive(archive, _spec(), box(-1, -1, 2, 2))

    assert report["status"] == "failed"
    assert "BadZipFile" in report["issues"][0]
