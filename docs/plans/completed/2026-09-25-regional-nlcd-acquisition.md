# Regional Annual NLCD 2025 acquisition

## Outcome

Implemented and live-validated on 2026-09-25. The new `ingest-nlcd-regional`
workflow uses the exact 2025 Boulder/Larimer/Weld boundary and the official
USGS/MRLC WCS only. It acquired a 47,189,394-byte regional GeoTIFF outside Git
and recorded its request parameters, final URL, retrieval metadata, checksum,
source version, ingestion run, candidate, AOI revision, and validation metrics
in the external manifest and SQLite catalog.

The validated artifact is an EPSG:5070 `uint8` raster, 8,064 × 5,664 cells,
nodata 250, with provider-snapped approximately 30 m resolution and 16
official observed class values. The raster covers 100% of the approved AOI by
area; 21,285,520 valid AOI pixels and 0 nodata AOI pixels were observed. The
padded response contains 24,388,976 outside-AOI pixels, which are retained as
non-observations.

The candidate remains inactive and `not_promoted`; no active Annual NLCD source
version or PostGIS pixel table was created. Two earlier defensive validation
failures remain queryable as failed candidates. Existing fixture screening and
all other source pathways were left unchanged.

## Validation

- Focused regional acquisition tests pass with mocked provider responses.
- The real official WCS request returned HTTP 200 `image/tiff` and passed
  raster readability, CRS, transform/resolution, nodata, class-domain, and
  AOI coverage validation.
- Raw artifact remains outside Git under the external data directory.
