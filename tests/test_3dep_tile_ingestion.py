from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import requests
from affine import Affine
from rasterio.io import MemoryFile
from shapely.geometry import box, mapping

from environmental_screening_platform.aoi import AoiContext
from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.ingestion import ingest_3dep
from environmental_screening_platform.three_dep import (
    THREEDEP_INVENTORY_URL,
    THREEDEP_NATIVE_CRS,
    discover_3dep_tile_plan,
    validate_3dep_tile_raster,
)
from environmental_screening_platform.workflow import create_project


class FakeResponse:
    def __init__(
        self,
        body: bytes = b"",
        *,
        url: str,
        json_body: dict[str, Any] | None = None,
        status_code: int = 200,
        content_type: str = "image/tiff",
    ):
        self.body = body
        self.url = url
        self._json_body = json_body
        self.status_code = status_code
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
            "ETag": '"tile-fixture"',
        }

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> dict[str, Any]:
        assert self._json_body is not None
        return self._json_body

    def iter_content(self, size: int):
        yield self.body

    def close(self) -> None:
        return


class FakeSession:
    def __init__(self, inventory: dict[str, Any], tile_body: bytes, data_root: Path):
        self.inventory = inventory
        self.tile_body = tile_body
        self.data_root = data_root
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if url == THREEDEP_INVENTORY_URL:
            return FakeResponse(
                url=THREEDEP_INVENTORY_URL,
                json_body=self.inventory,
                content_type="application/json",
            )
        assert list((self.data_root / "3dep" / "tile-plans").glob("*.json"))
        return FakeResponse(body=self.tile_body, url=url)


def _context() -> AoiContext:
    geometry = box(-75.0008, 40.0008, -74.9992, 40.0024)
    return AoiContext(
        project_id="project",
        aoi_id="aoi",
        revision=2,
        geometry=geometry,
        input_sha256="a" * 64,
        spatial_validation={"crs": "EPSG:4326"},
        validation_policy="generic",
    )


def _item(date: str, *, tile: str = "n40w075", outside: bool = False) -> dict[str, Any]:
    bounds = [-76, 39, -74, 41] if not outside else [-80, 35, -79, 36]
    return {
        "title": f"USGS 1/3 Arc Second {tile} {date}",
        "sourceId": f"product-{tile}-{date}",
        "metaUrl": f"https://www.sciencebase.gov/catalog/item/product-{date}",
        "vendorMetaUrl": "https://prd-tnm.s3.amazonaws.com/metadata.xml",
        "publicationDate": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "lastUpdated": f"{date[:4]}-{date[4:6]}-{date[6:]}T00:00:00Z",
        "sizeInBytes": 1234,
        "extent": "1 x 1 degree",
        "format": "GeoTIFF",
        "downloadURL": f"https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/historical/{tile}/USGS_13_{tile}_{date}.tif",
        "boundingBox": {
            "minX": bounds[0],
            "minY": bounds[1],
            "maxX": bounds[2],
            "maxY": bounds[3],
        },
    }


def _raster_bytes(*, nodata_inside: bool = True) -> bytes:
    aoi = _context().geometry
    minx, miny, maxx, maxy = aoi.bounds
    resolution = (1 / 3) / 3600
    values = np.full((12, 12), 1600, dtype="float32")
    if nodata_inside:
        values[5, 5] = -999999
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=values.shape[1],
            height=values.shape[0],
            count=1,
            dtype="float32",
            crs=THREEDEP_NATIVE_CRS,
            transform=Affine(
                resolution,
                0,
                minx - resolution * 3,
                0,
                -resolution,
                maxy + resolution * 3,
            ),
            nodata=-999999,
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


def test_tile_plan_is_deterministic_and_selects_newest_product_per_tile() -> None:
    context = _context()
    items = [_item("20220101"), _item("20260101"), _item("20230101", outside=True)]
    first = discover_3dep_tile_plan(
        FakeSession({"total": len(items), "items": items}, b"", Path("/tmp")), context
    )
    second = discover_3dep_tile_plan(
        FakeSession({"total": len(items), "items": list(reversed(items))}, b"", Path("/tmp")),
        context,
    )

    assert first["selected_tiles"] == second["selected_tiles"]
    assert first["selected_tiles"][0]["publication_date"] == "2026-01-01"
    assert len(first["candidate_products"]) == 2
    assert first["inventory_parameters"]["bbox"]
    assert first["aoi_geometry_sha256"] == context.geometry_sha256


