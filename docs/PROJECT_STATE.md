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
- completed source-feasibility plans under `docs/plans/completed/`, including the initial acquisition stop, targeted TIGER/FEMA recovery, and non-FEMA sample-validation outcome.

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
| Geography | Owner-selected geography remains Boulder (08013), Larimer (08069), and Weld (08123), official TIGER/Line 2025. The national ZIP was CRC-tested and only the three records were extracted outside Git. The selected features are valid in NAD83/EPSG:4269; their valid union is a three-component MultiPolygon with bounds (-106.195438, 39.912886, -103.573216, 41.001905), area about 7,391.206 sq mi, one 7,390.088 sq mi connected component and two detached source components totaling about 1.118 sq mi. No geography was narrowed or geometry repaired. The generalized TIGERweb sample is diagnostic only. | Retain the exact selected source geometry and its multipart components; use bounded regional processing and preserve the approved county union |
| Environmental sources | Owner-selected MVP direction remains FEMA NFHL, PAD-US 4.1, Annual NLCD Collection 1.2 (2025), 3DEP 1/3 arc-second, and SSURGO hydric-soil information; NWI remains excluded. FEMA is access-blocked with no effective/pending sample. PAD-US official metadata and five-feature service sample were acquired, but three geometries self-intersect and require an owner-approved staging repair/quarantine policy. NLCD 2025 GeoTIFF service sample passed basic raster checks; native-grid/full-region bytes remain unmeasured. 3DEP one tile passed GeoTIFF checks; bounding-box inventory has eight tiles totaling about 3.07 GB. SSURGO SDA identified 19 survey areas/1,878 whole-SSA map units and returned representative polygon/component hydric samples; full package bytes remain unmeasured. Evidence and checksums are in `SOURCE_FEASIBILITY.md` and the external manifest. | Resolve PAD-US geometry policy; validate FEMA effective/pending coverage; complete remaining source scale/window/package checks before Milestone 1 approval and Milestone 2. Hydric soil is not a wetland inventory or jurisdictional determination. |
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

- The project cannot yet ingest or screen data because no schema or executable application has been implemented. The official 2025 boundary and representative samples of NLCD, 3DEP, and SSURGO have passed bounded checks; PAD-US promotion remains blocked by invalid sample geometries and FEMA remains access-blocked. NWI is not an MVP dependency; it was superseded because exact release-specific redistribution terms could not be confirmed.
- The exact official 2025 TIGER/Line county archive was acquired (83,989,800 bytes; ZIP CRC passed) and filtered to the approved GEOIDs. Feature and union validity, NAD83/EPSG:4269, multipart structure, connectedness, area, and bounds were measured. The full union is a valid 3-component MultiPolygon; two small disconnected components are retained as present in the source. The generalized TIGERweb sample remains diagnostic. Raster practicality remains unmeasured.
- FEMA NFHL remains explicitly pending: official service/download routes reset TLS and the reachable `gis.fema.gov` directory does not list NFHL. No FEMA schema, effective/pending samples, effective dates, community/panel coverage or jurisdiction coverage were validated. PAD-US is accessible but three of five returned sample geometries have self-intersections; canonical handling is unresolved. NLCD WCS returned a 2025 sample but the native Albers tile/complete regional bytes remain unmeasured. 3DEP's eight-tile count is a bounding-box upper bound, with full tile storage estimated at 3.07 GB. SSURGO's 19-area inventory and sample data are validated, but full survey-area package byte totals remain unknown.
- SSURGO is a soil survey. Component-level hydric ratings indicate hydric-soil information only; they are not wetland polygons and cannot establish presence or absence of jurisdictional wetlands.
- Architecture details that depend on actual source formats remain provisional.
- There is no verified runtime, test, deployment, cost, or performance baseline.
- No authentication, report, GeoPackage, or source-refresh behavior has been confirmed.
- The local Git baseline contains governance documents only; no remote is configured. Raw validation artifacts remain outside Git. Source findings are not equivalent to final source approval.

## Current blockers and decision points

1. FEMA NFHL access is blocked. Required evidence remains official layer metadata plus county/community effective-feature samples, with community/panel IDs, dates/status, CRS, attributes, effective/pending separation, and mapped/unmapped coverage. Unknown or unmapped areas are not hazard-free. No substitution is approved.
2. Owner must decide how to handle PAD-US invalid geometries before canonical promotion: audited staging repair with raw preservation, or quarantine/reject with acknowledged coverage gaps. See `SOURCE_FEASIBILITY.md` for evidence and recommendation.
3. Finish bounding-box-versus-polygon tile inventory for 3DEP, measure a regional NLCD native-grid output, and measure/confirm SSURGO package or targeted-query regional storage. These are outstanding scale details, not evidence of source unsuitability.
4. Milestone 1 is partially validated; Milestone 2 has not begun. The approved 2025 three-county union is validated and unchanged.

## Current development frontier

The former England recommendation is superseded. Northern Colorado (Boulder, Larimer, Weld) and the five-source direction remain owner-approved; NWI remains excluded. The official TIGER/Line 2025 boundary is validated outside Git as a topologically valid three-component MultiPolygon totaling about 7,391.206 sq mi; every component is retained. Representative samples for NLCD, 3DEP, and SSURGO passed bounded checks. PAD-US produced three self-intersecting geometries among five returned features and requires an owner policy for audited repair versus quarantine. FEMA NFHL remains provider-access blocked and has no validated effective/pending samples. Milestone 1 is partially validated, not complete; Milestone 2 has not begun. The local Git repository has no remote; raw samples/manifest are external.

## Evidence required for future updates

When this file is updated, agents should use concrete evidence such as:

- repository files, valid Git status/history, and configuration;
- passing test and build output;
- migration/application startup results;
- source acquisition and validation reports;
- deployment URLs, health checks, and smoke-test output; and
- inspected runtime behavior.

Documentation alone must not be used to convert an intended component into a verified one.
