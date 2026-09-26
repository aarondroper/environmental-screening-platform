# Architecture

## Status and evidence convention

This document separates the intended platform from the verified Milestone 2B local prototype. The implementation currently consists of a Python CLI, file-backed project/AOI/job records, four narrowly scoped source pathways, a fixture-only SSURGO PostGIS load, bounded SSURGO screening consumption, bounded snapshot-pinned NLCD/3DEP raster screening, and bounded multi-source fixture orchestration; it is not the intended hosted application. Statements below are labeled as intended, unresolved, or verified where relevant.

| Label | Meaning |
| --- | --- |
| **Verified** | Supported by inspected repository behavior, configuration, tests, or deployment evidence. |
| **Intended** | The agreed direction for implementation, not evidence that it exists. |
| **Unresolved** | Requires research, development judgment, or owner decision. |

## Architectural objective

The platform should be a coherent small application whose sophistication comes from reliable geospatial data operations rather than service proliferation. It should acquire external data, preserve raw inputs, validate and normalize them, promote safe versions into PostGIS, run transparent screenings asynchronously, and expose the results through an API and MapLibre web application.

## Verified current boundary

Verified implementation is the local workflow in `src/environmental_screening_platform/`: Python CLI, official Census boundary acquisition/parser, NLCD WCS window and exact-snapshot raster summary, 3DEP ImageServer window and exact-snapshot elevation summary, bounded TNM Access 3DEP tile planning/acquisition, SSURGO SDA query, fixture-only PostGIS map-unit/component load, snapshot-pinned fixture-only SSURGO screening query, JSON project/AOI/job state, provenance/raw-byte storage, metrics, exports, an optional PostGIS repository boundary, and a bundled Leaflet static frontend with a primary recorded screening report and secondary operations view. The development-only `screening serve` command additionally provides a same-origin standard-library bridge for generic-AOI Annual NLCD acquisition, AOI-scoped promotion, immutable snapshot binding, and screening. The primary map uses an attributed OpenStreetMap tile layer and recorded or locally loaded AOI geometry. It stores operational data only under a caller-supplied external data directory. There is no deployed database, hosted API, queue/worker service, or production/active regional environmental canonical data promotion. The architecture diagram remains the intended target, not an implementation diagram.

### Verified local execution boundary (Milestone 2B)

