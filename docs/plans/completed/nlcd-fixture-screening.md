# Snapshot-pinned Annual NLCD fixture screening

## Outcome

Completed 2026-09-24. The local screening worker now consumes Annual NLCD only
from the exact external GeoTIFF named by the immutable SQLite job snapshot's
`source_snapshot_id` and `source_version_id`. The explicit `screen-nlcd-fixture`
mode creates a single-source bounded job and does not create a PostGIS pixel
table.

## Verified behavior

- Covered AOIs report raster footprint coverage, valid/nodata pixels, source class
  values and documented labels, class percentages, estimated cell area, and CRS,
  transform, resolution, dimensions, nodata, and source-year metadata.
- Uncovered AOIs, missing snapshots, and missing/checksum-invalid artifacts remain
  explicit unknown/unavailable outcomes; they are never treated as no constraint.
- A later promoted raster version does not alter an existing job result.
- JSON and CSV retain raster metrics and exact source provenance. GeoJSON retains
  source state/provenance without fabricating pixel geometries.
- Census, SSURGO, PAD-US, and FEMA behavior remains unchanged.

## Remaining limits

The path is `fixture_only` and representative. It does not establish full
Northern Colorado NLCD coverage, regional window/mosaic behavior, or production
readiness. NLCD classes are land-cover classifications, not regulatory
constraints or suitability conclusions.

## Checks

The NLCD screening tests passed (`4 passed`), the full suite passed (`46 passed,
5 skipped`), and the live PostGIS regression set passed (`10 passed, 1
deselected`). Ruff, formatting, mypy, CLI, documentation-link, and
`git diff --check` checks also passed.
