from __future__ import annotations

import hashlib
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
    NLCD_REGIONAL_CRS,
    _nlcd_regional_request,
    _validate_nlcd_regional_raster,
    acquire_nlcd_regional,
)
from environmental_screening_platform.catalog import SQLiteSourceRepository
from environmental_screening_platform.ingestion import (
    _update_nlcd_regional_manifest,
    ingest_source,
)


class FakeResponse:
    def __init__(self, body: bytes, *, content_type: str = "image/tiff", status_code: int = 200):
        self.body = body
        self.url = "https://dmsdata.cr.usgs.gov/geoserver/wcs"
        self.status_code = status_code
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
            "ETag": '"fixture"',
        }

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

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


def _aoi() -> Any:
    return box(-105.0008, 40.0008, -104.9992, 40.0024)


def _raster_bytes(*, nodata: int = 250, unknown: bool = False) -> bytes:
    projected = transform(Transformer.from_crs(4326, 5070, always_xy=True).transform, _aoi())
    left = projected.bounds[0] - 60
    top = projected.bounds[3] + 60
    values = np.array(
        [
            [21, 21, 22, 22, 250, 250],
            [21, 23, 22, 22, 250, 250],
            [41, 41, 71, 71, 90, 95],
            [41, 41, 71, 71, 90, 95],
            [250, 250, 81, 82, 81, 82],
            [250, 250, 81, 82, 81, 82],
        ],
        dtype="uint8",
    )
    values[2:4, 2:4] = 250
    if unknown:
        values[2, 2] = 7
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


def test_regional_request_uses_exact_native_window_parameters() -> None:
    request = _nlcd_regional_request(_aoi())
    assert request["coverage"] == "mrlc_Land-Cover_conus_year_data:Land-Cover_conus_year_data"
    assert request["time"] == "2025-01-01T00:00:00.000Z"
    assert request["crs"] == "EPSG:5070"
    assert request["resx"] == request["resy"] == 30.0
    assert len(request["bbox"].split(",")) == 4


def test_regional_raster_validation_accounts_nodata_and_outside_pixels() -> None:
    profile = _validate_nlcd_regional_raster(_raster_bytes(), _aoi())
    assert profile["crs"] == "EPSG:5070"
    assert profile["resolution_m"] == [30.0, 30.0]
    assert profile["nodata"] == 250
    assert profile["pixel_accounting"]["nodata_pixel_count"] > 0
    assert profile["pixel_accounting"]["outside_aoi_pixel_count"] > 0
    assert profile["coverage"]["covered_aoi_percentage"] > 0
    assert profile["observed_class_values"] == sorted(profile["observed_class_values"])


def test_regional_raster_validation_rejects_wrong_nodata_and_unknown_class() -> None:
    with pytest.raises(ValueError, match="nodata"):
        _validate_nlcd_regional_raster(_raster_bytes(nodata=0), _aoi())
    with pytest.raises(ValueError, match="official class domain"):
        _validate_nlcd_regional_raster(_raster_bytes(unknown=True), _aoi())


def test_regional_acquisition_records_checksum_and_native_metadata(tmp_path: Path) -> None:
    body = _raster_bytes()
    session = FakeSession(FakeResponse(body))
    acquired = acquire_nlcd_regional(session, tmp_path, _aoi())
    assert session.calls[0]["params"]["crs"] == "EPSG:5070"
    assert session.calls[0]["params"]["resx"] == 30.0
    assert acquired.result.provenance is not None
    assert acquired.result.provenance["sha256"] == hashlib.sha256(body).hexdigest()
    assert acquired.result.provenance["size_bytes"] == len(body)
    assert acquired.result.metrics["source_year"] == 2025


def test_regional_ingestion_keeps_candidate_inactive_and_preserves_failed_artifact(
    tmp_path: Path,
) -> None:
    repo = SQLiteSourceRepository(tmp_path)
    aoi = _aoi()

    def acquire(_source_id: str, root: Path, _unused_aoi: Any, callback: Any):
        return acquire_nlcd_regional(
            FakeSession(FakeResponse(_raster_bytes())),
            root,
            aoi,
            acquisition_callback=callback,
        )

    outcome = ingest_source(
        "annual_nlcd",
        tmp_path,
        repository=repo,
        acquirer=acquire,
        aoi_override=aoi,
        aoi_metadata={"aoi_id": "northern-colorado-front-range", "revision": 1},
    )
    assert outcome["candidate"]["status"] == "incomplete"
    assert outcome["candidate"]["promotion_status"] == "not_promoted"
    assert repo.get_active("annual_nlcd") is None
    assert outcome["run"]["aoi_id"] == "northern-colorado-front-range"
    assert outcome["candidate"]["validation"]["metrics"]["crs"] == "EPSG:5070"

    def fails(_source_id: str, root: Path, _unused_aoi: Any, callback: Any):
        return acquire_nlcd_regional(
            FakeSession(FakeResponse(b"not a raster", content_type="text/plain")),
            root,
            aoi,
            acquisition_callback=callback,
        )

    failed = ingest_source(
        "annual_nlcd",
        tmp_path,
        repository=repo,
        acquirer=fails,
        aoi_override=aoi,
        aoi_metadata={"aoi_id": "northern-colorado-front-range", "revision": 1},
    )
    assert failed["candidate"]["status"] == "failed"
    assert failed["candidate"]["artifact_path"] is not None
    assert repo.get_active("annual_nlcd") is None
    _update_nlcd_regional_manifest(
        tmp_path,
        failed,
        boundary_path=tmp_path / "counties_2025.shp",
    )
    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert failed["candidate"]["candidate_id"] in manifest