- `screening project-create` validates a nonempty, valid WGS84 Polygon/MultiPolygon AOI and records immutable project/AOI-revision JSON outside Git. Generic AOIs have no platform-wide containment boundary. The explicit `--aoi-policy northern_colorado_regression` option obtains/caches the exact 2025 Census county boundary and validates containment against the full union for regression/demo runs.
- `screening screen` persists a job, runs the local worker synchronously, and records `queued → processing → completed/failed`; independent source failures remain source-level outcomes. Failed jobs may be retried against the same immutable AOI; completed results are immutable.
- `screening screen-ssurgo-fixture` creates a single-source job in explicit `ssurgo_fixture_only` mode, resolves the immutable SQLite SSURGO snapshot, and queries only the matching PostGIS snapshot/version pair. It never selects latest data or a regional source version. `screening screen --database-url ...` can use the same bounded SSURGO path when the requested job contains an eligible snapshot.
- `screening screen-nlcd-fixture` creates a single-source job in explicit `nlcd_fixture_only` mode and opens only the exact external NLCD GeoTIFF named by the immutable SQLite snapshot. It records raster footprint coverage, valid/nodata pixels, class counts/percentages, CRS, transform, resolution, dimensions, nodata, and source year. Raster pixels remain external artifacts; no NLCD pixel table is added to PostGIS.
- `screening screen-3dep-fixture` creates a single-source job in explicit `3dep_fixture_only` mode and opens only the exact external 3DEP DEM named by the immutable SQLite snapshot. It records footprint coverage, valid/nodata cells, raw elevation min/max/mean/percentiles, CRS, resolution, dimensions, transform, nodata, vertical metadata where present, and source-version provenance. It may export one source-footprint feature; it does not add pixels to PostGIS or calculate slope.
- `screening screen-fixtures` creates a bounded five-source job against the validated Census AOI revision. It runs the existing SSURGO, NLCD, and 3DEP fixture paths against exact snapshot rows, carries PAD-US quarantined and FEMA blocked outcomes without processing them, and emits an overall partial/fixture-only outcome plus a source-status matrix. It does not create a composite result or cross-source geometry.
- Raw provider responses are content-addressed by SHA-256 and stored outside the repository. Each acquisition event records actual response URL/media type, exact request parameters, retrieval time, size, checksum, release label, and terms URL. HTTPS and same-host redirects are required; response size and request dimensions are bounded. The regional SSURGO package workflow additionally records provider-reported and measured sizes, selected HTTP headers, ZIP CRC/package-structure validation, and one inactive candidate/source-version/run per survey area. Its read-only regional parser validates the observed Shapefile/pipe-table package format, CRS, original geometry validity, survey identity, `mukey`/`cokey` relationships, and hydric fields, writes external per-package/aggregate QA, and does not alter raw source records. The discrepancy-audit CLI derives in-memory `make_valid` diagnostics and cross-source identity classifications only. The separate `stage-ssurgo-regional` path writes only derived PostGIS staging records with original and derived geometries, audited repair diagnostics, source attributes, map-unit/component joins, and package/candidate/run/version lineage. It accepts only the approved repair checks, retains quarantines, is idempotent per source snapshot/version, and has no active-source promotion path. The generic `ingest-ssurgo` path discovers survey areas with official SDA `SDA_Get_Areasymbol_from_intersection_with_WktWgs84` plus `sacatalog`, derives official WSS URLs from release metadata, persists a deterministic plan before package bodies, preflights provider sizes, enforces count/aggregate-byte limits, and records each inactive candidate with AOI revision/geometry hash, HTTP metadata, checksum, and ZIP structure validation. It stops before staging, repair, clipping, coverage analysis, or promotion. The separate `ingest-nlcd-regional` path uses the official WCS regional window for the exact approved boundary, requests the 2025 time position in EPSG:5070 at nominal 30 m, validates the provider-snapped transform/resolution, class domain, nodata and AOI coverage, and records its inactive candidate/source-version/run/manifest lineage. The regional raster remains an external artifact; no pixel table or active-version pointer is created.
- Source adapters are project-owned. Current successful small-AOI pathways are TIGER/Line 2025, Annual NLCD 2025 WCS, USGS 3DEP ImageServer, and NRCS SDA SSURGO. Successful live smoke requests are evidence only for those small windows and do not expand the source validation scopes recorded in the contract.
- `regression_fixtures.py` is the single project-owned configuration for the Northern Colorado demonstration fixture. It contains the three county GEOIDs, fixture AOI identifier and vintage, boundary paths, the expected 19-package SSURGO sizing record, and validated NLCD/3DEP raster expectations. These values are not generic project defaults. Regional SSURGO remains explicitly fixture-scoped; generic NLCD acquisition, bounded 3DEP tile acquisition, and bounded SSURGO package discovery/acquisition are implemented as persisted-AOI requests, while SSURGO staging, raster mosaicking, and arbitrary-AOI production coverage remain future work.
- The explicit `ingest-nlcd` command is the first AOI-agnostic source acquisition slice. It loads the persisted immutable `AoiContext`, builds a bounded official WCS request from that geometry and the Annual NLCD release, preserves the native EPSG:5070/30 m grid, and records request, raster, checksum, and AOI geometry-hash provenance in the inactive candidate catalog. Very small AOIs use a bounded padded provider window because the WCS returned unstable sub-30 m transforms for the unpadded envelope; outside-AOI pixels remain masked and explicit. Oversized requests fail before acquisition because clipping and tiling are not implemented. `ingest-nlcd-regional` remains the Northern Colorado regression/fixture alias.
- The explicit `ingest-3dep` command loads the persisted immutable `AoiContext`, queries the official TNM Access inventory, writes a deterministic plan before any tile download, selects one dated 1/3-arc-second GeoTIFF product per intersecting tile, and records each tile as an independent inactive candidate. It validates the native EPSG:4269 geographic grid, 1/3-arc-second resolution, dimensions, datatype, nodata, transform, readability, footprint coverage, and raw elevation metadata without clipping, resampling, mosaicking, or activation. Excessive tile plans and incomplete inventory responses fail explicitly. `screen-3dep-fixture` and Northern Colorado aliases remain separate unchanged regression paths.
- PAD-US and FEMA are emitted as explicit not-acquired outcomes: PAD-US remains conditionally validated with regional coverage unknown and the prior sample quarantine counts shown; FEMA remains access-blocked with no effective/pending data. No fallback source is used.
- Results are JSON; CSV carries one row per source including state/provenance/metrics; GeoJSON carries the AOI plus valid SSURGO clipped map-unit features. Raster products remain summarized in analytical exports; the static demo additionally publishes a masked NLCD PNG as an explicitly labeled display derivative. GeoJSON does not imply that a missing source has no findings.
- SSURGO fixture results carry `source_status=fixture_only`, `screening_status` (`observed`, `no_indicator_observed`, or `uncovered`), source snapshot/version provenance, covered and uncovered AOI areas, map-unit/component counts, and the explicit hydric-soil limitation label. Component attributes are not spatially delineated within map units. Regional survey-area ZIP candidates are separate inactive validation records and are not consumed by this fixture screening path.
- NLCD fixture results carry `source_status=fixture_only`, `screening_status` (`observed`, `nodata`, or `uncovered`), exact source snapshot/version provenance, raster footprint and covered/uncovered AOI areas, valid/nodata pixel counts, class counts/percentages, and source grid metadata. JSON/CSV include the summary; GeoJSON contains no fabricated pixel features. The checked-in Washington, DC demo preview is generated from the exact validated EPSG:5070 raster, masks outside-AOI/nodata cells to transparent RGBA, and records its own display checksum and source lineage.
- 3DEP fixture results carry `source_status=fixture_only`, `screening_status` (`observed`, `nodata`, or `uncovered`), exact source snapshot/version provenance, raster footprint and covered/uncovered AOI areas, valid/nodata cell counts, raw elevation statistics, CRS/grid/nodata metadata, and vertical units/datum when declared. GeoJSON may contain one meaningful raster footprint and never pixel features.
- The unified fixture result preserves independent source results and adds `overall_status`, `product_status`, `availability_status`, `job_outcome`, and `source_status_matrix`. `job_status=completed` means the bounded orchestration wrote a result; `overall_status=partial` makes blocked, quarantined, incomplete, and unavailable evidence visible rather than treating it as absence.
- This is job-oriented, not genuinely asynchronous: the CLI command itself waits while the local worker runs. AOIs exceeding configured NLCD/3DEP request or tile-plan limits currently fail explicitly; multi-window tiling and raster mosaicking are future work.

