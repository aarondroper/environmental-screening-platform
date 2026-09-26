from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_bounds
from shapely.geometry import Polygon
from shapely.ops import transform

from environmental_screening_platform.nlcd_preview import generate_nlcd_preview


def _write_source(path: Path, aoi: Polygon) -> None:
    to_source = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    minx, miny, maxx, maxy = transform(to_source, aoi).bounds
    bounds = (minx - 1_000, miny - 1_000, maxx + 1_000, maxy + 1_000)
    values = np.full((8, 8), 22, dtype="uint8")
    values[3, 3] = 250
    values[3:5, 3:5] = 23
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="uint8",
        crs="EPSG:5070",
        transform=from_bounds(*bounds, values.shape[1], values.shape[0]),
        nodata=250,
    ) as dataset:
        dataset.write(values, 1)


def test_preview_masks_nodata_and_outside_aoi_and_preserves_provenance(tmp_path: Path) -> None:
    aoi = Polygon([[-77.041, 38.9], [-77.039, 38.9], [-77.039, 38.902], [-77.041, 38.902]])
    source = tmp_path / "source.tif"
    preview = tmp_path / "preview.png"
    metadata_path = tmp_path / "preview.json"
    _write_source(source, aoi)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    metadata = generate_nlcd_preview(
        source,
        preview,
        metadata_path,
        aoi_geometry={"type": "Polygon", "coordinates": [list(aoi.exterior.coords)]},
        aoi_revision=1,
        aoi_geometry_sha256="aoi-hash",
        source_metadata={
            "source_snapshot_id": "snapshot-1",
            "source_version_id": "annual_nlcd:version-1",
            "sha256": source_sha256,
            "source_year": 2025,
            "release": "Annual NLCD Collection 1.2, 2025 land cover",
        },
        generated_at="2026-09-26",
    )

    assert metadata["display_derivative"] is True
    assert metadata["schema_version"] == 2
    assert metadata["display_raster"]["crs"] == "EPSG:4326"
    assert metadata["display_raster"]["transform"][1] == 0
    assert metadata["display_raster"]["transform"][3] == 0
    assert metadata["schema_version"] == 2
    assert metadata["source"]["sha256"] == source_sha256
    assert metadata["source"]["source_snapshot_id"] == "snapshot-1"
    assert metadata["source"]["source_version_id"] == "annual_nlcd:version-1"
    assert metadata["aoi"]["geometry_sha256"] == "aoi-hash"
    assert metadata["source_raster"]["crs"] == "EPSG:5070"
    assert metadata["source"]["raster"]["crs"] == "EPSG:5070"
    assert metadata["display_raster"]["crs"] == "EPSG:4326"
    assert metadata["display_raster"]["nodata"] == 250
    assert metadata["display_raster"]["pixel_dimensions"] == [
        metadata["display_raster"]["width"],
        metadata["display_raster"]["height"],
    ]
    assert metadata["display_raster"]["transform"][1] == 0
    assert metadata["display_raster"]["transform"][3] == 0
    assert metadata["alignment"]["outside_aoi_pixels_transparent"] is True
    assert metadata["alignment"]["source_nodata_transparent"] is True
    assert [item["value"] for item in metadata["legend"]] == [23]
    assert metadata["display"]["asset_sha256"] == hashlib.sha256(preview.read_bytes()).hexdigest()
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["source"] == metadata["source"]

    with rasterio.open(preview) as image:
        rgba = image.read()
    assert rgba.shape == (
        4,
        metadata["display_raster"]["height"],
        metadata["display_raster"]["width"],
    )
    assert set(np.unique(rgba[3])) == {0, 255}
    assert np.any(rgba[0][rgba[3] == 255] == 235)  # NLCD class 23 red channel

    source_bounds = metadata["source_raster"]["bounds"]
    display_bounds = metadata["display_raster"]["bounds"]
    overlay_bounds = metadata["alignment"]["overlay_bounds_wgs84"]
    assert overlay_bounds[0] < overlay_bounds[2]
    assert overlay_bounds[1] < overlay_bounds[3]
    assert source_bounds[0] < source_bounds[2]
    assert overlay_bounds == display_bounds
    assert metadata["alignment"]["display_crs"] == "EPSG:4326"
    assert metadata["alignment"]["display_transform"] == metadata["display_raster"]["transform"]


def test_preview_rejects_source_checksum_substitution(tmp_path: Path) -> None:
    aoi = Polygon([[-77.041, 38.9], [-77.039, 38.9], [-77.039, 38.902], [-77.041, 38.902]])
    source = tmp_path / "source.tif"
    _write_source(source, aoi)
    with pytest.raises(ValueError, match="checksum mismatch"):
        generate_nlcd_preview(
            source,
            tmp_path / "preview.png",
            tmp_path / "preview.json",
            aoi_geometry={"type": "Polygon", "coordinates": [list(aoi.exterior.coords)]},
            aoi_revision=1,
            aoi_geometry_sha256="aoi-hash",
            source_metadata={"sha256": "not-the-source"},
        )


def test_checked_in_demo_preview_matches_its_metadata() -> None:
    demo = Path(__file__).parents[1] / "frontend" / "public" / "demo"
    metadata = json.loads((demo / "nlcd-preview.json").read_text(encoding="utf-8"))
    asset = demo / "nlcd-preview.png"
    assert metadata["display_derivative"] is True
    assert metadata["source"]["source_version_id"].startswith("annual_nlcd:")
    assert (
        metadata["source"]["sha256"]
        == "6bc353d127a2a7d5a66c8152cfea099f271275e172d0924c18470fc0d93a6c4e"
    )
    assert metadata["display"]["asset_sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
    with rasterio.open(asset) as image:
        assert image.count == 4
        assert image.width == metadata["display_raster"]["width"]
        assert image.height == metadata["display_raster"]["height"]
        assert set(np.unique(image.read(4))) <= {0, 255}
