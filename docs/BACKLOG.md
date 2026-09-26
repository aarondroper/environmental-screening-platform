# Backlog

## How to use this backlog

This is the prioritized roadmap of remaining project work. It is organized into milestones rather than fine-grained implementation tasks. Detailed, temporary execution plans belong in `docs/plans/active/` and move to `docs/plans/completed/` when finished.

Milestones may be refined as evidence arrives, but agents must not silently alter product scope, scientific methodology, important datasets, or operating cost without crossing the decision boundary in `AGENTS.md`.

Current status: Northern Colorado and the five-source MVP direction are owner-selected. Final Milestone 1 source approval remains open for full regional PAD-US coverage/repair results and FEMA technical access/effective-pending validation. The exact 2025 boundary is validated. NLCD, 3DEP, and SSURGO representative samples passed bounded validation; the automated regional NLCD WCS window also passed raster validation but remains an inactive validation-only candidate. All 19 official SSURGO survey-area package bodies are acquired; read-only package QA found 13 passes and 6 explicit failures (10 original invalid polygons and 2 harmless survey-name variations), with all 19 intersecting the AOI. The discrepancy audit accepted all 10 derived repairs under owner policy, and the derived staging run loaded all 19 packages without quarantine; raw packages and original geometries remain unchanged. The package candidates and one derived regional candidate remain inactive, and no regional canonical source is promoted. Milestone 2B.1 is a local file-backed ETL/screening slice; 2B.2 adds durable SQLite source-version/run/candidate metadata and explicit safe promotion; 2B.3 binds each screening job to an immutable source snapshot; 2B.4 adds an optional local PostGIS AOI repository boundary; 2B.5 adds a fixture-only SSURGO map-unit/component staging and promotion path; 2B.6 consumes only the matching fixture-only SSURGO rows in a bounded screening job; 2B.7 consumes only the matching NLCD raster artifact in an explicit fixture-only mode; 2B.8 consumes only the matching 3DEP raster artifact in an explicit fixture-only mode; 2B.9 unifies those fixture paths with PAD-US/FEMA status-only outcomes; 2B.10 adds owner-approved derived regional SSURGO staging only; 2B.11 materializes that staging as an inactive, checksum-protected candidate; 2B.13 adds the automated regional Annual NLCD acquisition and validation path without changing source maturity or activation. These remain a local prototype, not a production platform or final source approval. See `PROJECT_STATE.md` for measured integration artifacts and precise limits.
Current status: Northern Colorado and the five-source MVP direction are owner-selected, with Northern Colorado now treated as the known-good regression/demo fixture rather than a platform-wide AOI boundary. Final Milestone 1 source approval remains open for full regional PAD-US coverage/repair results and FEMA technical access/effective-pending validation. The exact 2025 boundary is validated. NLCD, 3DEP, and SSURGO representative samples passed bounded validation; the automated regional NLCD WCS window also passed raster validation but remains an inactive validation-only candidate. All 19 official SSURGO survey-area package bodies are acquired; read-only package QA found 13 passes and 6 explicit failures (10 original invalid polygons and 2 harmless survey-name variations), with all 19 intersecting the fixture AOI. The discrepancy audit accepted all 10 derived repairs under owner policy, and the derived staging run loaded all 19 packages without quarantine; raw packages and original geometries remain unchanged. The package candidates and one derived regional candidate remain inactive, and no regional canonical source is promoted. Milestone 2B.1 is a local file-backed ETL/screening slice; 2B.2 adds durable SQLite source-version/run/candidate metadata and explicit safe promotion; 2B.3 binds each screening job to an immutable source snapshot; 2B.4 adds an optional local PostGIS AOI repository boundary; 2B.5 consumes a fixture-only SSURGO map-unit/component path; 2B.6 consumes matching fixture-only SSURGO rows; 2B.7 consumes the matching NLCD fixture; 2B.8 consumes the matching 3DEP fixture; 2B.9 unifies those fixture paths with PAD-US/FEMA status-only outcomes; 2B.10–2B.13 record regional SSURGO staging/disposition and automated fixture-region NLCD acquisition. These remain a local prototype, not a production platform or final source approval. See `PROJECT_STATE.md` for measured integration artifacts and precise limits.

## AOI-agnostic foundation — first refactor

The current AOI-agnostic implementation frontier includes generic Annual NLCD acquisition, bounded 3DEP tile planning/acquisition, and bounded SSURGO survey-area package discovery/acquisition; all remain inactive validation-only paths. SSURGO staging, raster mosaicking, and arbitrary-AOI production coverage remain future work.

The 2026-09-25 live generic-AOI smoke passed for both paths using a dedicated Washington, DC-area AOI. The NLCD path required and now records a bounded padded request for very small AOIs; the 3DEP path selected and validated one official native tile. Measured IDs, checksums, sizes, and limitations are recorded in `PROJECT_STATE.md` and the external manifest; no active source version was created.