## Intended system shape

```mermaid
flowchart LR
    S[External environmental sources] --> I[Ingestion adapters]
    I --> R[Raw object storage]
    I --> V[Staging and validation]
    V --> P[Versioned PostGIS canonical data]
    U[Analyst web app] --> A[FastAPI]
    A --> Q[Queue and worker]
    Q --> P
    A --> P
    A --> U
    O[Operations view] --> A
```

The diagram is an intended boundary model, not a verified deployment diagram.

## Technology direction

| Area | Intended direction | Status |
| --- | --- | --- |
| Backend language | Python package and CLI | Implemented prototype; production backend/API not implemented |
| API | FastAPI with typed schemas and OpenAPI | Strongly preferred; not implemented |
| Database | PostgreSQL + PostGIS | Local AOI and fixture-only SSURGO schema boundaries implemented; hosted database and active regional environmental schema not implemented |
| Migrations | Alembic / SQL migration boundary | Two local SQL migrations implemented for AOI and representative SSURGO fixture boundaries; Alembic history not implemented |
| Geospatial processing | Rasterio, NumPy, Shapely, PyProj, pyshp; SQL/PostGIS later | Initial local dependencies implemented; source-dependent expansion |
| Frontend | React + TypeScript | Strongly preferred; not implemented |
| Mapping | MapLibre | Strongly preferred; not implemented |
| Background processing | Lightweight queue and worker, likely Redis-backed | Unresolved implementation choice |
| Raw storage | S3-compatible object storage, likely MinIO locally and an affordable hosted equivalent | Provider unresolved |
| Local environment | Docker Compose | Strongly preferred; not implemented |
| CI/CD | GitHub Actions | Preferred; not implemented |

## Application components

### Frontend

The React/TypeScript application is intended to provide:

- project list and project creation;
- study-area drawing and visualization;
- screening submission and job-state display;
- result summary and per-dataset findings;
- MapLibre map with selectively visible constraint layers;
- CSV/spatial downloads;
- source and data-health operations view.

Authentication, navigation structure, and exact responsive behavior remain unresolved. Desktop/laptop is primary, with usable smaller-screen behavior expected but not full mobile parity.

### API

FastAPI is intended to be the application boundary for:

- projects and project areas;
- screening submission, status, and results;
- environmental dataset and version metadata;
- ingestion/status information;
- health and readiness checks;
- downloads or download metadata.

The API should use explicit request/response schemas, validation, stable error responses, and OpenAPI documentation. Exact route names and authentication behavior are unresolved.

### Worker and scheduler

A lightweight background process is intended to run screening jobs and likely ingestion jobs. It should support queued, processing, completed, and failed states, retries, useful failure messages, and idempotent execution.

Periodic source checking is intended, but the scheduler mechanism and source-specific frequencies remain unresolved. A scheduled trigger should be able to no-op when a source has not changed.

### Ingestion adapters

