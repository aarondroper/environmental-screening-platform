import shutil
import zipfile
from pathlib import Path

import pytest
from shapely.geometry import box
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from esp.catalog import active_version
from esp.ingest import ingest_ssurgo
from esp.models import DatasetVersion, IngestionRun, RawSnapshot
from esp.sources.ssurgo import SchemaError
from tests.ssurgo_packages import FIXTURE, build_package

RELEASE = {"CO644": "2025-08-29T16:38:56"}


class LocalPackages:
    """PackageSource serving local ZIPs instead of Web Soil Survey."""

    def __init__(self, package: Path, releases: dict[str, str]) -> None:
        self.package, self._releases, self.downloads = package, releases, 0

    def releases(self, areas: list[str]) -> dict[str, str]:
        return {a: self._releases[a] for a in areas}

    def download(self, area: str, release: str, dest_dir: Path) -> tuple[str, Path]:
        self.downloads += 1
        dest = dest_dir / f"{area}.zip"
        shutil.copy(self.package, dest)
        return f"file://{self.package}", dest


def _ingest(sessions: sessionmaker[Session], source: LocalPackages, raw_dir: Path):  # type: ignore[no-untyped-def]
    return ingest_ssurgo(sessions, source, ["CO644"], raw_dir)


def test_ingest_loads_validates_and_promotes(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    outcome = _ingest(sessions, LocalPackages(FIXTURE, RELEASE), tmp_path)

    assert outcome.status == "succeeded" and outcome.promoted
    with sessions() as session:
        version = active_version(session, "ssurgo")
        assert version is not None and version.id == outcome.version_id
        assert version.status == "active"
        assert version.provider_release == RELEASE
        assert version.validation is not None and version.validation["passed"]
        assert version.stats is not None
        assert version.stats["polygons"] == 64 and version.stats["mapunits"] == 21
        counts = session.execute(
            text(
                "SELECT count(*), count(DISTINCT ST_SRID(geom)), bool_and(ST_IsValid(geom))"
                " FROM ssurgo_polygons WHERE version_id = :v"
            ),
            {"v": version.id},
        ).one()
        assert tuple(counts) == (64, 1, True)
        snapshot = session.scalars(select(RawSnapshot)).one()
        assert Path(snapshot.storage_path).read_bytes() == FIXTURE.read_bytes()
        assert snapshot.provider_release == "CO644 saverest 2025-08-29T16:38:56"


def test_unchanged_release_skips_download(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    source = LocalPackages(FIXTURE, RELEASE)
    first = _ingest(sessions, source, tmp_path)
    second = _ingest(sessions, source, tmp_path)

    assert second.status == "unchanged" and second.version_id == first.version_id
    assert source.downloads == 1


def test_new_release_with_identical_content_is_not_reloaded(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    first = _ingest(sessions, LocalPackages(FIXTURE, RELEASE), tmp_path)
    again = _ingest(sessions, LocalPackages(FIXTURE, {"CO644": "2026-10-01T00:00:00"}), tmp_path)

    assert again.status == "unchanged" and again.version_id == first.version_id
    with sessions() as session:
        assert session.scalar(select(text("count(*)")).select_from(DatasetVersion)) == 1


def _mapunit_tables(package: Path) -> tuple[list[list[str]], list[list[str]]]:
    import csv
    import io

    with zipfile.ZipFile(package) as zf:

        def read(name: str) -> list[list[str]]:
            with zf.open(f"CO644/tabular/{name}") as raw:
                return list(csv.reader(io.TextIOWrapper(raw, encoding="utf-8"), delimiter="|"))

        return read("mapunit.txt"), read("muaggatt.txt")


def test_failed_validation_keeps_previous_version_active(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    good = _ingest(sessions, LocalPackages(FIXTURE, RELEASE), tmp_path / "raw")
    mapunit, muaggatt = _mapunit_tables(FIXTURE)
    # Polygons fill only a quarter of the declared survey-area boundary: truncated upstream data.
    mukey = mapunit[0][-1]
    bad_package = build_package(
        tmp_path / "bad.zip",
        "CO644",
        mapunit,
        muaggatt,
        [(mukey, box(-105.08, 40.57, -105.06, 40.585))],
        box(-105.08, 40.57, -105.04, 40.60),
    )

    bad = _ingest(
        sessions, LocalPackages(bad_package, {"CO644": "2026-10-01T00:00:00"}), tmp_path / "raw"
    )

    assert bad.status == "failed"
    with sessions() as session:
        active = active_version(session, "ssurgo")
        assert active is not None and active.id == good.version_id
        failed = session.get(DatasetVersion, bad.version_id)
        assert failed is not None and failed.status == "failed"
        assert failed.validation is not None
        failing = {c["name"] for c in failed.validation["checks"] if not c["passed"]}
        assert failing == {"polygons_fill_survey_areas", "no_large_drop_vs_active"}
        rows = session.execute(
            text("SELECT count(*) FROM ssurgo_polygons WHERE version_id = :v"),
            {"v": bad.version_id},
        ).scalar_one()
        assert rows == 0
        run = session.get(IngestionRun, bad.run_id)
        assert run is not None and run.status == "failed" and run.error == "validation failed"


def test_schema_change_fails_run_without_touching_active(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    good = _ingest(sessions, LocalPackages(FIXTURE, RELEASE), tmp_path / "raw")
    mapunit, muaggatt = _mapunit_tables(FIXTURE)
    changed = build_package(
        tmp_path / "changed.zip",
        "CO644",
        mapunit,
        [row[:-2] + row[-1:] for row in muaggatt],  # upstream dropped a column
        [(mapunit[0][-1], box(-105.08, 40.57, -105.04, 40.60))],
        box(-105.08, 40.57, -105.04, 40.60),
    )

    with pytest.raises(SchemaError):
        _ingest(
            sessions, LocalPackages(changed, {"CO644": "2026-10-01T00:00:00"}), tmp_path / "raw"
        )

    with sessions() as session:
        active = active_version(session, "ssurgo")
        assert active is not None and active.id == good.version_id
        latest = session.scalars(
            select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1)
        ).one()
        assert latest.status == "failed" and "muaggatt.txt" in (latest.error or "")