**Status:** Implemented. Generic projects accept valid nonempty WGS84 Polygon/MultiPolygon AOIs. Northern Colorado containment is available only through the explicit `northern_colorado_regression` policy. County IDs, boundary paths, SSURGO package expectations, raster expectations, and fixture metadata are centralized in `regression_fixtures.py` and remain regression configuration.

**Limit:** This does not make NLCD, SSURGO, PAD-US, or FEMA generic production acquisition paths. Source-specific regional commands remain fixture-scoped, and larger-AOI tiling remains future work.

## Milestone 2B.17 — Generic multi-source AOI ingestion orchestration

**Status:** Implemented. The `ingest-aoi` command creates a durable parent plan/run around the existing generic NLCD, 3DEP, and SSURGO adapters. It supports deterministic preflight planning, independent bounded source execution, explicit failures/incomplete outcomes, dry runs, and idempotent retries of only failed/incomplete source attempts.

**Remaining boundary:** No source promotion, FEMA/PAD-US acquisition, new tiling, screening change, UI/API, or production readiness is included. The next slice should be selected from the AOI-agnostic ETL backlog only after reviewing parent-run behavior against live generic acquisition and the existing inactive-candidate rules.

## Milestone 2B.18 — AOI-scoped generic raster candidate promotion

**Status:** Implemented. Generic Annual NLCD and 3DEP candidates use the
existing SQLite catalog and can activate only for the exact project/AOI
revision that acquired them. Promotion is checksum- and geometry-hash-
protected, validates complete AOI coverage and native raster metadata, writes
an auditable decision, and preserves the previous AOI pointer on failure.

**Remaining boundary:** SSURGO, PAD-US, and FEMA remain unpromoted; source
maturity is unchanged. The next work should address the hosted/production
repository boundary or another explicitly selected AOI-agnostic ETL slice,
not infer regional production readiness from these local pointers.

## Milestone 2B.19 — Snapshot-pinned active NLCD/3DEP screening

**Status:** Implemented. `screen-active` consumes only exact AOI-scoped active
Annual NLCD and 3DEP pointers through immutable job snapshots, reuses the
existing raster processors, and preserves independent metrics and complete
provenance in all exports.

**Remaining boundary:** Fixture-only paths remain unchanged. SSURGO, PAD-US,
and FEMA are not consumed or promoted by this slice, and source maturity and
regional production readiness remain unresolved.

## Milestone 2B.20 — Read-only AOI operational run report

**Status:** Implemented. `report-aoi-run` projects the existing catalog,
deterministic acquisition plans, and file-backed screening records for one
immutable project/AOI revision into JSON or a concise terminal summary.

**Remaining boundary:** The report is evidence-only. It does not acquire,
promote, screen, alter source maturity, or replace a future API/operations
surface.

## Milestone 2B.21 — Static read-only operations console

**Status:** Implemented. A dependency-free static console under `frontend/`
consumes the deterministic `report-aoi-run` JSON read model and includes a
checked-in recorded Washington, DC demonstration report. It shows AOI
identity, deterministic plans, source lifecycle, attempts/retries, artifacts,
checksums, validation, candidates, promotions, active versions, immutable
snapshots, independent metrics, and explicit warning/incomplete/unknown states.

**Explicit limits:** The console is not a live dashboard, API, map, worker, or
provider client. It does not require PostGIS or raw artifacts, does not alter
the Python CLI/catalog/source adapters, and does not produce rankings,
composite scores, safety conclusions, or regulatory determinations. Future
live wiring remains a separate product/architecture decision.

## Milestone 2B.22 — Primary map-centric screening workspace

**Status:** Implemented. The static frontend primary route is now a
full-viewport environmental screening workspace: the recorded Leaflet AOI map
is the dominant surface, a persistent control shows which spatial layers are
actually rendered or metrics-only/unavailable, and a compact sidebar presents
independent NLCD, 3DEP, SSURGO, PAD-US, and FEMA states. Secondary tabs expose
reports/exports, data-source availability, and technical provenance; the
operations console remains at `?view=operations`.

**Explicit limits:** This is still a read-only projection of the Washington,
DC recorded report. It adds no source overlays, provider access, screening
algorithm, API, or live processing. The map renders only the recorded AOI
geometry, NLCD/3DEP remain metrics-only, and all source limitations and
unknown states remain explicit.

## Milestone 2B.23 — Primary screening workspace usability pass

**Status:** Implemented. The primary workspace now uses a shorter shell/header,
compact source rows with inline observed metrics and collapsed details, a
collapsible layer control with an AOI visibility toggle, and a compact
interpretation-limits disclosure. Geometry hashes, source IDs, checksums, and
long technical explanations are kept out of the primary view and remain
available through the Data Sources, Reports, Activity, and operations views.

**Explicit limits:** The recorded AOI map and all source states/metrics are
unchanged. At this milestone only the AOI boundary was rendered; later
Milestone 2B.24 and 2B.25 add explicitly documented NLCD and 3DEP display
derivatives. SSURGO, PAD-US, and FEMA retain their
incomplete, conditional, unknown, or unavailable semantics. Mobile uses the
existing scrollable workspace tabs and separate map/summary regions; this is
not a new live application workflow.