Source-specific adapters should encapsulate acquisition and parsing differences without creating a giant hard-coded script. They should support, where applicable:

- pagination;
- retries and timeouts;
- ETags, release metadata, timestamps, or checksums for change detection;
- raw snapshot recording;
- source-specific schema and spatial validation;
- reproducible staging into canonical structures.

The product contract and common/source-specific adapter boundaries are defined in `docs/SCREENING_CONTRACT.md`. A first local subset is implemented, including a fixture-only SSURGO canonical query; it does not implement production/regional canonical promotion, source catalog/version transactions in PostGIS, or adapters for PAD-US/FEMA. FEMA access and complete regional PAD-US package access still block final source approval.

#### Source acquisition and implementation status

- **PAD-US:** the official 4.1 MapServer returns versioned polygon features and useful categorical/source fields, but its service directory exposes only the Fee layer. The complete Colorado state geodatabase package is linked through official USGS/ScienceBase but its item/file route returned HTTP 403 in this session. The owner-approved policy preserves raw shapes and attributes, runs deterministic `make_valid` only in derived staging, checks equal-area change and topology, and quarantines candidates that fail. In the five-feature sample, two valid features were accepted unchanged and three repaired candidates quarantined; this sample is not a regional count or coverage estimate. No full regional QA is claimed until the complete package is acquired.
- **Annual NLCD:** the existing fixture path remains WCS 1.0.0/EPSG:3857 and snapshot-pinned. The separate regional acquisition path requests only the official 2025 WCS window for the exact three-county boundary in EPSG:5070 with nominal 30 m `resx`/`resy`, retains the provider-snapped affine transform and approximately 30 m x/y resolution, and validates a 47,189,394-byte, 8,064 × 5,664 `uint8` response with nodata 250, 100% AOI footprint coverage, and 16 observed official class values. Its 24,388,976 outside-AOI pixels are explicitly outside the screening area. The response is an inactive validation candidate, not an active canonical source; no pixel table, refresh scheduler, mosaic/window splitter, or production-readiness claim exists.
- **3DEP:** the existing ImageServer path provides a snapshot-pinned, resampled 10 m EPSG:5070 fixture/smoke workflow. The separate `ingest-3dep` path queries the official TNM Access inventory, plans one product per intersecting 1x1-degree tile, downloads native 1/3-arc-second GeoTIFFs independently, and records tile IDs, dated product metadata, request parameters, raster validation, checksums, and AOI provenance before leaving each candidate inactive. The native validator requires EPSG:4269, 1/3-arc-second resolution, a regular north-up transform, readable single-band supported datatype, and nodata `-999999`; nodata and uncovered areas remain unknown. The bounded path does not clip, resample, mosaic, promote, derive terrain metrics, or claim full regional production readiness. The prior TNM 8-tile/3.07-GB bounding-box estimate remains an estimate, not an acquisition result.
- **SSURGO:** implemented bounded SDA Post REST query using the official clipped-mapunit macro, returning AOI-clipped mapunit polygons and component attributes. A 1,893-byte live query returned 3 map units/6 unique component rows and full polygon coverage of a 0.00948 km² test AOI. Component hydric rating is soil information, not a wetlands inventory or regulatory determination. The exact approved three-county union has 19 confirmed intersecting survey areas; the automated regional package workflow acquired all 19 official WSS ZIPs, measured 394,959,419 compressed bytes matching provider `Content-Length`, and passed CRC/spatial/tabular container validation. Read-only package QA found 13 passes, 6 failures, 10 original invalid polygons, and all 19 package/AOI intersections. The discrepancy audit found all 10 diagnostic derivations valid/nonempty with unchanged polygon component counts, ring-count changes, joinable attributes, 17 confirmed identities, and 2 harmless naming variations. The staging path then loaded 19 packages, 123,196 features, 1,878 map units, and 7,404 components into derived PostGIS staging, accepting all 10 audited repairs and quarantining none. Packages remain inactive, no active source version was created, and complete regional canonical coverage remains unverified.
- **FEMA NFHL:** no service data or sample was obtained. Effective and pending products remain separate; missing coverage stays unknown. No FEMA adapter assumptions beyond provider metadata are validated.

The generic SSURGO acquisition path is separate from the current fixture-only screening and regional staging paths. It consumes a persisted generic AOI, discovers current survey-area releases through SDA, resolves official WSS cache packages, persists a deterministic bounded plan, and retains each package as an inactive candidate. A live DC001 smoke outside Northern Colorado passed package-container validation; this does not change the representative SSURGO maturity, establish full arbitrary-AOI coverage, or permit screening consumption.

