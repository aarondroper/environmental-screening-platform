# NLCD bridge lifecycle fix

## Objective

Correct ownership of the local generic-AOI NLCD job lifecycle so bridge phase
updates do not transition the canonical job before `run_job` does.

## Outcome

- Bridge acquisition, promotion, and screening phases now update only the
  informational bridge envelope.
- Workflow helpers perform strict queued/processing/failed retry transitions;
  successful worker execution owns `queued -> processing -> completed`.
- Acquisition failures use `queued -> processing -> failed`, and retries use
  `failed -> queued` without changing the immutable AOI or source snapshot.
- Regression coverage verifies generic Colorado AOI lineage, retry behavior,
  no stale DC preview/metrics, strict duplicate-transition rejection, and a
  real unavailable-source `run_job` path.

## Validation

- `.venv/bin/python -m pytest -q`: 128 passed, 9 skipped.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/mypy src`: passed.
- `cd frontend && npm test && npm run build`: passed.
- `git diff --check`: passed.
- CLI help was exercised with `.venv/bin/screening --help`.
- No PostGIS or opt-in external-fixture checks were required for this local
  lifecycle fix.