## Milestone 2B.24 — Browser-renderable Annual NLCD preview

**Status:** Implemented for the recorded Washington, DC demonstration. A
derived RGBA PNG is generated from the retained validated Annual NLCD 2025
GeoTIFF, masked to the exact immutable AOI. A checked-in metadata document
records the source version, snapshot, checksum, raster grid/bounds, AOI hash,
observed class values, display transformation, and preview checksum.

The primary Leaflet map loads the preview as an optional image overlay with
transparent nodata/outside-AOI pixels, a documented categorical legend,
adjustable opacity, a toggle, AOI boundary-on-top ordering, and an explicit
unavailable state if metadata or the asset cannot be loaded. The PNG is a
display derivative only; the source raster and screening metrics remain
authoritative. No provider access, redownload, resampling, composite score, or
3DEP/SSURGO/PAD-US/FEMA behavior changed.

## Milestone 2B.25 — Browser-renderable 3DEP terrain preview

**Status:** Implemented for the recorded Washington, DC demonstration. A
4,802-byte RGBA PNG is generated from the retained validated 3DEP GeoTIFF,
windowed around the exact immutable AOI at native source-cell spacing and
masked so outside-AOI and nodata cells are transparent. The checked-in metadata
records the source tile/release URL, source version/snapshot, 500,034,664-byte
source checksum, EPSG:4269 transform/bounds/nodata, AOI revision/hash, preview
window bounds, and hillshade transformation.

The primary Leaflet map presents the 3DEP derivative under a compact
“Screening layers” control with an opacity slider, toggle, muted relative-
hillshade legend, AOI boundary-on-top ordering, and explicit metadata/asset
failure handling. It is disabled by default so the NLCD layer remains readable.
The retained raster does not declare vertical units or datum in its raster
metadata, so the derivative displays relative illumination only and does not
show or convert elevation values. Source metrics and all other source behavior
remain unchanged; no source promotion, composite score, or suitability
interpretation was added.

## Milestone 1 — Geography and source feasibility

**Priority:** P0 — prerequisite

**Status:** The England recommendation and NWI MVP source are superseded. Owner selected Northern Colorado (Boulder, Larimer, Weld; approx. 7,391 sq mi) and the five-source direction: FEMA NFHL, PAD-US 4.1, Annual NLCD Collection 1.2 (2025), 3DEP 1/3 arc-second, and SSURGO hydric-soil information. Exact TIGER/Line 2025 county geometries pass validation and retain all three union components. NLCD, one 3DEP tile, and SSURGO SDA samples passed representative checks and their initial small-window adapters have passed live smoke tests. The owner-approved PAD-US repair policy has been applied to a five-feature sample: two unchanged features accepted, three repaired candidates quarantined. Complete Colorado package access is blocked by official ScienceBase HTTP 403 responses; no regional QA or gap estimate exists. FEMA official service/download access remains independently blocked. Milestone 1 final source approval remains open. Milestone 2A was explicitly authorized; Milestone 2B has a local prototype but makes no full source-coverage claims.

**Objective:** Complete artifact-level validation of the selected geography and sources for final source approval and implementation readiness. Milestone 2A's initial contract was explicitly authorized before this gate closed.

**Major deliverables:**

- exact TIGER/Line 2025 county geometry acquired; preserve archive/checksums outside Git and retain all multipart/detached components (validated; no narrowing);
- official NFHL metadata and effective-feature samples for the three counties, preserving a distinct pending status;
- source-specific representative artifacts and coverage/scale evidence for PAD-US 4.1, Annual NLCD Collection 1.2 (2025), 3DEP 1/3 arc-second, and SSURGO; identify all 19 SDA survey areas and confirm a repeatable regional extraction/volume approach;
- acquire the official complete Colorado PAD-US 4.1 state package (or smallest complete official regional package), identify every feature intersecting the approved county union, then apply the already approved repair/quarantine policy and quantify coverage effects; current blocker is HTTP 403 on ScienceBase item/file/object routes;
- verify source terms, formats, CRS, geometry/raster properties, key fields/domains, extents, coverage and measured/estimated scale and volume;
- source-specific ingestion/QA design, including FEMA effective/pending and unknown coverage, regional raster windows, and SSURGO component hydric-rating lineage/interpretation;
- retain source-specific public-use/redistribution evidence and release/effective-date provenance in project documentation.

**Dependencies:** Public-source network access for the official PAD-US state package and FEMA NFHL, plus complete regional artifacts for source-specific checks. PAD-US repair policy is already owner-approved. The geography gate is complete. FEMA NFHL access is independently blocked; continue no source substitution and do not narrow the approved extent.