The generic `ingest-aoi` workflow is an orchestration boundary over those three adapters. It creates one SQLite parent run keyed to the immutable project/AOI revision and geometry hash, writes a deterministic plan containing source order, adapter identity, official planning endpoint, and explicit limits before network acquisition, then executes selected sources independently. NLCD, 3DEP, and SSURGO continue to own their request construction, provider validation, raw storage, child runs, attempts, checksums, and inactive candidates; the parent stores links and an aggregate machine-readable status. A retry reuses the original plan and AOI hash, selects only failed/incomplete source entries, appends attempt history, and never removes a prior candidate. Parent records and plan/run summaries are external artifacts; no cross-database foreign keys or active-version updates are introduced.

The product-facing maturity vocabulary (`validated`, `conditionally_validated`, `access_blocked`, `failed`, `not_acquired`), separate AOI coverage states, observation outcomes, and missing-data behavior are runtime JSON fields for this slice. They are not database enums. A source's static validation maturity and a per-run `attempt_status` remain separate; per-run success does not rewrite source maturity or complete Milestone 1 approval.

### Screening engine

The screening engine should evaluate each project AOI independently against each active source version. The verified SSURGO fixture path evaluates only the exact snapshot/version captured by the job and uses direct intersection, area, percentage, map-unit, and component metrics. The verified NLCD fixture path reads only the exact snapshot raster, uses the AOI/raster-footprint intersection and native categorical cells, and reports explicit valid/nodata/class metrics without creating a PostGIS pixel table. The verified 3DEP fixture path reads only the exact snapshot raster, uses the same AOI/raster-footprint accounting, and reports raw elevation statistics without creating a PostGIS pixel table or derived slope. It should prefer direct, interpretable physical metrics over a composite environmental score. Likely operations include intersection, area and percentage calculations, line length, proximity, and raster statistics where a raster source is selected.

The known-good regression/demo geography is the validated three-county union (Boulder, Larimer, Weld; approximately 7,391 sq mi), including all three disconnected union components. The generic AOI policy does not impose this boundary; the named regression policy does. The local prototype uses bounded raster windows and does not yet tile larger arbitrary AOIs. SSURGO output retains map-unit/component context and explicitly says that hydric ratings are soil information, not wetlands mapping or evidence of jurisdictional-wetland presence/absence. FEMA's effective/pending path is not implemented; the result remains blocked/unavailable, and the target contract requires unmapped/unavailable areas to stay unknown. Other full source metrics remain intended or partially implemented per `SCREENING_CONTRACT.md`.

Regulatory thresholds, hazard interpretations, and environmental categorization language must not be invented by an agent. They require evidence and owner review.

## Data and storage architecture

### Raw, staging, and canonical layers

The intended lineage is:

```text
external source
  -> source catalog
  -> raw snapshot in object storage
  -> staging and source-specific validation
  -> normalized canonical dataset in PostGIS
  -> validated active dataset version
  -> screening result linked to used versions
```

Raw source material should retain acquisition time, source identity, original metadata where useful, checksum, and source version/release information when available. Raw data is not expected to be committed to Git.

The local slice implements this as an external filesystem raw store with content-addressed response bytes and append-only acquisition event JSON. Project, AOI, job, result, CSV, and GeoJSON files also live under that external directory. Milestone 2B.2 adds a backend-neutral `SourceRepository` interface with a local SQLite metadata implementation under `catalog/`; SQLite transactions serialize candidate registration and promotion. Milestone 2B.4 adds a separate optional `SpatialRepository` interface with a local PostGIS implementation under `spatial.py`; it stores canonical AOI geometry, fixture-only SSURGO map-unit/component records, and derived regional SSURGO staging records, links to SQLite-owned source snapshot/version IDs as explicit text, and has no cross-database foreign keys. SSURGO fixture staging/validation/promotion is defined in migration `002_ssurgo_mapunits`; owner-approved regional derived staging is defined in migration `003_ssurgo_regional_staging` and has no active-source promotion path. Raw files have no object-lock or retention guarantee, and the existing JSON project/job store still has no concurrent-worker or multi-record transaction guarantee. PostGIS remains the intended canonical spatial store and hosted repository target.

The regional SSURGO staging aggregate has a separate catalog materialization boundary. `materialize-ssurgo-regional-candidate` treats the external aggregate JSON as a derived candidate artifact, rechecks its checksum and all 19 package/report/raw-artifact links, and records one source version, acquisition attempt, incomplete ingestion run, and inactive candidate. Its validation JSON carries the synthetic regional source snapshot, package candidates/runs/versions, raw checksums, staging batch, repair audit, QA report, measured counts, and the unresolved coverage limitation. The aggregate source version is never inserted into `active_versions`; repeated materialization is resolved by the immutable source-version checksum identity.

