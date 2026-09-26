# Annual NLCD browser preview

## Objective

Publish the first truthful browser-renderable environmental layer using the
validated Washington, DC Annual NLCD 2025 raster already retained outside Git.

## Scope

- Generate a derived RGBA PNG masked to the recorded AOI from the exact source
  raster, without changing the source artifact or screening metrics.
- Record source version, snapshot, checksum, raster grid/bounds, AOI hash, and
  the display transformation in checked-in preview metadata.
- Render the preview as an optional Leaflet image overlay with categorical
  legend, opacity control, toggle, AOI-on-top ordering, and honest failure
  handling.
- Add local generator, frontend, and raster/provenance tests.

## Boundaries

No provider access, raster redownload, source promotion, screening algorithm,
3DEP/SSURGO/FEMA/PAD-US change, composite interpretation, or production
frontend/backend work is included.

## Outcome

Completed 2026-09-26. Generated `frontend/public/demo/nlcd-preview.png` from
the retained validated Washington, DC Annual NLCD 2025 GeoTIFF without source
redownload. The 926 × 926 RGBA derivative preserves only valid AOI pixels,
with nodata and outside-AOI pixels transparent; metadata records the exact
source version, snapshot, checksum, raster grid/bounds, AOI revision/hash,
observed classes, display transformation, and derivative checksum. The
Leaflet map loads it as an optional, opacity-adjustable layer with a concise
legend and AOI-on-top ordering. Generator, frontend, full Python, and manual
desktop/mobile preview checks passed.
