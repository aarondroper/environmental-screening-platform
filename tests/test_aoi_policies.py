from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon, mapping

from environmental_screening_platform.aoi import (
    GENERIC_AOI_POLICY,
    NORTHERN_COLORADO_REGRESSION_POLICY,
    AoiContext,
    northern_colorado_regression_policy,
)
from environmental_screening_platform.workflow import create_project, revise_aoi


def _aoi_file(path: Path, bounds: tuple[float, float, float, float]) -> Path:
    minx, miny, maxx, maxy = bounds
    path.write_text(
        json.dumps(
            mapping(
                Polygon(
                    [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)]
                )
            )
        ),
        encoding="utf-8",
    )
    return path


def _boundary_cache(root: Path) -> None:
    path = root / "workspace" / "reference" / "approved_counties.geojson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(Polygon([(-106, 39), (-103, 39), (-103, 42), (-106, 42), (-106, 39)])),
                        "properties": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_generic_project_accepts_aoi_outside_regression_geography(tmp_path: Path) -> None:
    data_root = tmp_path / "external"
    aoi_path = _aoi_file(tmp_path / "aoi.geojson", (-75, 40, -74.9, 40.1))

    created = create_project("generic AOI", aoi_path, data_root)

    assert created["project"]["aoi_validation_policy"] == GENERIC_AOI_POLICY
    assert created["aoi_revision"]["validation_policy"] == GENERIC_AOI_POLICY
    assert created["aoi_revision"]["spatial_validation"]["validation_policy"] == GENERIC_AOI_POLICY


def test_regression_policy_enforces_northern_colorado_boundary(tmp_path: Path) -> None:
    data_root = tmp_path / "external"
    _boundary_cache(data_root)
    inside = _aoi_file(tmp_path / "inside.geojson", (-105.5, 40, -105.4, 40.1))
    outside = _aoi_file(tmp_path / "outside.geojson", (-75, 40, -74.9, 40.1))

    created = create_project(
        "Northern Colorado regression",
        inside,
        data_root,
        validation_policy=northern_colorado_regression_policy(),
    )

    assert created["project"]["aoi_validation_policy"] == NORTHERN_COLORADO_REGRESSION_POLICY
    with pytest.raises(ValueError, match="approved three-county boundary"):
        create_project(
            "outside regression",
            outside,
            data_root,
            validation_policy=northern_colorado_regression_policy(),
        )


def test_aoi_revision_is_immutable_and_hash_provenance_is_preserved(tmp_path: Path) -> None:
    data_root = tmp_path / "external"
    first_path = _aoi_file(tmp_path / "first.geojson", (-75, 40, -74.9, 40.1))
    created = create_project("revision provenance", first_path, data_root)
    first = created["aoi_revision"]
    first_bytes = first_path.read_bytes()

    second = revise_aoi(
        str(created["project"]["project_id"]),
        _aoi_file(tmp_path / "second.geojson", (-75, 40, -74.8, 40.1)),
        data_root,
    )

    assert first["aoi_id"] != second["aoi_id"]
    assert first["revision"] == 1
    assert second["revision"] == 2
    assert first["input_sha256"] == hashlib.sha256(first_bytes).hexdigest()
    assert second["validation_policy"] == GENERIC_AOI_POLICY
    context = AoiContext.from_revision(first)
    assert context.aoi_id == first["aoi_id"]
    assert context.input_sha256 == first["input_sha256"]
    assert first["geometry_sha256"] == context.geometry_sha256
    assert context.validation_policy == GENERIC_AOI_POLICY