The regional coverage disposition extends that boundary without activating data. `promote-candidate` records a rejected promotion decision for the SSURGO candidate when its regional coverage validation contains uncovered or overlapping residuals, using the measured 842.5 m² / 43-component / 30-interior-residual / 160.7 m²-overlap reason. The candidate remains `not_promoted`, its partial/incomplete-source statuses and regional report lineage are preserved, and residual areas remain unknown. This source-specific guard does not alter other source promotion or screening behavior.

The local PostGIS setup is `postgis/postgis:16-3.4` with a health check and an externally configured bind-mounted data directory. Credentials and the connection URL are environment-provided. Migration `001_aoi_revisions.sql` creates the AOI boundary: canonical AOI revisions, preserved source components, spatial indexes, validity constraints, source/analysis CRS metadata, and provenance. Migration `002_ssurgo_mapunits.sql` adds SSURGO batch/staging tables and separate fixture-only canonical map-unit/component tables. Migration `003_ssurgo_regional_staging.sql` adds package, map-unit, component, and feature staging tables with original/derived geometries, QA diagnostics, source attributes, and candidate/run/version lineage. The Census boundary loader transforms preserved EPSG:4269 county geometries to EPSG:4326 canonical geometry and measures area in EPSG:5070; it does not narrow, repair, or silently discard the approved counties. The SSURGO loaders preserve provider `mukey`/`cokey` and hydric fields, validate joins and geometry, and keep regional staging separate from active versions. All three migrations and the regional staging loader were executed successfully against the pinned container on 2026-09-24, including direct validity, component, CRS, linkage, idempotency, quarantine, and transaction-rollback checks. This verifies the local repository boundary and derived staging path only, not a deployed database, active regional source version, or environmental source completeness.

### Conceptual database entities

The schema is expected to include concepts such as:

- `datasets`: logical environmental sources and provider/license metadata;
- `dataset_versions`: acquired, validated, active, or superseded versions;
- `ingestion_runs`: attempts, status, timing, checksums, counts, validation results, and errors;
- normalized environmental layer tables: source-specific canonical spatial data;
- `projects`: analyst-created screening projects;
- `project_areas`: project geometry and relevant geometry metadata;
- `screening_jobs`: requested workflow, status, retry/error information, and timestamps;
- `job_source_snapshots`: immutable per-job/AOI source-version resolution and missing-data state;
- `screening_results`: per-dataset metrics, result geometries or references, and source-version lineage.

Exact normalization, table names, geometry types, raster strategy, and retention rules are development decisions constrained by the selected sources.

### Spatial database expectations

PostGIS is a core architectural boundary, not a résumé-only dependency. The implementation should use intentional geometry columns, GiST spatial indexes, suitable conventional indexes, migrations, and query profiling. Techniques such as subdivision should be used only where actual data and query plans justify them.

### Version activation

The local catalog implements candidate-first acquisition metadata for Census, NLCD, 3DEP and SSURGO. The acquisition callback durably creates an `incomplete` candidate and checksum/release version before parsing; adapter validation finalizes that candidate as validated, failed, or incomplete. Each run, acquisition attempt, candidate validation and immutable `(source, release, SHA-256)` version is queryable; PAD-US quarantine and FEMA blocked outcomes are recorded without acquisition or promotion. Explicit promotion verifies candidate/run/validation/coverage/quarantine states and re-hashes the external artifact inside a SQLite `BEGIN IMMEDIATE` transaction before advancing the active-version pointer. Failed, partial, quarantined or blocked candidates cannot activate; version bytes and metadata are retained when a later version is promoted. Repeating a decision for the same candidate is idempotent.

Generic Annual NLCD and 3DEP candidates use the same catalog and promotion
transaction, but their active pointer is AOI-scoped. Promotion requires the
persisted project, immutable AOI revision, exact geometry hash, acquisition
run, source version, artifact checksum/size, complete AOI footprint, native
raster metadata, and an eligible observed validation state. The catalog stores
these pointers in `active_aoi_versions`; a pointer for one AOI revision cannot
serve another revision, and a failed replacement leaves the prior pointer
unchanged. Candidate failures remain queryable with an auditable rejection
decision. The legacy `active_versions` pointer remains for existing unscoped
fixture behavior. SSURGO, PAD-US, and FEMA are not enabled by this slice.

