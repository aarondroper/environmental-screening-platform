# Local NLCD screening bridge

## Outcome

Implemented a development-only standard-library HTTP bridge and primary
frontend action for screening a validated user-loaded AOI with Annual NLCD
only. The bridge persists a generic project and immutable AOI revision,
creates a deferred job, delegates acquisition/validation/AOI-scoped promotion
and snapshot-pinned screening to the existing workflow, and returns truthful
queued/running/succeeded/failed states.

The bridge retains failed attempts, supports retrying failed jobs, preserves
exact AOI/source/checksum lineage, and rejects stale result presentation. The
frontend keeps 3DEP, SSURGO, FEMA, and PAD-US explicitly not evaluated and does
not reuse the Washington, DC demonstration metrics or generate a browser
preview.

## Verification

- Python tests: `127 passed, 9 skipped`.
- Focused bridge tests cover success, failed acquisition/retry, and stale
  geometry lineage rejection.
- Frontend tests: `32 passed`; production build succeeded.
- Ruff check/format, mypy, CLI help, and `git diff --check` passed.
- PostGIS/provider integration remains optional and was not required by this
  local bridge slice.