**Acceptance criteria:** County identity/vintage and union geometry validate; all five exact products have suitable use/redistribution terms and repeatable access; representative artifacts pass source-specific integrity, schema/CRS, coverage and scale checks; PAD-US promotion behavior is explicitly approved; regional raster and soil processing/volume are bounded; FEMA effective, pending, mapped, and unknown coverage semantics are empirically validated; no owner-level source or geography decision remains. NWI is outside the MVP and must not be silently reintroduced. These are still required for final Milestone 1/source approval. The owner explicitly authorized controlled progression into Milestones 2A and 2B before that gate; the implementation must continue to disclose source maturity and cannot claim complete coverage. Do not create a remote or push without owner authorization.

## Milestone 2 — Screening workflow and product contract

**Priority:** P0 — prerequisite

**Objective:** Define the analyst workflow, result structure, source-specific metrics, and preliminary-screening limitations.

**Status:** Milestone 2A contract definition, controlled Milestones 2B.1–2B.6 slices, bounded snapshot-pinned NLCD and 3DEP fixture screening, and the unified fixture orchestration are complete. Final Milestone 1 source approval remains open for complete regional PAD-US coverage/repair statistics and FEMA technical access/effective-pending validation. The implementation is local and incomplete; it does not enable production/region-wide conclusions.

**Major deliverables:**

- project/AOI lifecycle (defined in `SCREENING_CONTRACT.md`: map-drawn Polygon/MultiPolygon, GeoJSON API geometry, immutable AOI revisions, generic validation by default, and optional named containment policies including the Northern Colorado regression policy);
- screening job lifecycle and result semantics (defined; a file-backed synchronous job runner implements an initial subset; external queue/worker remains future work);
- per-source metric definitions and validation/coverage/observation-state semantics (defined; initial NLCD, 3DEP, SSURGO and boundary metrics implemented; PAD-US/FEMA remain non-operational);
- result provenance and export contract (defined; initial JSON, CSV and GeoJSON exports implemented; GIS findings remain limited to SSURGO map units);
- transparent preliminary-only/non-regulatory wording (defined);
- primary AOI interaction selected for this contract: map drawing, with GeoJSON geometry at the API boundary; no end-user file-upload workflow is included in 2A.

**Dependencies:** Milestone 2A was explicitly authorized before full Milestone 1 source approval. Full source approval is still required before production implementation can claim complete source coverage or use source maturity labels beyond their documented scope.

The contract is documented in `docs/SCREENING_CONTRACT.md`. It covers project/AOI behavior; transparent per-source metrics for mapped FEMA zones, SSURGO hydric-soil indicators, terrain, land cover and protected areas; source versions/effective dates and lineage; result structure and exports; asynchronous job states; missing/unknown coverage; and preliminary-screening limitations. It prohibits a composite score, invented regulatory thresholds, a wetland determination, or an implication of jurisdictional-wetland presence/absence.

**2A acceptance criteria:** Met by the approved design contract. It does not establish final source approval.

## Milestone 2B.1 — First local ETL vertical slice

**Status:** Implemented and locally smoke-tested on 2026-09-22. Source maturity remains bounded by its prior representative validation scope.

**Verified scope:** Official 2025 Census boundary acquisition/parsing; official 2025 NLCD WCS window; 3DEP ImageServer AOI window; NRCS SDA clipped SSURGO mapunit/component query; immutable project AOI revisions; local job/retry records; external content-addressed raw responses/checksum event records; transparent per-source metrics and states; JSON/CSV/GeoJSON exports; deterministic tests.

**Explicitly not delivered by this first ETL slice:** production environmental PostGIS source tables, true asynchronous queue, full-region/window tiling, source refresh scheduling, PAD-US/FEMA operational adapters, UI/API, deployment, production guarantees, and final Milestone 1 source approval. The local AOI PostGIS schema boundary was added separately in Milestone 2B.4; the local metadata catalog and candidate promotion were added in 2B.2 and immutable job source snapshots in 2B.3. The representative SSURGO PostGIS fixture is tracked separately in Milestone 2B.5.

**Acceptance evidence:** `pytest`, Ruff, mypy and CLI smoke pass; a live 0.00948 km² AOI job produced a completed result with official small-window NLCD/3DEP/SSURGO responses, correct Census union, and explicit PAD-US/FEMA unresolved states. See `PROJECT_STATE.md` and the external data directory; raw data is not committed.

## Milestone 2B.2 — Source-version records and safe candidate promotion

**Status:** Implemented using a backend-neutral repository protocol and local SQLite metadata store under the external data directory. Records include ingestion/retry runs, acquisition attempts, checksum/release source versions, candidate validation/coverage/errors, promotion decisions, and active-version pointers. Promotion rechecks artifact integrity and requires successful validation and complete coverage; failed, partial, quarantined, and blocked outcomes remain queryable. SQLite is a local control-metadata implementation, not a replacement for PostGIS.

**Verified scope:** CLI ingestion for Census, NLCD, 3DEP, and SSURGO; explicit non-acquired PAD-US quarantine and FEMA blocked records; list/inspect/retry/promote/active-version commands. Screening-job binding to the active catalog pointer was deliberately delivered in Milestone 2B.3.

**Acceptance evidence:** 32 deterministic tests, Ruff, mypy, CLI help, and no-network FEMA/PAD-US catalog status smokes passed. No provider data were acquired during this slice. See `PROJECT_STATE.md`.

