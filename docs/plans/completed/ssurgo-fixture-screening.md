# SSURGO fixture-only screening consumption

## Outcome

Completed 2026-09-24. Screening now consumes only canonical SSURGO rows matching the immutable SQLite job snapshot's exact `source_snapshot_id` and `source_version_id`. The PostGIS query intersects those fixture-only map-unit geometries with the job AOI, joins component records, and returns bounded coverage and hydric-attribute metrics.

## Verified behavior

- The explicit `screen-ssurgo-fixture` CLI mode creates only a single-source `ssurgo_fixture_only` job; the general `screen` command can use the same path only when given an explicit PostGIS URL.
- Covered AOIs report `source_status=fixture_only`, map-unit/component counts, covered and uncovered area, hydric attribute records, and `observed` or `no_indicator_observed` screening status.
- AOIs outside the fixture report `uncovered` and `not_covered`; missing SQLite snapshots remain `unknown`/incomplete rather than becoming no constraint.
- A newer promoted source version does not alter an existing job result; queries never select latest data.
- JSON, CSV, and GeoJSON results retain job/AOI, source snapshot/version, fixture status, and hydric-soil limitation provenance.
- PAD-US and FEMA remain unchanged and are not consumed by this slice.

## Remaining limits

The query is intentionally restricted to `fixture_only` canonical rows. It does not establish regional SSURGO coverage or production readiness. Hydric-soil information is not a wetlands inventory or regulatory determination. No composite score, regulatory threshold, or suitability conclusion is produced.

## Checks

The live PostGIS integration set passed (`10 passed`, excluding the intentional no-URL configuration assertion), the normal suite passed (`42 passed, 5 skipped`), and Ruff, formatting, mypy, CLI checks, documentation-link checks, and `git diff --check` were run.
