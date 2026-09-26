# AOI operational run report

## Outcome

Implemented the read-only `report-aoi-run` CLI projection for any persisted
project and immutable AOI revision. It reconciles existing SQLite parent and
child ingestion records, deterministic plans, attempts, candidates, source
versions, promotion decisions, AOI-scoped active pointers, and file-backed
screening jobs/snapshots/results without creating a parallel state model.

The command emits deterministic JSON by default and a concise `--format
summary` view. Source lifecycle sections preserve where each source stopped and
retain failed, incomplete, unavailable, unknown, quarantined, blocked, and
rejected evidence independently. SQLite is opened read-only for reporting;
missing catalogs are not initialized.

## Validation

- Focused report tests: 4 passed.
- Full suite: 118 passed, 9 skipped.
- Ruff, mypy, CLI help, documentation-link checks, and `git diff --check`
  passed.
- The same five repository-wide formatter baseline files remain unformatted:
  `ssurgo_packages.py`, `ssurgo_regional_candidate.py`,
  `ssurgo_regional_coverage.py`, `workflow.py`, and `tests/test_aoi_policies.py`.

No provider access or raw-data acquisition was performed.
