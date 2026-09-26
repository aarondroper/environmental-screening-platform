from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import Polygon

from environmental_screening_platform.three_dep_preview import generate_3dep_preview


def _aoi() -> Polygon:
    return Polygon([[-77.041, 38.9], [-77.039, 38.9], [-77.039, 38.902], [-77.041, 38.902]])


def _write_source(path: Path, aoi: Polygon) -> None:
    bounds = (-77.043, 38.898, -77.037, 38.904)
    values = np.arange(64, dtype="float32").reshape(8, 8) + 100
    values[2, 2] = -999999
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4269",
        transform=from_bounds(*bounds, values.shape[1], values.shape[0]),
        nodata=-999999,
    ) as dataset:
        dataset.write(values, 1)


def test_preview_window_hillshade_masks_nodata_and_preserves_lineage(tmp_path: Path) -> None:
    aoi = _aoi()
    source = tmp_path / "source.tif"
    preview = tmp_path / "preview.png"
    metadata_path = tmp_path / "preview.json"
    _write_source(source, aoi)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    metadata = generate_3dep_preview(
        source,
        preview,
        metadata_path,
        aoi_geometry={"type": "Polygon", "coordinates": [list(aoi.exterior.coords)]},
        aoi_revision=1,
        aoi_geometry_sha256="aoi-hash",
        source_metadata={
            "source_snapshot_id": "snapshot-3dep",
            "source_version_id": "3dep:version-1",
            "sha256": source_sha256,
            "release": "USGS 3DEP 1/3 arc-second fixture",
        },
        generated_at="2026-09-26",
        padding_degrees=0.0005,
    )

    assert metadata["display_derivative"] is True
    assert metadata["source"]["sha256"] == source_sha256
    assert metadata["source"]["source_version_id"] == "3dep:version-1"
    assert metadata["source"]["raster"]["crs"] == "EPSG:4269"
    assert metadata["source"]["raster"]["nodata"] == -999999.0
    assert metadata["aoi"]["geometry_sha256"] == "aoi-hash"
    assert metadata["alignment"]["outside_aoi_pixels_transparent"] is True
    assert metadata["alignment"]["source_nodata_transparent"] is True
    assert metadata["vertical_metadata"]["declared_in_source_raster"] is False
    assert metadata["vertical_metadata"]["units"] is None
    assert metadata["vertical_metadata"]["datum"] is None
    assert (
        metadata["preview_raster"]["resampling"]
        == "none; native source cells retained in the AOI window"
    )
    assert metadata["display"]["representation"] == "relative terrain hillshade"
    assert metadata["display"]["asset_sha256"] == hashlib.sha256(preview.read_bytes()).hexdigest()

    with rasterio.open(preview) as image:
        rgba = image.read()
    assert rgba.shape[0] == 4
    assert set(np.unique(rgba[3])) == {0, 255}
    visible_rgb = rgba[:3][:, rgba[3] == 255].T
    assert np.unique(visible_rgb, axis=0).shape[0] > 1
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["source"] == metadata["source"]

    overlay_bounds = metadata["alignment"]["overlay_bounds_wgs84"]
    assert overlay_bounds[0] < -77.041 < overlay_bounds[2]
    assert overlay_bounds[1] < 38.9 < overlay_bounds[3]


def test_preview_rejects_source_checksum_substitution(tmp_path: Path) -> None:
    source = tmp_path / "source.tif"
    _write_source(source, _aoi())
    with pytest.raises(ValueError, match="checksum mismatch"):
        generate_3dep_preview(
            source,
            tmp_path / "preview.png",
            tmp_path / "preview.json",
            aoi_geometry={"type": "Polygon", "coordinates": [list(_aoi().exterior.coords)]},
            aoi_revision=1,
            aoi_geometry_sha256="aoi-hash",
            source_metadata={"sha256": "not-the-source"},
        )


def test_checked_in_demo_preview_matches_metadata() -> None:
    demo = Path(__file__).parents[1] / "frontend" / "public" / "demo"
    metadata = json.loads((demo / "3dep-preview.json").read_text(encoding="utf-8"))
    asset = demo / "3dep-preview.png"
    assert metadata["display_derivative"] is True
    assert metadata["source"]["source_version_id"].startswith("3dep:")
    assert (
        metadata["source"]["sha256"]
        == "8c67738d7c829e9f408958b61fb2526df94a645d89805389c248dac84a9f3d18"
    )
    assert metadata["source"]["byte_size"] == 500034664
    assert metadata["vertical_metadata"]["units"] is None
    assert metadata["vertical_metadata"]["datum"] is None
    assert metadata["display"]["asset_sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
    with rasterio.open(asset) as image:
        assert image.count == 4
        assert image.width == metadata["preview_raster"]["width"]
        assert image.height == metadata["preview_raster"]["height"]
        assert set(np.unique(image.read(4))) <= {0, 255}
