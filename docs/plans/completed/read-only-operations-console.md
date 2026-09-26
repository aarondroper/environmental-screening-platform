# Read-only operations console

## Outcome

Implemented a dependency-free static operations console under `frontend/`.
It consumes the existing `report-aoi-run` JSON read model and includes a
checked-in recorded Washington, DC smoke report at
`frontend/public/demo/report.json`.

The console presents AOI identity, immutable geometry hash, deterministic plan,
ingestion lifecycle, source state matrix, retries, artifact sizes/checksums,
validation, candidates, promotion/active-version state, immutable snapshots,
source metrics, warnings, and explicit incomplete/unknown/unavailable states.
It does not contact providers, require the Python backend/PostGIS/raw
artifacts, add a map, or change screening behavior.

## Validation

- `cd frontend && npm test`: 4 passed.
- `cd frontend && npm run build`: passed; static `dist/` output generated.
- Static HTTP smoke served `frontend/dist` and returned the console shell and
  demo JSON.
- Python suite: 118 passed, 9 documented environment-dependent skips.
- Ruff, formatter, mypy, CLI help, documentation links, and `git diff --check`:
  passed.