## Milestone 2B.3 — Immutable screening-job source snapshots

**Status:** Implemented in the local SQLite catalog. Job creation resolves every requested source against the active pointer and stores immutable AOI/source snapshot rows before processing. Screening execution and retry use those exact rows; missing active versions, blocked/quarantined sources, unpromoted candidates, and disappeared artifacts remain explicit states. New job creation is the explicit fresh-snapshot operation.

**Verified scope:** Source snapshot IDs and source-version lineage in JSON, CSV, and GeoJSON; PAD-US/FEMA controlled states; active-version isolation after later promotion; retry snapshot reuse; artifact checksum/availability handling. No source maturity was changed and no provider data was acquired in this slice.

**Acceptance evidence:** 36 deterministic tests, Ruff, mypy, CLI help, documentation link checks, and `git diff --check` passed.

## Milestone 2B.4 — Local PostGIS AOI repository boundary

**Status:** Implemented as an optional local setup and repository boundary. SQLite remains the control plane. A pinned PostGIS Compose service, external data volume, first migration, canonical AOI/component schema, explicit cross-database source snapshot/version identifiers, and a validated Census three-county fixture loader are present.

**Verified scope:** Pure-Python boundary/fixture validation, migration and Compose configuration checks, and real PostGIS execution against `postgis/postgis:16-3.4`. The validated Census artifact loaded successfully with all three county components and a valid three-component union; direct queries verified EPSG:4269 source geometry, EPSG:4326 canonical geometry, EPSG:5070 analysis-area semantics, explicit source snapshot/version linkage, idempotent reload, and transaction rollback without partial records. The opt-in integration test passed. No environmental source tables or scoring were added.

**Runtime evidence:** Docker Desktop WSL integration and the optional psycopg dependency were available on 2026-09-23. The real migration, boundary load, direct PostGIS queries, idempotent reload, failed-transaction rollback, and integration test passed. The database volume and validated Census artifact remain outside Git; this does not establish a deployed database or environmental source-table implementation.

## Milestone 2B.5 — Representative SSURGO spatial fixture

**Status:** Implemented and runtime-verified on 2026-09-23. The migration `002_ssurgo_mapunits.sql` adds SSURGO batch, staging, and fixture-only canonical map-unit/component tables without duplicating the SQLite control-plane catalog. The loader parses the existing 1,893-byte official SDA response, retains raw artifacts outside Git, preserves provider attributes and component hydric fields, and records source snapshot/version plus optional ingestion/candidate linkage.

**Verified scope:** A real PostGIS run staged 3 map units and 6 components, validated required identifiers/joins, valid MultiPolygon geometry, EPSG:4326 source/canonical metadata and EPSG:5070 analysis areas, then atomically promoted the candidate as `fixture_only` with `coverage_status=partial` and `observation_status=data_observed`. Repeated loading was idempotent; a separate source version remained separate; failed validation retained the candidate without canonical rows. Live integration tests, full no-database tests, Ruff, mypy, CLI, and diff checks passed.

**Explicit limits:** This is a representative fixture, not full three-county SSURGO coverage, a regional package, an active source version, or production readiness. Hydric fields remain soil information only and are not a wetlands inventory or regulatory determination. No PAD-US/FEMA status changed.

## Milestone 2B.6 — Fixture-only SSURGO screening consumption

**Status:** Implemented and runtime-verified on 2026-09-24. Screening dispatch accepts an optional PostGIS repository and resolves the immutable SQLite SSURGO job snapshot before querying only the exact `source_snapshot_id`/`source_version_id` pair. The query intersects canonical fixture geometries with the immutable job AOI, joins map units to components, calculates covered/uncovered area, map-unit/component counts, and hydric attribute records, and emits `source_status=fixture_only` plus explicit `observed`, `no_indicator_observed`, or `uncovered` states.

**Verified scope:** The explicit `screen-ssurgo-fixture` command creates a single-source `ssurgo_fixture_only` job. Live tests verified covered and uncovered AOIs, missing snapshots, source-version isolation after a newer promotion, component joins, hydric-soil labeling, and JSON/CSV/GeoJSON provenance. PAD-US and FEMA remain unchanged.

**Explicit limits:** The path consumes only fixture-only canonical rows and does not establish regional SSURGO coverage, production readiness, or an active regional source. Hydric-soil information is not a wetlands inventory or regulatory determination. No composite score or regulatory conclusion is produced.

## Milestone 2B.7 — Snapshot-pinned Annual NLCD fixture screening

**Status:** Implemented as an explicit `nlcd_fixture_only` local path. It reads only the exact external GeoTIFF identified by the immutable job snapshot, reports footprint coverage, valid/nodata pixels, class counts/percentages, and raster metadata, and keeps pixels outside PostGIS. It does not claim full regional NLCD coverage or production readiness.

