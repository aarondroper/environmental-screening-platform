# NLCD map identify click path

## Outcome

Completed 2026-09-27. The Colorado job `27a5c1fa-e7d9-4523-aa95-177ca45b87ea` was used as the external integration fixture. Its job-scoped metadata and PNG routes returned the succeeded result, EPSG:4326 north-up display transform, exact AOI geometry hash, and a readable 957 × 722 RGBA asset.

The user-visible failure was in the frontend event/presentation boundary: identify output was written only to a small caption target, while the map click path had no explicit AOI-layer forwarding and made the usable handler depend on the asynchronous preview callback. The existing tests exercised the pixel function and source text, not a Leaflet-compatible click event updating visible DOM state. The overlay itself remains non-interactive.

The fix installs an unconditional map click controller immediately after map creation, forwards AOI-boundary clicks explicitly, keeps the image overlay `interactive: false`, and renders a persistent in-map identify panel. Outside-AOI checks now take precedence over raster bounds, and points inside the AOI but outside the preview footprint return an explicit no-observation state.

## Validation

- `cd frontend && npm test` — 41 passed.
- `cd frontend && npm run build` — passed; the built bundle contains the persistent panel and event controller.
- `.venv/bin/pytest -q` — 132 passed, 9 skipped for configured external/PostGIS fixtures.
- `.venv/bin/ruff check .` — passed.
- `.venv/bin/mypy src` — passed.
- CLI help, documentation-path scan, and `git diff --check` — passed.
- Local bridge HTTP smoke against the real Colorado job — succeeded for job status, job-scoped preview metadata, and PNG asset retrieval.

No browser binary is installed in this environment, so a manual desktop/mobile browser click pass could not be run here. The remaining manual verification is to click a valid pixel and an outside-AOI location in the served workspace; the deterministic fixture covers the explicit nodata/no-observation state, while the Colorado AOI itself reports zero AOI nodata in its recorded metrics.
