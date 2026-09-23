# Local PostGIS AOI repository boundary

## Objective

Add an optional, local-only PostGIS repository boundary for canonical AOI revisions while preserving SQLite as the control-plane catalog. Load and validate one three-component Census boundary fixture with explicit source snapshot/version identifiers.

## Outcome — completed 2026-09-22

- Added `postgis/postgis:16-3.4` Compose setup with health check, environment-provided credentials, and an external bind-mounted data directory.
- Added migration `001_aoi_revisions.sql` for canonical AOI revisions, preserved source components, spatial indexes, validity constraints, CRS metadata, and provenance.
- Added optional psycopg-backed `SpatialRepository`/`PostGISRepository`, explicit SQLite-to-PostGIS text linkage, Census boundary loader, idempotent insertion, and transaction-scoped writes.
- Added CLI commands for migration and boundary loading. The loader preserves the three approved county components, transforms EPSG:4269 to EPSG:4326, and measures area in EPSG:5070 without narrowing or silently repairing geometry.
- Added deterministic fixture/static tests and an opt-in real PostGIS integration test. No environmental source tables, source substitutions, frontend, API, queue, or deployment work was added.

## Validation

The implementation baseline originally had 40 tests passing with the PostGIS integration test skipped because Docker was not integrated with WSL and psycopg was unavailable. A runtime-verification follow-up completed on 2026-09-23: the pinned container started with an external bind-mounted volume, migration `001_aoi_revisions` applied, and the validated 2025 Census boundary loaded successfully. Direct queries verified the three county components, valid `ST_MultiPolygon` union, CRS metadata, source snapshot/version linkage, idempotent reload, and rollback without partial records after a deliberate duplicate-component failure. The real integration test passed. The full non-database suite remained 40 passed/1 skipped, with Ruff, format, mypy, CLI help, documentation-link checks, and `git diff --check` passing. No deployed database or environmental source loading was introduced.