**Verified scope:** Deterministic and validated-external-raster tests cover source-version isolation, valid/nodata accounting, covered/uncovered AOIs, class labels, CRS/transform metadata, missing/unavailable artifacts, repeated deterministic metrics, and JSON/CSV provenance. GeoJSON carries source state/provenance but no fabricated pixel features. Census, SSURGO, PAD-US, and FEMA behavior remains unchanged.

**Explicit limits:** The raster is a representative fixture/smoke artifact. Full regional windowing/mosaic strategy and production source readiness remain unresolved. No composite interpretation or regulatory land-cover conclusion is produced.

## Milestone 2B.8 — Snapshot-pinned 3DEP fixture screening

**Status:** Implemented as an explicit `3dep_fixture_only` local path. It reads only the exact external DEM identified by the immutable job snapshot, reports footprint coverage, valid/nodata cells, raw elevation statistics and raster metadata, and keeps pixels outside PostGIS. It does not claim full regional 3DEP coverage or production readiness.

**Verified scope:** Deterministic and validated-external-fixture tests cover source-version isolation, AOI intersection, valid/nodata accounting, reproducible min/max/mean/percentile metrics, CRS/resolution/transform/nodata and vertical metadata behavior, missing/unavailable artifacts, JSON/CSV provenance, repeated screening, and one meaningful raster-footprint GeoJSON feature. Census, NLCD, SSURGO, PAD-US, and FEMA behavior remains unchanged.

**Explicit limits:** The retained service-window fixture does not declare vertical units or datum, so values are reported without conversion and those fields remain null with a warning. No slope/aspect, flood, landslide, suitability, composite, or regulatory interpretation is produced. Full regional tile/window processing remains unresolved.

## Milestone 2B.9 — Unified bounded fixture screening

**Status:** Implemented as the explicit `screen-fixtures` command. It snapshots the validated Census AOI revision with SSURGO, Annual NLCD, 3DEP, PAD-US, and FEMA source rows; runs only the existing SSURGO/NLCD/3DEP fixture processors; and preserves PAD-US quarantined and FEMA blocked outcomes in a source-status matrix.

**Verified scope:** Unified JSON with independent per-source results, exact snapshot/version IDs, metrics, provenance/checksums, warnings, `job_outcome`, and partial/fixture-only status; one-row-per-source CSV with repeated matrix metadata; GeoJSON with only the AOI and meaningful SSURGO/3DEP geometries. A source failure preserves other results. Retry reuses the immutable snapshot and a new job observes newly promoted versions.

**Explicit limits:** This is orchestration, not final source approval or regional screening. PAD-US and FEMA are not processed. SSURGO remains fixture-only and requires PostGIS for a successful source result; NLCD/3DEP remain representative fixtures. No composite score, suitability, wetland, flood, or regulatory conclusion is produced.

## Milestone 2B.13 — Automated regional Annual NLCD acquisition

**Status:** Implemented and live-validated on 2026-09-25. The new `ingest-nlcd-regional` command loads the exact approved 2025 Boulder/Larimer/Weld boundary, requests only the 2025 Annual NLCD Collection 1.2 window from the official USGS/MRLC WCS, and records the result in the existing SQLite acquisition/run/candidate/source-version/provenance model. Raw raster bytes remain outside Git.

**Verified scope:** The inactive candidate acquired 47,189,394 bytes (SHA-256 `3abd04eb346c45f0a6bb1570ba55bb4f3b011eae640bc11579340049a9336f90`) as an 8,064 × 5,664 `uint8` EPSG:5070 GeoTIFF with nodata 250, provider-snapped approximately 30 m transform, 45,674,496 total cells, 21,285,520 valid AOI cells, zero nodata AOI cells, 100% AOI footprint coverage, and observed values within the official class domain. Request parameters, final URL, HTTP metadata, retrieval time, checksum, dimensions, transform, and metrics are in the external manifest. Two earlier defensive validation failures remain queryable as failed inactive candidates and did not alter the active pointer.

**Explicit limits:** The rectangular response includes 24,388,976 outside-AOI pixels; those are not screening observations. The source maturity remains representative-sample `validated`, the regional candidate remains `not_promoted`, and no active Annual NLCD version was created. No PostGIS pixel table, refresh scheduler, national archive, composite score, regulatory interpretation, or final Milestone 1 source approval is added.

## Milestone 2B.14 — AOI-agnostic Annual NLCD acquisition

**Status:** Implemented with deterministic local tests. The `ingest-nlcd` command consumes a persisted immutable AOI revision, builds the official WCS request from that geometry, and records AOI hashes, request parameters, native raster metadata, checksum, and inactive candidate provenance. `ingest-nlcd-regional` remains the Northern Colorado regression/fixture alias.

**Verified scope:** Generic WGS84 Polygon/MultiPolygon AOIs outside Northern Colorado are accepted. The native EPSG:5070/30 m grid, nodata value 250, official class domain, AOI footprint accounting, outside-AOI pixels, and nodata/unknown semantics are validated. Oversized requests fail before HTTP with an explicit bounded-request error; no clipping or tiling was added.

