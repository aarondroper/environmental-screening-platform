# 3DEP browser preview

## Objective

Add the first browser-renderable 3DEP terrain layer to the recorded
Washington, DC screening workspace using the retained validated source tile.

## Scope

- Generate a small AOI-windowed RGBA hillshade display derivative from the
  external 3DEP GeoTIFF without redownloading or committing the source tile.
- Preserve source version, checksum, raster contract, AOI lineage, and the
  display transformation in checked-in metadata.
- Add an optional Leaflet layer beneath the AOI boundary with a restrained
  explanation, toggle, opacity control, and honest loading/error behavior.
- Keep NLCD, screening metrics, source maturity, and all non-3DEP sources
  unchanged.

## Boundaries

No elevation conversion, vertical datum/unit claim, source promotion, new
screening behavior, composite interpretation, or provider access is included.

## Outcome

Completed 2026-09-26. Generated `frontend/public/demo/3dep-preview.png` from
the retained 500,034,664-byte Washington, DC 3DEP GeoTIFF without redownload.
The 44 × 44 native-cell AOI window is a muted relative hillshade with
outside-AOI and nodata cells transparent. Metadata preserves the exact source
version, snapshot, tile URL/release, checksum, EPSG:4269 source grid/bounds/
nodata, AOI revision/hash, preview bounds, and transformation. The Leaflet
workspace loads it as an optional disabled-by-default layer below the AOI
boundary, with opacity, toggle, legend, and explicit failure handling. The
source raster declares no vertical units or datum, so the preview exposes no
elevation values or conversion. Focused and full validation plus manual
desktop/mobile review passed.
