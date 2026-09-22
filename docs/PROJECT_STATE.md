# Project State

## Snapshot status

This is the authoritative factual snapshot of the current checkout. As verified on 2026-09-22, the repository is a governance-only baseline: it contains project instructions and planning documents, but no application implementation.

The repository contents, command behavior, and available metadata were inspected directly. No claim below is based solely on the intended architecture or product brief.

## Verified repository state

### Governance and planning files

The checkout contains:

- `AGENTS.md`;
- `docs/PROJECT_BRIEF.md`;
- `docs/PROJECT_STATE.md`;
- `docs/ARCHITECTURE.md`;
- `docs/DECISIONS.md`;
- `docs/BACKLOG.md`;
- `docs/QUALITY_GATES.md`;
- `docs/SOURCE_FEASIBILITY.md`; and
- completed source-feasibility plans under `docs/plans/completed/` (including the final-validation outcome for this task).

The `.agents/` and `.codex/` directories are also empty in this checkout.

### Version-control state

The canonical project root was confirmed by its `AGENTS.md` and governance files. After confirming the existing `.git/` was empty/invalid and no repository or remote existed, a local repository was initialized with owner authorization. Baseline documentation commit: `900a78d91a0985aa20f37c937e2266fbcf111120` on branch `master`; no remote is configured. Do not add a remote, push, or replace the repository without authorization.

### Application implementation

No implementation, configuration, or executable behavior was verified for:

- ingestion adapters, scheduled refresh, raw object storage, staging, or validation pipelines;
- PostgreSQL/PostGIS schema, migrations, or database services;
- API, OpenAPI contract, background worker, or queue;
- screening engine or source/version lineage;
- React/TypeScript frontend, MapLibre map, exports, or report generation;
- dependency manifests, Docker Compose, CI/CD workflows, deployment, or operational monitoring; or
- unit, integration, geospatial, frontend, or end-to-end tests.

No product command can currently be run because no application or tool configuration exists in the checkout.

## Implemented versus intended

| Area | Current factual state | Intended next state |
| --- | --- | --- |
| Governance | Instructions and project documents exist; their consistency has been reconciled in this task | Keep governance evidence-based as implementation arrives |
| Product scope | Defined in `PROJECT_BRIEF.md` as intended scope and non-goals | Preserve a small preliminary-screening platform |
| Geography | Owner-selected working geography: Northern Colorado Front Range, defined by the 2025 Census county boundaries for Boulder (08013), Larimer (08069), and Weld (08123). Census area attributes imply approximately 7,391 sq mi total; exact GIS geometry has not been downloaded into the project. | Preserve this three-county boundary unless owner changes it; retain boundary vintage and checksum on acquisition |
| Environmental sources | Owner-selected MVP direction: FEMA NFHL, USGS PAD-US 4.1, Annual NLCD Collection 1.2 (2025 land cover), 3DEP 1/3 arc-second DEM, and NRCS SSURGO hydric-soil information. Provider metadata/catalogues support public access and redistribution for these federal products. No source data/sample has been acquired or implemented; none has passed artifact-level validation. NWI is superseded for the MVP because its release-specific redistribution terms could not be confirmed. | Acquire small representative artifacts and verify actual access, integrity, CRS/schema/attributes, spatial coverage, and scale for each selected release before Milestone 2. Do not imply hydric soil is wetlands evidence or a jurisdictional-wetland determination. |
| Data architecture | Not implemented | Raw, staging, validation, versioned canonical PostGIS |
| API | Not implemented | FastAPI with documented contracts |
| Worker | Not implemented | Lightweight queued jobs for screening and likely ingestion |
| Frontend | Not implemented | React + TypeScript + MapLibre workflows |
| Local development | Not implemented | Reproducible Docker Compose environment |
| Tests | No test suite or test runner configuration exists | Meaningful unit, database, integration, data-contract, and frontend tests |
| CI/CD | No workflows or build configuration exists | GitHub Actions validation and automated deployment |
| Deployment | No deployment exists or is configured | Publicly demonstrable hosted application |

## Partially implemented

No application capability is partially implemented. The governance framework is the only established project structure at this stage.

## Known defects and limitations

- The project cannot yet ingest or screen data because no schema or executable application has been implemented and none of the five owner-selected source products has passed representative artifact validation. NWI is not an MVP dependency; it was superseded because exact release-specific redistribution terms could not be confirmed.
- The 2025 Census identifiers and area attributes support the selected three-county extent and approximate 7,391 sq mi total, but the actual boundary geometries have not been acquired, unioned, or topologically checked. Raster practicality is conditional on regional tile/window acquisition and has not been measured from source files.
- SSURGO is a soil survey. Component-level hydric ratings indicate hydric-soil information only; they are not wetland polygons and cannot establish presence or absence of jurisdictional wetlands.
- Architecture details that depend on actual source formats remain provisional.
- There is no verified runtime, test, deployment, cost, or performance baseline.
- No authentication, report, GeoPackage, or source-refresh behavior has been confirmed.
- The local Git baseline contains governance documents only; there is no configured remote. Source-validation evidence remains incomplete and must not be treated as source approval.

## Current blockers and decision points

1. The source workspace could not reach/download provider artifacts during final source validation. All five source releases therefore remain sample-unverified: actual archive integrity, CRS/schema, feature/raster characteristics, regional package volume and source coverage have not been checked.
2. The three-county geography has not had a topology/union geometry check because the Census boundary file/service was unavailable in the workspace. Keep the owner-approved extent intact; do not narrow it autonomously.
3. County/community-level FEMA products need an effective-date/coverage inventory at acquisition. Effective and pending products must remain separate; missing/unmapped coverage is unknown, not hazard-free.
4. For SSURGO, the exact intersecting soil survey areas and package volumes have not been enumerated. The WSS user-defined AOI has a 100,000-acre limit, so complete regional coverage should use the relevant SSA packages, with sample extraction for a small AOI. Confirm current release table schema from the acquired packages.
5. Milestone 2 has not begun. Carry the preliminary-only boundary into its future product contract, including explicit hydric-soil, flood-map coverage/effective-date, and terrain/land-cover limitations; do not invent regulatory thresholds or a composite score.

## Current development frontier

The former England recommendation is superseded. Northern Colorado Front Range, using the 2025 Census boundaries of Boulder, Larimer, and Weld counties, is the owner-selected working geography. The owner-selected MVP source direction is FEMA NFHL, PAD-US, Annual NLCD, 3DEP, and SSURGO hydric-soil information; NWI was superseded for the MVP because exact redistribution terms could not be confirmed. Official-record rights/access review found no material blocker for the five selected products, but none passed representative artifact validation. The three-county extent remains about 7,391 sq mi; county geometry topology and raster/package volumes are unverified. The immediate frontier is small-sample and boundary geometry validation; direct network checks again failed DNS for the official hosts listed in `docs/SOURCE_FEASIBILITY.md`. Milestone 2 has not begun and is gated on representative validation. Local Git is initialized with a documentation baseline commit and no remote.

## Evidence required for future updates

When this file is updated, agents should use concrete evidence such as:

- repository files, valid Git status/history, and configuration;
- passing test and build output;
- migration/application startup results;
- source acquisition and validation reports;
- deployment URLs, health checks, and smoke-test output; and
- inspected runtime behavior.

Documentation alone must not be used to convert an intended component into a verified one.
