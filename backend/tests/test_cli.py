import json
import shutil
from pathlib import Path

import pytest

from esp.cli import main
from esp.config import get_settings
from tests.ssurgo_packages import FIXTURE


def test_ingest_from_package_dir_then_rerun_is_unchanged(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    packages = tmp_path / "packages"
    packages.mkdir()
    shutil.copy(FIXTURE, packages / "CO644.zip")
    monkeypatch.setenv("ESP_RAW_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()

    assert main(["ingest", "ssurgo", "--areas", "co644", "--package-dir", str(packages)]) == 0
    first = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert main(["ingest", "ssurgo", "--areas", "CO644", "--package-dir", str(packages)]) == 0
    second = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert first["status"] == "succeeded"
    assert second == {
        **first,
        "status": "unchanged",
        "run_id": second["run_id"],
        "promoted": "False",
    }
    assert list((tmp_path / "raw" / "ssurgo").rglob("*.zip"))
