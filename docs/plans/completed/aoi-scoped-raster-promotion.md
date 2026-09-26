# AOI-scoped NLCD and 3DEP candidate promotion

## Outcome

Implemented AOI-scoped promotion for generic Annual NLCD and 3DEP candidates
using the existing SQLite control-plane catalog. The implementation adds an
`active_aoi_versions` pointer, validates exact project/AOI/revision and
geometry-hash lineage, rechecks source-version and artifact integrity, and
applies source-specific native-raster, complete-coverage, observation, and
nodata gates. Promotion decisions are auditable and idempotent; failed
replacements preserve the prior pointer.

Focused tests cover successful NLCD/3DEP promotion, incomplete and nodata
rejection, checksum/AOI/metadata mismatches, version isolation, job snapshot
resolution, prior-active preservation, and missing complete-coverage metrics.
Legacy unscoped fixture behavior and Northern Colorado aliases remain intact.

## Validation

- `tests/test_aoi_raster_promotion.py` passed.
- Full test, lint, type, CLI, documentation-link, and diff checks were run at
  completion; the repository's five pre-existing format-check failures remain
  unchanged and are reported in the handoff.
- No raw artifacts, database volumes, PostGIS schema, source processors, or
  runtime toolkit dependencies were added.
