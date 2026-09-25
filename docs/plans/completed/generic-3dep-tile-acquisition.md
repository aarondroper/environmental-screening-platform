# Generic 3DEP tile planning and acquisition

## Objective

Add a bounded, AOI-parameterized 3DEP 1/3-arc-second tile workflow that uses a
persisted immutable AOI revision, writes a deterministic TNM Access tile plan
before downloads, and registers each acquired tile as an inactive candidate.

## Scope completed

- Query the official TNM Access inventory for intersecting 1/3-arc-second DEM
  GeoTIFF products.
- Select one deterministic product release per intersecting tile.
- Acquire and validate each tile independently with per-tile provenance,
  checksums, raster metadata, and catalog lineage.
- Preserve nodata/uncovered areas as unknown and reject oversized/excessive
  requests explicitly.
- Preserve `screen-3dep-fixture` and Northern Colorado regression behavior.

## Validation outcome

- Added five deterministic mocked/local tests covering discovery, deterministic
  selection, bounded AOIs, native raster validation, plan-before-download
  ordering, checksum/provenance recording, inactive candidates, and failed
  downloads retained in the external manifest.
- Full deterministic suite passed: 92 passed, 8 optional integration tests
  skipped because external raster/PostGIS prerequisites were not configured.
- Ruff lint and mypy passed. Format checking still reports five pre-existing
  unrelated files; the new files are formatted. CLI help, documentation path
  checks, and `git diff --check` passed.

## Explicit limits

No generic-AOI live tile download, clipping, resampling, mosaicking, promotion,
terrain-derived metric, or source-maturity change was performed. Full regional
3DEP acquisition and production readiness remain unresolved.
