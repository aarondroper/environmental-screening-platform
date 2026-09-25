# AOI-agnostic boundary refactor

## Objective

Separate generic AOI validation from the Northern Colorado regression/demo
fixture without changing source processors, screening metrics, or persistence
identifiers.

## Delivered

- Added `AoiContext` and named AOI validation policies.
- Generic project creation/revision now accepts valid nonempty WGS84
  Polygon/MultiPolygon AOIs without a global containment boundary.
- Added the explicit `northern_colorado_regression` policy, preserving the
  existing 2025 county containment behavior when selected.
- Centralized Northern Colorado county IDs, boundary paths, SSURGO package
  count/sizing path, raster expectations, and fixture metadata in
  `regression_fixtures.py`.
- Preserved existing project, AOI, ingestion, job snapshot, PostGIS, export,
  and provenance identifiers; policy provenance is additive.
- Added focused generic-AOI, policy-enforcement, revision, hash, and
  provenance tests.
- Updated product and architecture documentation to describe Northern Colorado
  as a regression/demo fixture rather than the platform-wide AOI boundary.

## Validation

- Focused tests: 45 passed.
- Full deterministic suite: 82 passed, 8 optional external/PostGIS tests
  skipped because their environment variables/fixtures were not configured.
- Ruff, mypy, CLI help, local documentation-link validation, and
  `git diff --check` passed.

## Remaining limits

Generic source acquisition, source tiling, UI/API AOI drawing, and arbitrary-AOI
production coverage remain future work. PAD-US and FEMA behavior and all source
maturity labels are unchanged.