The `screen-active` coordinator is the active-version consumer for these two
sources. It passes the project/AOI scope to snapshot creation with legacy
global fallback disabled, persists the immutable snapshot rows, and invokes
the existing raster processors against the snapshot's promoted artifact path.
The raster readers window large native tiles to the AOI while retaining full
source dimensions/grid metadata; outside-AOI and nodata areas remain explicit.
The result/export layer labels these outcomes `active_aoi`, carries the active
pointer/source-version/candidate/run/checksum lineage, and emits only a
meaningful 3DEP footprint when available. Fixture modes use the same processors
with their existing `fixture_only` labels.

`report-aoi-run` is a read-only operational projection over the same SQLite
control-plane catalog and file-backed job records. It validates the requested
project/AOI/revision identity, reads deterministic parent plans, joins child
runs/attempts/candidates/source versions/promotions/active pointers, and loads
matching screening jobs and immutable snapshots from the external data root.
It returns both complete raw lifecycle records and a per-source lifecycle
section; it never writes a report record, refreshes an active pointer, or
collapses unknown, unavailable, incomplete, nodata, pending, quarantined, or
rejected states into success or absence.

The static frontend is a read-only projection over this report contract in
static-preview mode.
`frontend/src/main.mjs` loads the checked-in/generated `report-aoi-run` JSON
document. Its primary route is a full-viewport, map-centric environmental
screening workspace with a compact one-row project/AOI header, a collapsed
layer-availability control, independent compact source findings, and primary
tabs for Screening, Reports, and Data sources. Technical provenance is kept in
the separate operations route and expandable data-source details. The
workspace uses the recorded AOI geometry, masked Annual NLCD 2025 display
derivative, and optional 3DEP relative-hillshade display derivative in the
checked-in fixture. The 3DEP derivative is disabled by default and does not
expose vertical units, datum, or converted elevation values when the source
raster does not declare them. Both derivatives are loaded from checked-in
PNG/metadata assets, preserve source version/checksum/AOI lineage, use WGS84
bounds derived from their source raster windows, and render only valid AOI
pixels with nodata and outside-AOI pixels transparent. `?view=operations` opens the secondary
technical operations view
with plans, attempts, candidates, promotions, and lifecycle detail. Static-preview
mode neither acquires data nor connects to SQLite or PostGIS; the primary route
does request public OpenStreetMap basemap tiles and shows their required
attribution. The checked-in Washington,
DC document is explicitly a recorded demonstration result. The frontend does
not add screening behavior, source geometries, a composite score, or regulatory
conclusions, and preserves the report's independent unknown/incomplete/
unavailable states. Leaflet, its CSS, and marker assets are bundled into the
static build so the map does not depend on a runtime CDN.

The primary workspace has a local `Load AOI` session path for a GeoJSON file or
pasted GeoJSON document. It accepts only a valid, nonempty WGS84 Polygon or
MultiPolygon, computes bounds and a deterministic browser geometry hash, and
fits the Leaflet map to the replacement geometry. In static-preview mode this
is presentation state only: recorded DC metrics and display derivatives are
cleared and replaced with explicit `not_evaluated` states. When served through
the development `screening serve` bridge, `Run screening` sends the loaded
geometry to the local bridge, which creates the durable AOI revision and
NLCD-only job and returns its queued/running/succeeded/failed report. The
bridge validates the backend geometry hash and exact source lineage before
displaying results; it does not generate a browser preview. Invalid or empty
input is rejected without repair, clipping, or expansion.

When a screening job is created, the catalog resolves every requested source against the active pointer and writes an immutable `job_source_snapshots` row before processing. Each row records the job/AOI revision, source version when available, candidate/run lineage, maturity, coverage, observation, snapshot status, reason, and provenance. The worker reads that snapshot only: it does not acquire a newer candidate or re-resolve the active pointer. A missing or checksum-invalid artifact becomes unavailable for that execution without mutating the historical snapshot. Retry reuses the same rows; a new `create_job` call is the explicit fresh-snapshot operation. This does not load canonical geometry/raster data into PostGIS.

## Processing pipelines

### Source refresh pipeline

```text
scheduled check
  -> determine whether upstream changed
  -> acquire source
  -> checksum and record provenance
  -> stage and normalize
  -> run source-specific data-quality gates
  -> load candidate version
  -> promote if valid
  -> expose status and logs
```

The `screening ingest` CLI runs an explicit source acquisition as an inactive candidate. Inspection commands list ingestion runs, source versions, candidates by source/status, acquisition attempts/validation from candidate detail, and the active version; `retry-ingestion` creates a new linked run instead of erasing the failed attempt. `promote-candidate` is a separate owner/operator action. Screening job creation now snapshots the active pointer for every requested source, including explicit PAD-US quarantine and FEMA access-blocked states; execution and retry use those exact rows. The bounded SSURGO fixture mode consumes only matching fixture-only PostGIS rows; it does not provide general canonical loading, source scheduling, provider change detection, or asynchronous queue execution.