def test_tile_plan_rejects_oversized_aoi_before_inventory() -> None:
    context = AoiContext(
        project_id="project",
        aoi_id="large",
        revision=1,
        geometry=box(-100, 30, -90, 40),
        input_sha256="b" * 64,
        spatial_validation={"crs": "EPSG:4326"},
        validation_policy="generic",
    )
    session = FakeSession({"total": 0, "items": []}, b"", Path("/tmp"))

    with pytest.raises(ValueError, match="bounded tile-plan limit"):
        discover_3dep_tile_plan(session, context)
    assert session.calls == []


def test_tile_raster_validation_preserves_nodata_and_native_metadata() -> None:
    profile = validate_3dep_tile_raster(
        _raster_bytes(), _context().geometry, tile=_item("20260101") | {"tile_id": "n40w075"}
    )

    assert profile["source_crs"] == "EPSG:4269"
    assert profile["dtype"] == "float32"
    assert profile["nodata"] == -999999.0
    assert profile["resolution_arc_seconds"] == pytest.approx([1 / 3, 1 / 3])
    assert profile["pixel_accounting"]["nodata_pixel_count"] > 0
    assert profile["pixel_accounting"]["outside_aoi_pixel_count"] > 0
    assert profile["elevation_m"]["mean"] == 1600


def test_generic_ingestion_records_tile_checksum_and_inactive_candidate(tmp_path: Path) -> None:
    aoi_path = tmp_path / "aoi.geojson"
    aoi_path.write_text(json.dumps(mapping(_context().geometry)), encoding="utf-8")
    data_root = tmp_path / "external"
    project = create_project("generic 3DEP", aoi_path, data_root)
    body = _raster_bytes()
    inventory = {"total": 1, "items": [_item("20260101")]}
    session = FakeSession(inventory, body, data_root)

    outcome = ingest_3dep(
        data_root,
        project_id=project["project"]["project_id"],
        session=session,
    )

    assert outcome["status"] == "completed_validation_only"
    tile = outcome["tiles"][0]
    candidate = tile["candidate"]
    provenance = candidate["validation"]["source_provenance"]
    assert provenance["tile_id"] == "n40w075"
    assert provenance["aoi_revision"] == 1
    assert provenance["aoi_geometry_sha256"] == project["aoi_revision"]["geometry_sha256"]
    assert provenance["sha256"] == hashlib.sha256(body).hexdigest()
    assert provenance["request_parameters"]["tile_id"] == "n40w075"
    assert candidate["promotion_status"] == "not_promoted"
    assert SQLiteSourceRepository(data_root).get_active("3dep") is None
    manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    assert any(item.get("tile_id") == "n40w075" for item in manifest["artifacts"])
    assert Path(outcome["plan_path"]).exists()


def test_failed_tile_download_is_retained_in_manifest(tmp_path: Path) -> None:
    aoi_path = tmp_path / "aoi.geojson"
    aoi_path.write_text(json.dumps(mapping(_context().geometry)), encoding="utf-8")
    data_root = tmp_path / "external"
    project = create_project("failed 3DEP", aoi_path, data_root)
    inventory = {"total": 1, "items": [_item("20260101")]}

    class FailedSession(FakeSession):
        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            if url != THREEDEP_INVENTORY_URL:
                self.calls.append({"url": url, **kwargs})
                return FakeResponse(
                    url=url,
                    status_code=503,
                    content_type="text/plain",
                )
            return super().get(url, **kwargs)

    outcome = ingest_3dep(
        data_root,
        project_id=project["project"]["project_id"],
        session=FailedSession(inventory, b"", data_root),
    )

    assert outcome["status"] == "failed"
    assert outcome["tiles"][0]["candidate"]["status"] == "failed"
    manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    assert any(item.get("tile_id") == "n40w075" for item in manifest["failed_attempts"])
