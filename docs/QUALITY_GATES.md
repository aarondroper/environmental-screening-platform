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

Tests use small generated geometries, rasters, and provider responses; they do not require internet, the personal toolkit, or the external source-artifact directory. The live AOI smoke run in `PROJECT_STATE.md` was separately run against official services and existing external Census data. It is evidence for that run only, not a standard offline test or regional source approval. There is no frontend, CI/CD, or deployment check; do not report those as passed. The repository now contains an optional Compose configuration and SQL migrations for the AOI and representative SSURGO fixture boundaries, which are covered by static checks and the opt-in integration test described below.

The local PostGIS boundary is optional. When Docker Desktop, an external `ESGP_POSTGIS_DATA_DIR`, `ESGP_POSTGIS_URL`, and the optional `.[postgis]` dependency are available, run `docker compose up -d postgis`, `.venv/bin/screening --data-dir "$DATA_DIR" postgis-migrate`, and the opt-in PostGIS integration test. If those prerequisites are unavailable, report the integration test as skipped/unavailable; deterministic migration/configuration and geometry-contract checks still apply. The live integration set covers the Census AOI and representative SSURGO fixture staging/validation/promotion. Never claim a database migration or insertion succeeded from static checks alone.

Keep inventorying tracked/visible files, inspecting `git status`, checking documentation links/paths, and distinguishing unavailable checks from passing checks as those systems are added. Do not invent commands for tools that are not configured.

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