The pipeline must be retry-safe and idempotent. Failed candidates must not silently replace an active version.

Regional SSURGO derived staging follows the same candidate-first rule: staging validation may produce a durable inactive candidate, but conditional maturity, partial coverage, failed/incomplete status, or unresolved regional coverage cannot be promoted. Raw ZIPs, original geometries, staging records, repair diagnostics, and package-level provenance remain queryable independently of the derived aggregate candidate.

### Screening pipeline

The current CLI writes a `queued` job and synchronously processes its already-persisted source snapshot. Missing active versions and unavailable artifacts remain source-level outcomes; they are never replaced by live acquisition or a newer candidate. The explicit SSURGO fixture mode queries the AOI against only the snapshot-pinned fixture rows and preserves uncovered/unknown/unavailable distinctions. This is not an asynchronous service or queue.

```text
API accepts project/screening request (intended; not implemented)
  -> create queued job
  -> worker claims job
  -> resolve active dataset versions
  -> calculate per-source metrics
  -> persist results and lineage
  -> mark complete or failed
  -> API/frontend retrieve status and results
```

The screening should remain small enough for modest hosted resources. Long-running spatial work should not depend on an open HTTP request.

## External dependencies and data sources

The known-good regression/demo fixture is the 2025 Census union of Boulder (08013), Larimer (08069), and Weld (08123), about 7,391.206 sq mi. The archive and selected GEOID subset are outside Git. The valid NAD83/EPSG:4269 union is a three-component MultiPolygon with one main connected county body and two small detached source components; preserve them rather than narrowing the fixture. The older generalized TIGERweb sample is diagnostic only. The owner-selected MVP source direction remains FEMA NFHL, USGS PAD-US 4.1, USGS Annual NLCD Collection 1.2 (2025 land cover), USGS 3DEP 1/3 arc-second DEM, and NRCS SSURGO component hydric-soil information. NWI was superseded for the MVP because exact release-specific redistribution terms could not be confirmed; it is not a substitute or current dependency. The local Milestone 2B adapter/workflow subset is described above and in `docs/PROJECT_STATE.md`. PAD-US's five-feature Fee sample has two unchanged accepted records and three quarantined repaired candidates under the owner-approved policy; official access to the complete Colorado state package returned HTTP 403, so no complete regional intersection or quarantine/gap results are known. FEMA remains provider-access blocked with no effective/pending sample validation. See `docs/SOURCE_FEASIBILITY.md` and the external manifest for measured evidence and remaining gaps.

The source-feasibility document distinguishes owner direction, public-use evidence, representative artifact checks, and unresolved access/coverage. Do not treat a small live request as regional validation. Preserve response versions/checksums; for FEMA keep pending apart from effective products, and for all sources represent absent/unavailable coverage as unknown rather than a negative environmental finding.

## Deployment architecture

The intended hosted shape requires:

- a deployable frontend;
- a running API;
- a worker and queue mechanism;
- managed PostgreSQL/PostGIS or an equivalent hosted database;
- object storage for raw snapshots;
- automated main-branch deployment;
- migration handling;
- post-deployment health/smoke checks.

The hosting provider, container runtime, database provider, object-storage provider, secrets mechanism, and rollback approach are unresolved. A purely static host is insufficient for the intended architecture.

## Important technical boundaries

- The platform is one coherent application, not a collection of microservices.
- Raw source preservation is separate from canonical active data.
- Staging/validation is separate from activation.
- Dataset version metadata and screening lineage are first-class concerns.
- The API is the frontend's application boundary; direct database access from the browser is not intended.
- Background processing owns long-running ingestion and screening work.
- Product-facing screening results must remain transparent and preliminary.
- Authentication, if added, should be simple and must not grow into enterprise IAM.
- Infrastructure must remain proportional: no Kubernetes, Kafka, distributed-compute layer, or Terraform requirement without a demonstrated need.

## Architecture decisions still required

The geography and MVP source direction are owner-selected, but final source approval remains open for full regional PAD-US coverage/repair statistics and FEMA technical access plus effective/pending validation. Milestones 2B.2–2B.4 metadata/spatial-boundary work does not close that gate or mean that source adapters are production-ready. Remaining choices include loading normalized environmental source data behind immutable snapshots, queue/worker library, raster storage strategy, authentication, hosting, source refresh schedule, exact large-AOI tiling behavior, and optional PDF reporting. Any added metrics or thresholds must stay within the existing contract and owner decision boundaries.
