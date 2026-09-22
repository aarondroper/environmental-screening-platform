# Bind screening jobs to source snapshots

## Objective

Capture the active source-version state when each screening job is created, then make execution, retry, result, and exports use that immutable snapshot without falling back to newer promotions or live acquisition.

## Outcome — completed 2026-09-22

- Added immutable `job_source_snapshots` records to the external SQLite catalog, including job/AOI lineage, source version, candidate/run references, maturity, coverage, observation, snapshot state, reason, timestamp, and provenance.
- Job creation resolves every requested source before processing. Active artifacts are checksum-checked; absent active versions become unknown/incomplete, PAD-US is quarantined, and FEMA is blocked. Unpromoted candidates are never substituted.
- Screening execution reads only the persisted snapshot. A disappeared or changed artifact is reported unavailable without mutating the historical snapshot. Retries reuse the same snapshot; a new job creates a fresh one.
- JSON, CSV, and GeoJSON exports include job/AOI identity, snapshot IDs, source-version IDs, source states, and explicit missing-source information.
- No PostGIS, source maturity change, provider substitution, composite metric, or deployment work was introduced.

## Validation

36 deterministic tests passed, including active/missing source states, PAD-US/FEMA behavior, later-promotion isolation, retry reuse, artifact disappearance, and all export formats. Ruff, mypy, CLI help, documentation link checks, and `git diff --check` passed.
