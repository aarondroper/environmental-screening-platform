# Backlog

## How to use this backlog

This is the prioritized roadmap of remaining project work. It is organized into milestones rather than fine-grained implementation tasks. Detailed, temporary execution plans belong in `docs/plans/active/` and move to `docs/plans/completed/` when finished.

Milestones may be refined as evidence arrives, but agents must not silently alter product scope, scientific methodology, important datasets, or operating cost without crossing the decision boundary in `AGENTS.md`.

Current status: no implementation milestone has verified its acceptance criteria. US candidate-region research is complete; Northern Colorado and the five-source MVP direction are owner-selected. Final representative artifact/boundary validation remains incomplete, so Milestone 1 is not closed and Milestone 2 has not begun.

## Milestone 1 — Geography and source feasibility

**Priority:** P0 — prerequisite

**Status:** The previous England recommendation and NWI MVP source are superseded. Owner selected Northern Colorado (Boulder, Larimer, Weld; approx. 7,391 sq mi) and the five-source direction: FEMA NFHL, PAD-US, Annual NLCD, 3DEP, and SSURGO hydric-soil information. Official-record reuse evidence is available, but actual product samples, package scales/volumes, data-level CRS/schema/coverage and county-union topology have not been validated. Milestone 1 remains open pending that evidence. A local documentation baseline commit now exists; no remote is configured.

**Objective:** Complete artifact-level validation of the owner-selected contained geography and approximately five authoritative public environmental sources before defining the screening contract.

**Major deliverables:**

- acquired 2025 Census county boundary data for GEOIDs 08013, 08069, and 08123; validate polygon and union topology, CRS and checksum without changing the selected extent;
- exact source release/product artifacts or region-scoped samples for NFHL, PAD-US 4.1, Annual NLCD Collection 1.2 (2025), 3DEP 1/3 arc-second, and current SSURGO packages for every intersecting SSA;
- verify actual archive/file integrity, formats, CRS, geometry/raster properties, key fields/domains, extents, coverage and measured approximate scale/volume;
- source-specific ingestion/QA design, including FEMA effective/pending and unknown coverage, regional raster windows, and SSURGO component hydric-rating lineage/interpretation;
- retain source-specific public-use/redistribution evidence and release/effective-date provenance in project documentation.

**Dependencies:** None beyond access to public source documentation/data.

**Acceptance criteria:** County identity/vintage and union geometry validate; all five exact products have suitable public-use/redistribution terms and repeatable access; representative artifacts pass source-specific integrity, schema/CRS, coverage and scale checks; regional raster processing and total hosted/local volume are demonstrably bounded; no owner-level source or geography decision remains. NWI is outside the MVP and must not be silently reintroduced. Milestone 2 starts only after these criteria pass. Do not create a remote or push without owner authorization.

## Milestone 2 — Screening workflow and product contract

**Priority:** P0 — prerequisite

**Objective:** Define the analyst workflow, result structure, source-specific metrics, and preliminary-screening limitations.

**Major deliverables:**

- project/AOI lifecycle;
- screening job lifecycle;
- per-source metric definitions;
- result and export contract;
- transparent wording for limitations and non-regulatory use;
- decision on drawing versus simple upload for the initial workflow.

**Dependencies:** Completion of Milestone 1, including validated samples for every selected source and the three-county boundary union.

The product contract must cover project/AOI behavior; transparent per-source metrics for mapped FEMA zones, SSURGO hydric-soil indicators, terrain, land cover and protected areas; source versions/effective dates and lineage; result structure and exports; asynchronous job states; missing/unknown coverage; and preliminary-screening limitations. It must not create a composite score, regulatory thresholds, a wetland determination, or an implication of jurisdictional-wetland presence/absence.

**Acceptance criteria:** A reviewer can understand what the platform calculates for every selected source, which dataset versions are used, what a completed result contains, and what the product explicitly does not conclude.

## Milestone 3 — Repository foundation and local platform

**Priority:** P0

**Objective:** Establish a self-contained, reproducible development foundation.

**Major deliverables:**

- Python/backend and frontend project structure;
- Docker Compose environment;
- PostGIS service and initial configuration;
- queue/object-storage development equivalents if retained;
- dependency and environment documentation;
- migration tooling foundation;
- baseline lint, type, test, and build commands.

**Dependencies:** Milestones 1–2 for source- and workflow-aware boundaries.

**Acceptance criteria:** A fresh checkout can start the documented local services and execute baseline checks without relying on the toolkit or undocumented local state. The local Git governance baseline already exists; remote hosting remains outside this milestone absent authorization.

## Milestone 4 — Data model, migrations, and source catalog

**Priority:** P0

**Objective:** Implement the metadata and canonical schema needed for provenance, versioning, projects, jobs, and results.

**Major deliverables:**

- Alembic migration history;
- dataset/source catalog;
- dataset versions and ingestion runs;
- project and project-area entities;
- screening jobs/results and version lineage;
- spatial indexes and appropriate conventional indexes;
- migration and constraint tests.

