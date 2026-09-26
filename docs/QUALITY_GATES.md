# Quality Gates

## Purpose

These gates define the checks an agent should consider before declaring work complete. Apply the gates proportionally to the change, but do not skip a relevant gate merely because the change appears small. A passing lint command is not evidence that data, scientific behavior, deployment, or UX is correct.

## Current Milestone 2B package baseline

The repository has a local Python CLI/package and deterministic tests. From the repository root, use Python 3.12 for the configured type-check target:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/mypy src
.venv/bin/screening --help
```

Tests use small generated geometries, rasters, and provider responses; the deterministic suite does not require internet, the personal toolkit, or the external source-artifact directory. The NLCD and 3DEP external-fixture integration checks are opt-in via `ESGP_NLCD_FIXTURE_PATH` and `ESGP_3DEP_FIXTURE_PATH` and must be reported separately from the deterministic suite. The live AOI smoke run in `PROJECT_STATE.md` was separately run against official services and existing external Census data. It is evidence for that run only, not a standard offline test or regional source approval. There is no frontend, CI/CD, or deployment check; do not report those as passed. The repository now contains an optional Compose configuration and SQL migrations for the AOI, representative SSURGO fixture, and derived regional SSURGO staging boundary, which are covered by static checks and the opt-in integration tests described below.

The local PostGIS boundary is optional. When Docker Desktop, an external `ESGP_POSTGIS_DATA_DIR`, `ESGP_POSTGIS_URL`, and the optional `.[postgis]` dependency are available, run `docker compose up -d postgis`, `.venv/bin/screening --data-dir "$DATA_DIR" postgis-migrate`, and the opt-in PostGIS integration tests. If those prerequisites are unavailable, report the integration tests as skipped/unavailable; deterministic migration/configuration and geometry-contract checks still apply. The live integration set covers the Census AOI, representative SSURGO fixture staging/validation/promotion, and the owner-approved regional SSURGO staging fixture/rollback path. A full regional staging run must additionally report direct PostGIS counts, lineage, geometry validity, quarantine status, raw-artifact integrity, and unchanged SQLite candidate states. The bounded `screen-fixtures` command additionally requires the configured PostGIS repository for a successful SSURGO result, but it must preserve NLCD/3DEP results and report SSURGO unavailable when PostGIS cannot be used. Never claim a database migration or insertion succeeded from static checks alone.

The inactive regional SSURGO candidate gate is separate from PostGIS promotion. Run `.venv/bin/screening --data-dir "$DATA_DIR" materialize-ssurgo-regional-candidate` only after the external staging aggregate, package reports, raw checksums, package candidates/runs, repair audit, and package QA have been verified. Confirm the resulting candidate is `incomplete`/`conditionally_validated`/`partial`/`not_promoted`, rerun the command to verify idempotence, and query `active-version --source ssurgo` to confirm the active pointer was not created or changed. This gate does not establish full regional coverage or production readiness.

For the regional Annual NLCD acquisition slice, run `.venv/bin/screening --data-dir "$DATA_DIR" ingest-nlcd-regional` only with the exact external 2025 Census boundary available. Confirm the response is the official WCS GeoTIFF, the candidate/source-version/run retain the exact request and checksum, the raster passes EPSG:5070/nominal-30-m/nodata/class-domain/AOI-coverage checks, and `active-version --source annual_nlcd` remains absent. The measured rectangular response includes outside-AOI pixels; verify those are recorded as non-observations. This command is validation-only and does not establish final source approval or production refresh readiness.

For the AOI-agnostic NLCD acquisition slice, run the deterministic generic-AOI tests and inspect `.venv/bin/screening --data-dir "$DATA_DIR" ingest-nlcd --help`. Confirm the persisted AOI revision and geometry hash are carried into the candidate provenance, the exact native-grid WCS request is bounded before HTTP, nodata/outside-AOI accounting remains explicit, and `active-version --source annual_nlcd` is unchanged. A new generic-AOI live request is optional and must be reported separately from mocked/local validation.

For the AOI-agnostic 3DEP tile acquisition slice, run the deterministic tile-plan/acquisition tests and inspect `.venv/bin/screening --data-dir "$DATA_DIR" ingest-3dep --help`. Confirm the persisted AOI revision and geometry hash are carried into the plan and every candidate, the official TNM inventory response is complete before downloads, the deterministic plan is written before any tile request, and excessive AOIs/tile counts fail explicitly. Confirm each native tile is independently checksum-recorded and validated for EPSG:4269, 1/3-arc-second resolution, dimensions, datatype, transform, nodata, readability, and footprint coverage; nodata/uncovered areas remain unknown, failed tile attempts remain queryable, and `active-version --source 3dep` is unchanged. No generic-AOI live tile download is required for this deterministic slice; report it separately if performed.

For the AOI-agnostic SSURGO package acquisition slice, run the mocked SDA/package tests and inspect `.venv/bin/screening --data-dir "$DATA_DIR" ingest-ssurgo --help`. Confirm the persisted AOI revision and geometry hash enter the deterministic plan and every candidate, SDA discovery uses the official `SDA_Get_Areasymbol_from_intersection_with_WktWgs84` function joined to `sacatalog`, WSS URLs are derived from discovered release metadata, package count and total-byte limits are enforced before bodies are acquired, and provider/measured sizes, HTTP metadata, checksums, and ZIP structure are retained. Run the documented small live smoke only with a generic AOI outside Northern Colorado; confirm the candidate remains inactive and `active-version --source ssurgo` is unchanged. This path does not stage, repair, clip, measure coverage, or promote SSURGO.

For the inactive regional candidate, run `.venv/bin/screening --data-dir "$DATA_DIR" analyze-ssurgo-regional-coverage --candidate-id CANDIDATE_ID --database-url "$ESGP_POSTGIS_URL"` only against the existing staging batches. Confirm the command uses a read-only PostGIS transaction, writes aggregate/per-package/diagnostic reports outside Git, records report checksums in the external manifest and candidate validation, and leaves staging rows, raw packages, and the active-version pointer unchanged. Review AOI coverage, uncovered residuals, package overlaps, outside-AOI area, and gap classifications; never treat uncovered soil area as absence of a constraint.

Keep inventorying tracked/visible files, inspecting `git status`, checking documentation links/paths, and distinguishing unavailable checks from passing checks as those systems are added. Do not invent commands for tools that are not configured.

For the generic multi-source AOI ingestion slice, run `pytest tests/test_aoi_ingestion.py`, inspect `screening ingest-aoi --help`, and exercise a dry run with a persisted generic AOI. Confirm the external plan is written before any adapter call, its ID is deterministic for the same AOI/source/limit inputs, the parent catalog row carries the immutable geometry hash, and no raw artifact or child acquisition appears in dry-run mode. Mock independent source outcomes to verify success/partial/failure aggregation, checksum-error visibility, byte/artifact limits, retry history, and idempotence. If a live smoke is performed, retain raw artifacts outside Git and report provider access separately; do not infer source maturity or promotion from the parent status.

For AOI-scoped raster promotion, run `pytest tests/test_aoi_raster_promotion.py` and inspect `screening promote-candidate --help` and `screening active-version --help`. Confirm that generic Annual NLCD and 3DEP promotion requires the exact project, immutable AOI revision, geometry hash, acquisition run, and source-version lineage; rehashes the external artifact; checks complete AOI coverage, native raster metadata, eligible observation state, and zero AOI nodata; and writes an auditable decision plus an AOI-scoped active pointer. Confirm that checksum, AOI, version, coverage, nodata, and failed-replacement cases remain inactive and do not change a prior active pointer. Confirm that unscoped fixture aliases and SSURGO/PAD-US/FEMA states are unchanged.

For snapshot-pinned active raster screening, run `pytest tests/test_active_screening.py` and inspect `screening screen-active --help`. Confirm that only the exact AOI-scoped active NLCD/3DEP pointers are snapshotted and processed, missing/unpromoted states remain explicit, native raster windows/metadata and nodata accounting are preserved, retry reuses the original snapshots, later promotion affects only a new job, and JSON/CSV/GeoJSON retain AOI and source lineage. The retained Washington, DC smoke is opt-in via `ESGP_RUN_LIVE_SMOKE=1`; it performs no network acquisition.

For the read-only AOI operational report, run `pytest tests/test_aoi_run_report.py` and inspect `screening report-aoi-run --help`. Confirm that a persisted project/AOI/revision report includes exact geometry/policy/area identity, deterministic plans, child attempts/retries, artifacts/checksums/source versions, candidates, validation outcomes, promotions, active AOI pointers, screening jobs/snapshots/results, and independent per-source lifecycle states. Confirm JSON is deterministic, `--format summary` is concise, no provider is contacted, and no unknown or failed state is collapsed into overall success.

## Evidence and scope gate

- Inspect the actual repository, git status, relevant code, tests, configuration, and executable behavior before changing or claiming anything.
- Confirm the work belongs to the current backlog objective and has not silently expanded product scope.
- Identify assumptions, unresolved decisions, external dependencies, and unverified claims.
- Preserve unrelated user changes and avoid destructive operations.

## Correctness gate

- The implementation satisfies the stated acceptance criteria.
- Normal success paths and important failure paths are handled explicitly.
- State transitions are valid and cannot silently skip required steps.
- API, database, worker, frontend, and export boundaries agree on data contracts.
- Error messages are useful to users/operators without exposing raw stack traces or secrets.

## Automated testing gate

Use the relevant layers for the change:

- unit tests for parsers, transforms, validation, checksums, geometry handling, and screening calculations;
- database and migration tests against a fresh suitable database;
- integration tests for ingestion, API requests, queue/worker execution, and screening workflows;
- geospatial contract tests for CRS, geometry validity, required fields, plausible extents/counts, and known-AOI results;
- frontend tests for important product workflows and failure states.

Do not substitute arbitrary coverage percentage for meaningful behavior. Record any unrun or unavailable tests.

## Linting and static-analysis gate

- Run the repository's configured Python lint/format checks.
- Run frontend lint/format checks where applicable.
- Run type checking for Python/frontend code where configured.
- Resolve new warnings or explain intentional exceptions.
- Review generated code and configuration for accidental dead or duplicated logic.

## Build gate

- Production frontend build succeeds.
- Backend/package/container builds succeed where affected.
- Database migrations apply from a clean database and are consistent with runtime models.
- Build output does not contain accidental secrets, temporary files, debug artifacts, or untracked required assets.

## Geospatial data-validation gate

For source and ETL work, verify as applicable:

- source identity, license, acquisition time, and provenance are recorded;
- retries, timeouts, pagination, and change detection behave as intended;
- required fields and expected geometry types exist;
- CRS is recognized and normalized deliberately;
- geometries are valid or repaired according to an explicit policy;
- spatial extents and feature counts are plausible for the selected geography;
- raster dimensions, resolution, nodata, and coverage are plausible where relevant;
- duplicate handling and idempotent reruns are tested;
- failed candidates cannot replace the last valid active version;
- raw snapshots/checksums are retained according to the designed lineage.

Do not activate a dataset solely because the HTTP request or parser succeeded.

## Scientific and analytical-validity gate

- Screening metrics match the approved workflow and source definitions.
- Units, CRS, area/length calculations, and distance semantics are correct.
- Known test geometries produce expected results.
- Any raster sampling/zonal calculation handles nodata, resolution, and alignment deliberately.
- Thresholds, hazard interpretations, and regulatory-facing language are evidence-backed or explicitly marked as owner decisions.
- No unsupported composite environmental score or misleading certainty is introduced.
- Results state that they are preliminary where appropriate.

## Reproducibility gate

- A fresh checkout can follow the documented setup.
- Required services, migrations, fixtures, and environment variables are documented.
- Tests do not rely on undocumented local state, stale generated files, or a developer-specific path.
- External-source acquisition is repeatable or the limitation is recorded.
- Toolkit patterns, if adapted, are copied into project-owned code without runtime coupling.

## Error-handling and resilience gate

- Network calls have appropriate timeouts and bounded retries.
- Partial ingestion and worker failures are recorded and recoverable.
- Job retries are idempotent and do not create inconsistent duplicate results.
- Previous valid data remains available after a failed update.
- API and UI expose actionable status for queued, processing, complete, failed, stale, or unavailable states where applicable.

## Security and privacy gate

- Secrets are not committed, logged, embedded in frontend bundles, or included in fixtures.
- Inputs are validated, including uploaded geometries and download parameters.
- Database access uses appropriate parameterization and least privilege for the scope.
- File/object paths, URLs, and export handling do not permit unintended traversal or uncontrolled access.
- Authentication/authorization behavior, if implemented, matches the approved scope.
- Public claims and operational endpoints do not expose unnecessary sensitive infrastructure detail.

## Performance gate

- Spatial indexes exist where expected and are actually used or justified otherwise.
- Representative queries and screening jobs complete within the intended modest resource envelope.
- Query plans are inspected before adding advanced optimization techniques.
- Large geometries, raster operations, pagination, and downloads have bounded behavior.
- The frontend does not load every source layer or oversized result unnecessarily.

## Accessibility and responsive-UI gate

For frontend changes:

- keyboard navigation and visible focus are usable;
- controls have meaningful labels and status text;
- color is not the only indicator of state;
- map and tabular information has an understandable non-map path where practical;
- loading, empty, error, and completed states are represented;
- core workflows remain usable on smaller screens even though desktop is primary.

## Visual-verification gate

- Inspect the changed UI in a production-like build or equivalent runtime.
- Verify map sizing, layer visibility, legends, labels, popups, loading states, and error states where affected.
- Check that the product feels like a restrained internal consultancy tool rather than a generic admin template or decorative story map.
- Remove debug overlays, placeholder copy, accidental browser defaults, and visual regressions.

## Documentation gate

- Update `docs/PROJECT_STATE.md` when verified reality changes.
- Update `docs/BACKLOG.md` when work is completed, superseded, split, or found unnecessary.
- Update `docs/ARCHITECTURE.md` when the implemented architecture changes.
- Update `docs/DECISIONS.md` only for consequential decisions.
- Keep setup, source provenance, limitations, test commands, deployment behavior, and operational behavior accurate.
- Do not write documentation that claims unverified implementation or deployment.

## Deployment-verification gate

For deployment or release work:

- CI passes the relevant checks before deployment.
- Migrations are applied or verified safely.
- API, worker, database, object storage, and frontend configuration agree.
- Health/readiness endpoints and a representative smoke workflow succeed after deployment.
- Logs/status expose failures and freshness problems sufficiently for diagnosis.
- Rollback or recovery behavior is documented, even if manual.
- The deployed result is checked in the actual target environment, not inferred from a local build.

## Self-review gate

Before declaring a milestone complete, inspect the final diff and repository state as if reviewing another developer's contribution. Look for incomplete work, accidental scope expansion, incorrect assumptions, dead or duplicated code, fragile errors, missing tests, stale documents, misleading completion claims, generated artifacts, and temporary files that should not be committed.

## Completion statement

The final work summary should state:

1. what changed;
2. what was actually verified and with which checks;
3. what remains unverified or unresolved;
4. any decision boundary reached;
5. how project state, backlog, plans, and other documentation were updated.