**Explicit limits:** Tests use a mocked provider response; no new generic-AOI live acquisition was performed. Candidates remain inactive and NLCD source maturity is unchanged. Generic SSURGO acquisition, source tiling, and arbitrary-AOI production coverage remain future work.

## Milestone 2B.15 — AOI-agnostic 3DEP tile planning and acquisition

**Status:** Implemented with deterministic mocked/local validation. `ingest-3dep` consumes a persisted immutable AOI revision, queries the official TNM Access inventory, writes a deterministic plan before downloads, and records each selected native tile as an inactive candidate through the existing SQLite acquisition/run/version/provenance model.

**Verified scope:** One product per intersecting tile is selected deterministically from official inventory metadata. Per-tile identifiers, URLs, release dates, request parameters, response headers, provider-reported and measured sizes, retrieval timestamps, checksums, AOI revision/geometry hash, external paths, and raster validation are retained. Validation covers readable single-band GeoTIFFs, EPSG:4269, 1/3-arc-second resolution, dimensions, supported datatype, regular transform, nodata `-999999`, footprint coverage, and raw elevation metadata. Nodata/uncovered areas remain unknown, and failed downloads remain explicit candidates/manifest failures. Tests cover discovery, deterministic planning, bounded limits, plan-before-download ordering, checksum/provenance, raster validation, and failed acquisition.

**Explicit limits:** No generic-AOI live tile download was performed. The path does not clip, resample, mosaic, substitute, promote, derive slope/aspect, or claim full regional coverage or production readiness. `screen-3dep-fixture` and Northern Colorado regression behavior remain unchanged. Generic SSURGO staging, raster mosaicking, and full source approval remain future work.

## Milestone 2B.16 — AOI-agnostic SSURGO package discovery and acquisition

**Status:** Implemented and live-smoke-verified on 2026-09-25. `ingest-ssurgo` queries the official NRCS SDA intersection function and `sacatalog` for the persisted AOI, resolves official WSS ZIP URLs from current release metadata, persists a deterministic plan before package-body requests, and records inactive package candidates through the existing SQLite acquisition/run/version model.

**Verified scope:** A small Washington, DC generic AOI discovered DC001 outside the Northern Colorado fixture. The official 12,965,824-byte package passed streamed HTTP metadata, ZIP CRC, and spatial/tabular structure validation; SHA-256 is `e5aa8a7b9b08aadedc0eec206fc06323ff37515e00b5e6fc756f2e6c7bba0989`. The smoke plan, batch, manifest, raw package, candidate, and checksums are external under `/home/aarondroper/projects/environmental-screening-platform-data/live-generic-ssurgo-smoke-20260925/`.

**Explicit limits:** Count and aggregate-size bounds reject before package-body acquisition when they cannot be enforced. Failed downloads and ZIP/package mismatches remain queryable candidates/attempts. No staging, repair, clipping, coverage analysis, promotion, generic SSURGO screening, or source-maturity change is included. `ingest-ssurgo-regional` remains the Northern Colorado regression alias.

## Completed validation work — regional SSURGO package acquisition

**Status:** Completed on 2026-09-24. The exact approved 2025 Census union returned 19 official NRCS SSURGO survey areas. Current `sacatalog` release metadata and grouped map-unit counts were confirmed, and all 19 official WSS survey-area ZIP bodies returned HTTP 200 with provider-reported compressed sizes totaling 394,959,419 bytes (376.663 MiB); measured local sizes matched, and all archives passed CRC/spatial/tabular container validation. The read-only parser then found 13 package passes and 6 package-level failures: 10 original invalid polygons in four packages and two survey-name variations. All 19 packages intersected the approved AOI. The sizing record, raw packages, and QA reports are outside Git under `/home/aarondroper/projects/environmental-screening-platform-data/ssurgo/`; candidates remain inactive/incomplete.

**Explicit limits:** Package QA preserves original failures and does not repair, drop, clip, or promote records. It establishes package-level schema/CRS/relationship checks and AOI intersection, not county-clipped canonical volume, gap-free regional coverage, or production readiness. SSURGO remains representative/fixture-validated and not production-ready. Hydric-soil information remains distinct from wetland mapping or regulatory determination.

## Current SSURGO follow-on boundary

The read-only parsing/QA, discrepancy-audit, owner-approved derived staging, and inactive candidate materialization slices are complete for the retained 19 packages. The two Wyoming naming differences are classified as harmless variations: package metadata, SDA/official lookup, package URLs, release metadata, checksums, and manifest identity agree; only the sizing record includes the word “Area.” The staging run retained original geometries and attributes, accepted all 10 audited repairs, quarantined none, and the derived aggregate is recorded as an `incomplete`/`conditionally_validated`/`partial` candidate. Any future canonical active-version promotion requires a separate source-approval decision and must not change the existing fixture-only screening path. Do not consume PAD-US or FEMA operationally; preserve provider-reported versus measured sizes.

## Milestone 2B.10 — Owner-approved derived regional SSURGO staging