**Dependencies:** Milestones 1–3.

**Acceptance criteria:** A fresh database can be migrated reproducibly; the schema expresses active/superseded versions and failed runs; spatial columns and indexes support the defined workflows; no manual-only schema step is required.

## Milestone 5 — Ingestion, raw archive, validation, and safe promotion

**Priority:** P0

**Objective:** Build the heterogeneous ETL platform for the selected sources.

**Major deliverables:**

- source-specific adapters;
- retries, timeouts, pagination, and change detection where relevant;
- raw snapshot storage and provenance metadata;
- staging and normalization;
- CRS normalization and geometry repair policy;
- source-specific data-quality gates;
- idempotent ingestion;
- atomic or equivalently safe version promotion;
- failure visibility and preservation of the previous active version.

**Dependencies:** Milestones 1, 3, and 4.

**Acceptance criteria:** Representative fixtures or controlled source samples can be ingested reproducibly; reruns do not create unnecessary duplicates; malformed or anomalous candidates fail visibly; a failed candidate cannot replace a known-good active version.

## Milestone 6 — Screening engine and background execution

**Priority:** P0

**Objective:** Implement transparent geospatial screening as retry-safe asynchronous jobs.

**Major deliverables:**

- queue/worker implementation;
- job state transitions and retries;
- AOI validation;
- per-source spatial calculations;
- persisted metrics, findings, and source-version lineage;
- known-AOI fixtures and integration tests;
- query profiling and targeted spatial optimization.

**Dependencies:** Milestones 2, 4, and 5.

**Acceptance criteria:** A screening request returns without waiting for the full calculation; the worker produces deterministic, interpretable results for known fixtures; failures are recoverable and visible; retries do not create inconsistent duplicate results.

## Milestone 7 — Backend API and operational endpoints

**Priority:** P1

**Objective:** Expose stable application and data-operations contracts.

**Major deliverables:**

- project and AOI endpoints;
- screening submission/status/result endpoints;
- dataset/version/ingestion-status endpoints;
- health/readiness endpoints;
- download endpoints or signed-download workflow;
- request/response validation and error handling;
- OpenAPI documentation;
- API integration tests.

**Dependencies:** Milestones 4–6.

**Acceptance criteria:** The documented API supports the core analyst and operations workflows, returns useful errors without raw stack traces, and passes integration tests against a representative database/worker setup.

## Milestone 8 — Web application and map-based review

**Priority:** P1

**Objective:** Deliver a polished internal consultancy interface.

**Major deliverables:**

- project list and creation;
- AOI drawing/viewing;
- screening submission and job-state UI;
- result summary and per-dataset findings;
- MapLibre map with controlled layer visibility and inspectable findings;
- data-operations/source-status view;
- downloads;
- accessible, responsive, visually verified states.

**Dependencies:** Milestones 2 and 7.

**Acceptance criteria:** A user can complete the primary workflow in the browser, understand queued/processing/completed/failed states, inspect map results without overwhelming layer density, and use the product on a smaller screen for core tasks.

## Milestone 9 — Exports and optional reporting

**Priority:** P1

**Objective:** Provide professional handoff outputs.

**Major deliverables:**

- CSV screening summary;
- project boundary export;
- GeoJSON or equivalent web-friendly spatial export;
- decision on GeoPackage;
- decision and implementation for concise PDF report if retained.

**Dependencies:** Milestones 2, 6, and 7.

**Acceptance criteria:** Outputs contain the expected project, metric, provenance, and limitation information; spatial outputs are valid and usable in representative GIS tooling; failures are reported clearly.

## Milestone 10 — CI, CD, deployment, and operational visibility

**Priority:** P1

**Objective:** Make the platform reproducibly testable and publicly demonstrable.

**Major deliverables:**

- GitHub Actions pull-request checks;
- database/migration and geospatial contract validation in CI;
- frontend/backend/container build checks;
- affordable hosted architecture;
- migration-aware main-branch deployment;
- secrets and environment handling;
- post-deployment smoke/health checks;
- structured logs, job/source status, and freshness visibility;
- rollback or recovery documentation.

**Dependencies:** Milestones 3–8; hosting choice requires an explicit cost/architecture decision.

**Acceptance criteria:** A main-branch change passes automated checks before deployment; the deployed application, API, worker, database, and storage are usable together; smoke checks verify the release; failures are discoverable without local production debugging.

## Milestone 11 — Final validation, performance, security, and portfolio release

**Priority:** P2

**Objective:** Perform the final credibility pass and prepare public documentation.

**Major deliverables:**

- end-to-end validation and known-AOI results;
- spatial query/performance review;
- security and secret review;
- accessibility and responsive review;
- repository cleanup and human-readable architecture explanation;
- portfolio case study and limitations.

**Dependencies:** All preceding milestones.

**Acceptance criteria:** The repository and deployment make only evidence-backed claims, meaningful quality gates pass, important failure paths are understood, and the project can be evaluated as a complete production geospatial system.
