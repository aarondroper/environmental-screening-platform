from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import box
from test_ssurgo_regional_candidate import _make_fixture

from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.ssurgo_regional_candidate import (
    materialize_staged_ssurgo_candidate,
)
from environmental_screening_platform.ssurgo_regional_coverage import (
    _classify_gap_components,
    analyze_coverage_geometries,
)


def test_full_two_package_coverage_has_no_gap_or_overlap() -> None:
    result = analyze_coverage_geometries(
        box(0, 0, 2, 1),
        {"P1": [box(0, 0, 1, 1)], "P2": [box(1, 0, 2, 1)]},
    )

    assert result["covered_area_sqm"] == pytest.approx(result["aoi_area_sqm"], rel=1e-3)
    assert result["uncovered_area_sqm"] == pytest.approx(0, abs=1e-3)
    assert result["overlap_pair_count"] == 0


def test_gap_overlap_and_aoi_clipping_are_distinguished() -> None:
    result = analyze_coverage_geometries(
        box(0, 0, 2, 1),
        {"P1": [box(-1, 0, 0.8, 1)], "P2": [box(0.7, 0, 1.5, 1)]},
    )

    assert result["uncovered_area_sqm"] > 0
    assert result["overlap_pair_count"] == 1
    assert result["overlap_area_sqm"] > 0
    assert result["outside_aoi_feature_area_sqm"] > 0
    assert result["packages"][0]["coverage_percentage_of_aoi"] < 100


def test_coverage_metrics_and_geometry_are_repeatable() -> None:
    aoi = box(0, 0, 2, 1)
    features = {"P1": [box(0, 0, 1.2, 1)], "P2": [box(1.1, 0, 2, 1)]}

    first = analyze_coverage_geometries(aoi, features)
    second = analyze_coverage_geometries(aoi, features)
    assert first["aoi_area_sqm"] == second["aoi_area_sqm"]
    assert first["covered_area_sqm"] == second["covered_area_sqm"]
    assert first["overlap_area_sqm"] == second["overlap_area_sqm"]
    assert first["gap_geometry"].wkb_hex == second["gap_geometry"].wkb_hex


def test_gap_diagnostics_distinguish_boundary_and_interior_residuals() -> None:
    aoi = box(0, 0, 2, 2)
    gap = box(0, 0.5, 0.000001, 0.6).union(box(0.5, 0.5, 0.6, 0.6))

    diagnostics = _classify_gap_components(aoi, gap)

    assert {item["properties"]["classification"] for item in diagnostics} == {
        "aoi_boundary_residual",
        "interior_aoi_gap",
    }


def test_coverage_validation_persists_without_active_promotion(tmp_path: Path) -> None:
    _make_fixture(tmp_path)
    materialized = materialize_staged_ssurgo_candidate(tmp_path)
    repository = SQLiteSourceRepository(tmp_path)
    validation = {
        "analysis_version": "test",
        "aggregate_report_sha256": "a" * 64,
        "coverage": {"covered_percentage": 100.0},
    }
    updated = repository.record_coverage_validation(
        materialized["candidate"]["candidate_id"],
        coverage_status="complete",
        observation_status="data_observed",
        validation=validation,
    )
    repeated = repository.record_coverage_validation(
        materialized["candidate"]["candidate_id"],
        coverage_status="complete",
        observation_status="data_observed",
        validation=validation,
    )

    assert updated["validation"]["regional_coverage_validation"] == validation
    assert repeated["candidate_id"] == updated["candidate_id"]
    assert updated["status"] == "incomplete"
    assert updated["promotion_status"] == "not_promoted"
    assert repository.get_active("ssurgo") is None
