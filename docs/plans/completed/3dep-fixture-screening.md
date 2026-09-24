# Snapshot-pinned 3DEP fixture screening

## Outcome

Implemented the bounded `3dep_fixture_only` screening path. It reuses the
existing exact-snapshot raster window mechanics, selects only the immutable job
snapshot artifact, reports raw elevation and coverage metrics, preserves raster
metadata and provenance, and exports one meaningful raster footprint when the
fixture intersects the AOI. No pixels are materialized in PostGIS and no
derived terrain or suitability interpretation is produced.

The path remains fixture-only. The retained official service-window artifact
is representative rather than proof of full Northern Colorado coverage or
production readiness. It has no declared units or vertical datum, so those
fields remain null and values are not converted.

## Verification

- Deterministic and external NLCD/3DEP fixture suite: 50 passed, 5 expected
  PostGIS-dependent tests skipped.
- Live PostGIS regression for the existing AOI and SSURGO paths: 10 passed,
  1 configuration-specific test deselected.
- Ruff, format check, mypy, CLI help, and `git diff --check` passed.
- Raw artifacts and the PostGIS volume remain outside Git.

## Boundaries retained

- Census, SSURGO, and NLCD behavior was preserved; NLCD uses the shared raster
  window helper and its existing tests remain passing.
- PAD-US remains conditionally validated/quarantined and FEMA remains
  access-blocked.
- Full regional 3DEP tile/window sizing, exact contributing tile revisions,
  and production acquisition remain open.