**Status:** Implemented and runtime-verified on 2026-09-24. Migration `003_ssurgo_regional_staging.sql` adds package, map-unit, component, and feature staging records with original/derived geometry, audited QA diagnostics, source attributes, and explicit source snapshot/version, candidate, ingestion-run, URL, release, checksum, and artifact-path lineage.

**Verified scope:** The `stage-ssurgo-regional` CLI parsed the 19 existing ZIPs without redownloading, retained valid polygons unchanged, applied `make_valid` only to the 10 audited invalid polygons, accepted all 10 under the 0.1% EPSG:5070 area/topology/joinability policy, and loaded 123,196 features, 1,878 map units, and 7,404 components into PostGIS staging. Direct queries verified valid derived geometries, EPSG:4326 metadata, zero orphan components, idempotent package reload, and `staging_only` status. A failed transaction left no partial package records. The 19 SQLite candidates remain `incomplete`/`not_promoted`; no active SSURGO version was created.

**Explicit limits:** This is derived staging, not canonical production promotion, final source approval, or a wetlands determination. Raw ZIPs and original geometries remain unchanged. Hydric fields remain soil information only.

## Milestone 2B.11 — Inactive regional SSURGO candidate materialization

**Status:** Implemented and runtime-verified on 2026-09-24. The `materialize-ssurgo-regional-candidate` command rechecks the existing staging aggregate, all package reports and raw checksums, package candidates/runs, discrepancy audit, and package QA before creating one derived source-version/candidate record in SQLite.

**Verified scope:** Candidate `9d77a86a-bdc7-4684-b977-1081f8ed484c` and source version `ssurgo:e6e101e90c00745d452482c2e9a4bbedab2a46813d830141e76852ead9b5f3bf` are linked to the synthetic regional snapshot, 19 package candidates/runs, 19 raw checksums, staging batch/report, repair audit, and QA report. The record preserves 19/19 acquired/structurally valid packages, 123,196 features, 1,878 map units, 7,404 components, 10 accepted repairs, zero quarantines, valid derived geometry/CRS checks, zero orphan joins, and WY621/WY721 naming notes.

**Safety state:** The candidate is `incomplete`, `conditionally_validated`, `partial`, and `not_promoted`; no active SSURGO pointer was created or updated. Repeat materialization is idempotent and aggregate checksum changes fail before a new candidate is created. This does not establish complete regional coverage, production readiness, or permission to consume the staged dataset in screening.

## Milestone 2B.12 — Regional SSURGO coverage and seam analysis

**Status:** Implemented and runtime-verified on 2026-09-24. The read-only `analyze-ssurgo-regional-coverage` path measured the exact three-county AOI against all 19 existing staging batches, wrote checksummed aggregate/per-package/gap/overlap/seam reports outside Git, and persisted the result against inactive candidate `9d77a86a-bdc7-4684-b977-1081f8ed484c`.

**Result:** Coverage is 99.9999955989% by EPSG:5070 area at report precision, with 842.5 m² uncovered, 43 diagnostic gap components, 9 cross-package overlap pairs totaling 160.7 m² pairwise overlap, and all 19 survey areas contributing. Thirteen gap components are AOI-boundary-adjacent within 1 m; 30 small interior residuals remain unknown and require no silent filling or interpretation. Outside-AOI feature area is reported separately from AOI coverage.

**Safety state:** The candidate remains `incomplete` / `conditionally_validated` / `partial` / `incomplete_source` / `not_promoted`; no active source version was created, and staged/raw data were unchanged. Final regional source approval and any canonical promotion remain separate owner-authorized work.

**Next frontier:** Review the measured coverage evidence and decide whether the residual gaps/overlaps are acceptable for a later canonical promotion design; do not consume this inactive candidate in the fixture-only screening path without a separate decision.

## Milestone 2B.13 — Regional SSURGO candidate disposition

**Status:** Implemented and runtime-verified on 2026-09-25. The explicit promotion attempt for candidate `9d77a86a-bdc7-4684-b977-1081f8ed484c` was rejected with an idempotent SQLite promotion decision.

**Reason:** 842.5 m² uncovered residual across 43 gap components, including 30 interior residuals; 160.7 m² of cross-package overlap. Residual areas remain unknown; no fill, repair, clipping, redownload, scope expansion, or promotion was performed.

**Safety state:** The candidate remains `incomplete` / `conditionally_validated` / `partial` / `incomplete_source` / `not_promoted`; all coverage metrics, diagnostic geometries, report checksums, package lineage, raw checksums, and provenance remain preserved. The active SSURGO pointer remains absent. FEMA, PAD-US, NLCD, 3DEP, and screening semantics are unchanged.

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

## Focused usability follow-up — compact screening workspace

**Status:** Completed 2026-09-26

The primary frontend now uses a compact one-row header, a roughly two-thirds
map / one-third summary desktop split, a collapsed layer control, compact
expandable source rows, and a map-first mobile layout. Primary navigation is
limited to Screening, Reports, and Data sources. The operations console remains
a separate technical route. No source semantics, screening behavior, or
browser-ready environmental overlays changed.

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
