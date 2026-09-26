# Real AOI map

## Objective

Replace the static AOI placeholder in the primary screening report with a
functional, responsive Leaflet map using the recorded AOI geometry and an
attributed public basemap.

## Scope

- Parse and validate recorded WGS84 Polygon/MultiPolygon geometry.
- Bundle Leaflet and its required assets into the static build.
- Fit and render only the AOI boundary; keep source metrics and operations view
  unchanged.
- Expose visible loading and error states and validate the HTTP preview.

## Outcome

Completed 2026-09-26. Leaflet is bundled with the static build, the exact
recorded WGS84 AOI polygon is parsed and fit to the map, and the attributed
OpenStreetMap basemap and AOI boundary were verified in headless Chromium at
desktop and mobile viewport sizes. Loading, tile-error, timeout, and invalid
geometry states remain visible. No environmental source geometry or screening
behavior was added.
