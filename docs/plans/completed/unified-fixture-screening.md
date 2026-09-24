# Unified bounded fixture screening

## Outcome

Implemented the explicit `screen-fixtures` workflow. It binds the job to the
validated immutable Census AOI revision and the exact five-source snapshot set
(`ssurgo`, `annual_nlcd`, `3dep`, `padus`, `fema_nfhl`). It reuses the existing
SSURGO, NLCD, and 3DEP processors, while PAD-US and FEMA remain status-only
(`quarantined` and `blocked`).

The result preserves independent source metrics, provenance and checksums,
source maturity/coverage/observation/availability states, warnings, and a
source-status matrix. `job_status=completed` is separate from
`overall_status=partial`; fixture scope is explicit and no missing source is
treated as absence. CSV remains one row per source, JSON retains nested source
results, and GeoJSON contains only the AOI and meaningful SSURGO/3DEP
geometries.

## Verification

- Full fixture-enabled suite: 53 passed, 5 optional PostGIS tests skipped.
- Live PostGIS regression for Census/SSURGO paths: 10 passed, 1 configuration
  assertion intentionally deselected.
- Unified tests cover successful source orchestration, exact snapshot use,
  PAD-US/FEMA propagation, one-source artifact failure, partial status,
  retry/fresh-version behavior, provenance, checksums, and all exports.
- Ruff, format check, mypy, CLI help, Markdown relative-link checks, and
  `git diff --check` passed.

## Boundaries retained

- Individual Census, SSURGO, NLCD, and 3DEP processors were not changed.
- No PAD-US or FEMA processing, regional acquisition, composite score,
  suitability conclusion, or regulatory interpretation was added.
- Regional SSURGO survey-area/package sizing remains a separate backlog task.
