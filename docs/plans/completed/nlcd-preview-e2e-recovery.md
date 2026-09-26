# Plan: recover generic-AOI NLCD preview delivery

## Outcome

Completed 2026-09-26. The end-to-end smoke identified a response-shape defect:
the bridge wrote one Annual NLCD preview object directly under
`browser_previews`, while the frontend consumes source-keyed previews at
`browser_previews.annual_nlcd`. The bridge now writes the source-keyed shape
and normalizes the legacy unkeyed shape when reading existing successful jobs.

## Evidence

- A real small Colorado AOI completed successfully through `screening serve`.
- The generated PNG and metadata were persisted outside Git under the job
  workspace and served by both job-scoped preview routes.
- AOI revision, geometry hash, source snapshot/version, source checksum, source
  year, CRS, transform, dimensions, and nodata matched across the result,
  metadata, and external artifact.
- The frontend bundle consumes `activeReport.browser_previews` and the
  source-keyed Annual NLCD entry. Identify behavior returned a human-readable
  observed class and explicit outside-AOI/nodata messages.

## Validation

The focused Python HTTP regression, full Python suite, frontend tests/build,
Ruff, Ruff format check, mypy, CLI help, documentation-link check, and
`git diff --check` passed. No other source, screening, or UI behavior changed.
