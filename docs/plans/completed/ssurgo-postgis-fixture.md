# SSURGO PostGIS fixture slice

## Outcome

Completed 2026-09-23. The existing official SDA representative response was parsed and loaded through a new PostGIS migration and repository boundary. A real `postgis/postgis:16-3.4` container accepted migration `002_ssurgo_mapunits`, staged 3 map units and 6 components, passed database-side validation, and atomically promoted the result as `fixture_only` with partial coverage and explicit source snapshot/version linkage.

## Verified behavior

- Provider `mukey`, `cokey`, `musym`, `muname`, `comppct_r`, `hydricrating`, and `hydricon` values and joins were preserved.
- Source and canonical geometry metadata are EPSG:4326; analysis area is EPSG:5070; valid polygonal geometry and component relationships passed direct PostGIS checks.
- Failed validation retains a queryable staging candidate and produces no canonical promotion.
- Reloading the same source snapshot/version is idempotent; a different source version remains separate and prior data is preserved.
- Optional ingestion-run and candidate identifiers are supported without moving the SQLite control-plane catalog into PostGIS.
- Raw response bytes and the external manifest remain outside Git.

## Remaining limits

The response is a representative Boulder-area sample only. It does not establish complete SSURGO coverage, full survey-area/package sizing, an active regional source version, or production readiness. Hydric-soil fields are soil indicators only; they are not wetlands mapping or a regulatory determination. PAD-US and FEMA remain unchanged, including FEMA access-blocked status.

## Checks

The live PostGIS integration set passed (`7 passed`; the intentional no-URL configuration assertion was excluded while the real URL was set), the full no-database suite passed (`41 passed, 3 skipped`), and Ruff, formatting, mypy, CLI, manifest/documentation validation, and `git diff --check` were run for the completed change.
