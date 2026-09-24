# SSURGO regional inactive candidate materialization

## Outcome

Completed on 2026-09-24. The existing 19-package staging aggregate was
checksum-verified together with all package reports, raw package checksums,
package candidates/runs, the discrepancy audit, and package QA report. The
aggregate was materialized as one inactive SQLite source version/candidate:

- candidate: `9d77a86a-bdc7-4684-b977-1081f8ed484c`;
- source version: `ssurgo:e6e101e90c00745d452482c2e9a4bbedab2a46813d830141e76852ead9b5f3bf`;
- synthetic snapshot: `ssurgo-regional-staging:615f66d0-0b3a-4356-a53a-0ac346b385ee`;
- state: `incomplete`, `conditionally_validated`, `partial`, `not_promoted`.

The candidate records 19/19 acquired and structurally valid packages, 123,196
features, 1,878 map units, 7,404 components, 10 accepted audited repairs, zero
quarantines, valid derived geometry/CRS checks, zero orphan joins, and the
documented WY621/WY721 harmless naming variations. It links the package
candidates/runs, raw checksums, staging batch, repair audit, and QA reports.

Repeat materialization returned the same candidate/version/run. A changed
aggregate checksum or validation count fails before a new candidate is created.
No active SSURGO version or active pointer was created or changed. Raw packages,
original geometries, and PostGIS staging were not modified.

## Validation

- focused candidate tests: passed;
- full test, Ruff, format, mypy, CLI, documentation-link, manifest, and
  `git diff --check` gates: passed;
- real external materialization and idempotent rerun: passed.

Complete regional coverage validation, production readiness, and any active
source-version promotion remain separate owner-controlled work.
