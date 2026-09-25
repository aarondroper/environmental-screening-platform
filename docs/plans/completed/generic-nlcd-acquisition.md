# Generic Annual NLCD acquisition

## Outcome

Implemented the first AOI-agnostic source acquisition slice. The persisted
immutable AOI revision is loaded as `AoiContext`; generic Annual NLCD WCS
requests use the AOI geometry, native EPSG:5070/30 m grid, nodata 250, and the
official class domain. AOI revision/input/geometry hashes, exact request
parameters, raster metadata, HTTP metadata, checksum, and inactive candidate
lineage are retained.

The request is bounded before HTTP acquisition and reports an explicit error
when the estimated native-grid window exceeds the configured cell limit. No
clipping or tiling was added. The existing `ingest-nlcd-regional` command and
tests remain the Northern Colorado regression/fixture alias.

## Validation

- Focused generic and regional NLCD tests passed.
- Generic tests cover an AOI outside Northern Colorado, request construction,
  geometry hashing, outside/nodata accounting, checksum/provenance capture,
  persisted revision binding, inactive candidate behavior, and pre-network
  bounded rejection.
- Full repository gates were run after the implementation. Ruff lint, tests,
  mypy, CLI checks, documentation links, and diff checks passed; the repository
  format check still reports five pre-existing unrelated files and those files
  were intentionally left unchanged.

## Limits

The generic path has deterministic mocked provider coverage only in this slice.
It does not change NLCD source maturity, activate a candidate, add tiling, or
generalize SSURGO, FEMA, or PAD-US.
