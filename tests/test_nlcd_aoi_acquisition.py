from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from affine import Affine
from pyproj import Transformer
from rasterio.io import MemoryFile
from shapely.geometry import box
from shapely.ops import transform

from environmental_screening_platform.adapters import (
    NLCD_AOI_MIN_WINDOW_M,
    NLCD_REGIONAL_CRS,
    _nlcd_aoi_request,
    _validate_nlcd_aoi_raster,
    acquire_nlcd_aoi,
)
from environmental_screening_platform.aoi import AoiContext
from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.ingestion import ingest_nlcd_aoi
from environmental_screening_platform.workflow import create_project


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body
        self.url = "https://dmsdata.cr.usgs.gov/geoserver/wcs"
        self.status_code = 200
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "image/tiff",
            "ETag": '"generic-fixture"',
        }

    def raise_for_status(self) -> None:
        return

    def iter_content(self, size: int):
        yield self.body

    def close(self) -> None:
        return


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def _generic_aoi() -> Any:
    return box(-75.0008, 40.0008, -74.9992, 40.0024)


def _aoi_file(path: Path) -> Path:
    path.write_text(json.dumps(_generic_aoi().__geo_interface__), encoding="utf-8")
    return path


def _raster_bytes(*, nodata: int = 250) -> bytes:
    aoi = _generic_aoi()
    projected = transform(Transformer.from_crs(4326, 5070, always_xy=True).transform, aoi)
    left = projected.bounds[0] - 60
    top = projected.bounds[3] + 60
    values = np.array(
        [
            [21, 21, 22, 22, 250, 250],
            [21, 23, 22, 22, 250, 250],
            [41, 41, 250, 71, 90, 95],
            [41, 41, 71, 71, 90, 95],
            [250, 250, 81, 82, 81, 82],
            [250, 250, 81, 82, 81, 82],
        ],
        dtype="uint8",
    )
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=values.shape[1],
            height=values.shape[0],
            count=1,
            dtype="uint8",
            crs=NLCD_REGIONAL_CRS,
            transform=Affine(30, 0, left, 0, -30, top),
            nodata=nodata,
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


def test_generic_request_is_native_and_uses_bounded_padded_aoi_bounds() -> None:
    request = _nlcd_aoi_request(_generic_aoi())

    assert request["crs"] == "EPSG:5070"
    assert request["resx"] == request["resy"] == 30
    assert request["time"] == "2025-01-01T00:00:00.000Z"
    bbox = [float(value) for value in request["bbox"].split(",")]
    projected = transform(
        Transformer.from_crs(4326, 5070, always_xy=True).transform, _generic_aoi()
    )
    assert bbox[0] < projected.bounds[0]
    assert bbox[1] < projected.bounds[1]
    assert bbox[2] > projected.bounds[2]
    assert bbox[3] > projected.bounds[3]
    assert bbox[2] - bbox[0] >= NLCD_AOI_MIN_WINDOW_M
    assert bbox[3] - bbox[1] >= NLCD_AOI_MIN_WINDOW_M


def test_generic_validation_preserves_outside_and_nodata_accounting() -> None:
    profile = _validate_nlcd_aoi_raster(_raster_bytes(), _generic_aoi())

    assert profile["crs"] == "EPSG:5070"
    assert profile["resolution_m"] == [30.0, 30.0]
    assert profile["nodata"] == 250
    assert profile["pixel_accounting"]["outside_aoi_pixel_count"] > 0
    assert profile["pixel_accounting"]["nodata_pixel_count"] > 0
    assert profile["coverage"]["covered_aoi_percentage"] > 0
    assert all(
        int(code) in {11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 72, 73, 74, 81, 82, 90, 95}
        for code in profile["observed_class_values"]
    )


def test_generic_request_rejects_oversized_aoi_before_http() -> None:
    with pytest.raises(ValueError, match="bounded.*tiling is not implemented"):
        _nlcd_aoi_request(box(-80, 30, -70, 40))


def test_generic_ingestion_uses_persisted_revision_and_records_provenance(tmp_path: Path) -> None:
    data_root = tmp_path / "external"
    aoi_path = _aoi_file(tmp_path / "generic.geojson")
    created = create_project("generic NLCD", aoi_path, data_root)
    body = _raster_bytes()
    session = FakeSession(FakeResponse(body))

    outcome = ingest_nlcd_aoi(
        data_root,
        project_id=created["project"]["project_id"],
        session=session,
    )

    assert len(session.calls) == 1
    assert session.calls[0]["params"]["crs"] == "EPSG:5070"
    assert session.calls[0]["params"]["coverage"].startswith("mrlc_Land-Cover")
    candidate = outcome["candidate"]
    provenance = candidate["validation"]["source_provenance"]
    revision = created["aoi_revision"]
    context = AoiContext.from_revision(revision)
    assert outcome["run"]["aoi_id"] == revision["aoi_id"]
    assert outcome["run"]["aoi_revision"] == revision["revision"]
    assert provenance["aoi_revision"] == revision["revision"]
    assert provenance["aoi_input_sha256"] == hashlib.sha256(aoi_path.read_bytes()).hexdigest()
    assert provenance["aoi_geometry_sha256"] == context.geometry_sha256
    assert provenance["source_collection"] == "Annual NLCD Collection 1.2, 2025 land cover"
    assert provenance["sha256"] == hashlib.sha256(body).hexdigest()
    assert provenance["size_bytes"] == len(body)
    assert candidate["promotion_status"] == "not_promoted"
    assert SQLiteSourceRepository(data_root).get_active("annual_nlcd") is None
    manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    assert any(
        item.get("candidate_id") == candidate["candidate_id"] for item in manifest["artifacts"]
    )


def test_generic_adapter_attaches_aoi_context_provenance(tmp_path: Path) -> None:
    body = _raster_bytes()
    context = AoiContext(
        project_id="project",
        aoi_id="aoi",
        revision=3,
        geometry=_generic_aoi(),
        input_sha256="a" * 64,
        spatial_validation={"crs": "EPSG:4326"},
        validation_policy="generic",
    )
    acquired = acquire_nlcd_aoi(
        FakeSession(FakeResponse(body)),
        tmp_path,
        context.geometry,
        aoi_context=context,
    )

    assert acquired.result.provenance is not None
    assert acquired.result.provenance["aoi_id"] == "aoi"
    assert acquired.result.provenance["aoi_revision"] == 3
    assert acquired.result.provenance["aoi_geometry_sha256"] == context.geometry_sha256
