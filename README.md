# Environmental Screening & GeoData Operations Platform

This repository currently contains the first local ETL/screening slice described in [the project state](docs/PROJECT_STATE.md). It is a prototype and source maturity remains limited to the scopes described in [source feasibility](docs/SOURCE_FEASIBILITY.md) and the [screening contract](docs/SCREENING_CONTRACT.md).

## Local setup

Use Python 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/mypy src
```

The local PostGIS boundary is optional and is not required for the deterministic test suite. It uses the pinned `postgis/postgis:16-3.4` image, an external bind-mounted data directory, and credentials supplied through the environment; no credentials are committed. With Docker and the optional client installed:

```bash
export POSTGIS_USER=screening
export POSTGIS_PASSWORD='set-a-local-password'
export POSTGIS_DB=screening
export ESGP_POSTGIS_DATA_DIR=/home/aarondroper/projects/environmental-screening-platform-data/postgis
export ESGP_POSTGIS_URL='postgresql://screening:set-a-local-password@localhost:5432/screening'
.venv/bin/python -m pip install -e '.[dev,postgis]'
docker compose up -d postgis
.venv/bin/screening --data-dir "$DATA_DIR" postgis-migrate
```

The boundary loader requires explicit SQLite-owned identifiers and preserves all three 2025 Census county components while storing their canonical union. For an approved external artifact, use `postgis-load-boundary` with the exact `source_snapshot_id` and `source_version_id`; the loader records the EPSG:4269 source geometry, EPSG:4326 canonical geometry, and EPSG:5070 analysis-area metadata. The PostGIS volume and source artifact remain outside Git.

All runtime records and raw source responses must live outside this repository. For example:

```bash
DATA_DIR=/home/aarondroper/projects/environmental-screening-platform-data/local-run
.venv/bin/screening --data-dir "$DATA_DIR" project-create --name "Example review" --aoi /path/to/aoi.geojson
.venv/bin/screening --data-dir "$DATA_DIR" screen --project-id PROJECT_ID
.venv/bin/screening --data-dir "$DATA_DIR" export --job-id JOB_ID --output-dir "$DATA_DIR/exports"
```

AOI input is GeoJSON WGS84 longitude/latitude with one valid, nonempty Polygon or MultiPolygon. New projects use the generic AOI validation policy and may be outside Northern Colorado; AOI changes create new immutable revisions with the input geometry hash and policy provenance. The Northern Colorado containment rule is an explicit regression/demo policy:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" project-create \
  --name "Northern Colorado regression" \
  --aoi /path/to/aoi.geojson \
  --aoi-policy northern_colorado_regression
```

That policy automatically retrieves/caches the official 2025 TIGER/Line county ZIP when needed and retains the validated Boulder/Larimer/Weld fixture boundary. The official archive is about 84 MB; no other national environmental products are downloaded. Generic source acquisition is bounded and source-specific; generic SSURGO package acquisition is now available, while staging, mosaicking, and regional coverage analysis remain separate work.

The `screen` command creates a new source snapshot for the requested AOI and currently executes the local worker synchronously. The worker processes only the exact active versions captured at job creation; it does not acquire a newer candidate during execution. When passed `--database-url`, it can consume matching fixture-only SSURGO PostGIS records. The explicitly bounded command below is preferred for that path:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" screen-ssurgo-fixture \
  --project-id PROJECT_ID --database-url "$ESGP_POSTGIS_URL"
```

For the bounded Annual NLCD path:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" screen-nlcd-fixture \
  --project-id PROJECT_ID
```

This creates a single-source `nlcd_fixture_only` job. It reads only the exact snapshotted external GeoTIFF, reports footprint coverage, valid/nodata pixels, source class counts/percentages, and raster CRS/grid provenance, and does not claim full regional coverage or production readiness. NLCD pixels are summarized in JSON/CSV; no misleading pixel geometries are added to GeoJSON.

For automated acquisition against any persisted generic AOI, use the explicit AOI-bound command:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" ingest-nlcd \
  --project-id PROJECT_ID [--aoi-id AOI_ID]
```

This builds the official Annual NLCD WCS request from the selected immutable AOI revision, uses the native EPSG:5070/30 m grid and nodata/class contract, records the AOI geometry hash and exact request/provenance, and creates an inactive candidate. Requests above the bounded cell limit fail before HTTP acquisition; clipping and tiling are not implemented. Outside-AOI pixels and AOI nodata remain explicit non-observation/unknown states. `ingest-nlcd-regional` remains the Northern Colorado regression/fixture alias.

For the bounded 3DEP elevation path:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" screen-3dep-fixture \
  --project-id PROJECT_ID
```

This creates a single-source `3dep_fixture_only` job. It reads only the exact snapshotted external DEM, reports footprint coverage, valid/nodata cells, raw elevation statistics, CRS/grid/nodata metadata, and vertical units/datum when declared. It performs no unit/datum conversion or slope calculation. A covered result may include one raster-footprint feature in GeoJSON; pixel geometries are not generated, and full regional coverage is not claimed.

For AOI-agnostic 3DEP tile planning and acquisition, use:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" ingest-3dep \
  --project-id PROJECT_ID [--aoi-id AOI_ID]
```

This queries the official TNM Access inventory for the persisted AOI, writes a deterministic one-product-per-intersecting-tile plan before downloading, and records each native 1/3-arc-second GeoTIFF as an inactive candidate with tile, release, request, raster metadata, checksum, and AOI geometry-hash provenance. Oversized AOIs, incomplete inventory responses, invalid URLs, unreadable/non-native rasters, nodata, and uncovered AOI areas remain explicit; tiles are not silently clipped, substituted, mosaicked, or activated. `screen-3dep-fixture` and the Northern Colorado regression workflows remain unchanged.

For AOI-agnostic SSURGO survey-area discovery and package acquisition, use:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" ingest-ssurgo \
  --project-id PROJECT_ID [--aoi-id AOI_ID]
```

This queries the official NRCS SDA intersection function for the persisted AOI, resolves current Web Soil Survey package URLs from `sacatalog` release metadata, writes a deterministic plan before package downloads, and enforces survey-area and aggregate-byte limits. Each ZIP is recorded as an inactive candidate with provider-reported/measured size, HTTP metadata, checksum, AOI revision/geometry-hash, and container validation. Failed downloads and package mismatches remain explicit candidates. `ingest-ssurgo-regional` remains the Northern Colorado 19-package regression alias; this generic path does not stage, repair, clip, measure coverage, or promote SSURGO, and hydric fields remain soil information rather than wetlands determinations.

For the bounded multi-source fixture path:

For one generic AOI acquisition plan spanning the existing NLCD, 3DEP, and SSURGO adapters, use:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" ingest-aoi \
  --project-id PROJECT_ID --aoi-id AOI_ID \
  --sources nlcd 3dep ssurgo \
  --max-source-bytes nlcd=256000000 \
  --max-source-artifacts 3dep=16 \
  --max-total-bytes 1000000000
```

The command writes a deterministic plan before provider access, creates one parent SQLite control-plane run, and executes selected sources independently through the existing generic adapters. It records child attempts/candidates, measured bytes, checksums, validation/coverage outcomes, AOI geometry-hash lineage, warnings, and unknown coverage; all candidates remain inactive. Add `--dry-run` to persist planning metadata without network requests. A retry uses `--retry-parent-run-id` and optionally `--retry-sources` to rerun only failed/incomplete sources under the original immutable AOI plan. This orchestration does not acquire FEMA/PAD-US, promote sources, or change screening semantics.

```bash
.venv/bin/screening --data-dir "$DATA_DIR" screen-fixtures \
  --project-id PROJECT_ID --database-url "$ESGP_POSTGIS_URL"
```

This creates one `fixtures` job for the validated Census AOI revision. It runs the existing SSURGO, Annual NLCD, and 3DEP fixture processors against their immutable source snapshots, and includes PAD-US (`conditionally_validated`/quarantined) and FEMA (`access_blocked`) in the source-status matrix without processing either source. JSON preserves nested source results; CSV has one row per source plus repeated matrix metadata; GeoJSON contains only the AOI and meaningful SSURGO/3DEP geometries. `job_status=completed` does not mean complete evidence: inspect `overall_status`, `job_outcome`, and each source's coverage/observation state.

For generic screening from promoted AOI-scoped raster versions, use:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" screen-active \
  --project-id PROJECT_ID --aoi-id AOI_ID --sources nlcd 3dep
```

This creates immutable snapshots of only the exact active Annual NLCD and/or
3DEP versions for that project/AOI revision, then processes the promoted
artifacts named by those snapshots. It never falls back to a global fixture or
unpromoted candidate. Results retain active/source version IDs, candidate and
ingestion-run lineage, AOI geometry hash, checksums, raster metrics, and
coverage/nodata states. Retrying a failed job reuses the original snapshots;
promoting a later version requires a new job. NLCD and 3DEP remain independent
descriptive metrics; no composite or regulatory conclusion is produced.

For a read-only lifecycle report covering one persisted project and immutable
AOI revision, use:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" report-aoi-run \
  --project-id PROJECT_ID --aoi-id AOI_ID --aoi-revision 1
```

The default output is deterministic JSON containing the AOI identity and area,
parent plans/runs, child acquisition attempts and retries, artifact counts and
checksums, source versions, candidates, validation outcomes, promotion
decisions, active AOI-scoped versions, screening jobs/snapshots/results, and
independent source lifecycle states. Use `--format summary` for a concise
terminal view. The report is read-only, works for generic AOIs, performs no
provider access, and keeps unknown/unavailable/incomplete/nodata/quarantined
states distinct from no constraint observed.

For the primary static environmental-screening demonstration, build and serve
the dependency-free frontend:

```bash
cd frontend
npm install
npm test
npm run build
python3 -m http.server 8080 --directory dist
```

Open <http://localhost:8080/>. The primary route is a single-screen,
map-centric screening workspace that reads the checked-in
`frontend/public/demo/report.json`, a recorded Washington, DC smoke result. It
uses the recorded AOI geometry and source-specific metrics in a bundled
Leaflet map with an attributed public OpenStreetMap basemap. The map layer
control renders the AOI boundary and the masked Annual NLCD 2025 display
derivative with its observed-class legend and opacity control. It also offers
an optional restrained 3DEP relative-hillshade display derivative, disabled by
default; the retained 3DEP raster declares no vertical units or datum, so the
preview shows no elevation values or conversion. SSURGO, PAD-US, and FEMA remain incomplete, conditional, or
unavailable rather than being represented by invented overlays. Secondary tabs
expose reports/exports, data-source availability, and technical provenance.
The primary results list is intentionally compact: observed metrics are shown
inline, source details are expandable, and hashes, IDs, and operational
history stay in the secondary technical views. Primary navigation is limited
to Screening, Reports, and Data sources; the operations console is a separate
technical route rather than part of the screening workspace.
The browser needs network access for basemap tiles, but the workspace performs
no environmental provider acquisition, backend processing, PostGIS access, raw
source download, or new screening behavior. It does not present a composite
score, safety/suitability conclusion, or regulatory determination.

For a local development-only end-to-end Annual NLCD run from a loaded AOI,
build the frontend and serve it through the standard-library bridge instead:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" serve \
  --frontend-dir "$PWD/frontend/dist" --host 127.0.0.1 --port 8080
```

The primary `Run screening` action sends the currently loaded validated
GeoJSON AOI to the local bridge. The bridge creates an immutable AOI revision
and job, runs the existing generic NLCD acquisition/validation/AOI-scoped
promotion/snapshot-pinned screening path, and reports queued, running,
succeeded, or failed states. After a successful run it generates an
AOI-specific categorical NLCD display derivative from the exact snapshotted
raster and serves its provenance metadata and PNG through job-scoped local
routes. The workspace renders that layer with transparent outside-AOI/nodata
pixels and click identification by human-readable NLCD class. It is not
deployed, authenticated, or backed by a queue; it does not reuse Washington,
DC metrics or previews, or process 3DEP, SSURGO, FEMA, or PAD-US. Those
sources remain explicitly not evaluated for the run. Raw artifacts and
catalog/workspace records remain under the external data directory.

Use `Load AOI` in the primary workspace to choose a local GeoJSON file or paste
GeoJSON. The browser accepts one valid, nonempty WGS84 Polygon or MultiPolygon,
shows its bounds and deterministic geometry hash in the secondary AOI details,
and fits the map to the loaded geometry. In static-preview mode this remains a
display-only session action. Through `screening serve`, `Run screening`
persists that geometry and starts the local NLCD workflow. Recorded Washington,
DC metrics and NLCD/3DEP previews are never reused for a replacement geometry;
other sources remain `Not evaluated` unless independently processed. Invalid,
empty, non-area, malformed, or self-intersecting input is rejected, while the
DC demonstration remains the default and reset state.

The report links to the secondary technical operations view at
<http://localhost:8080/?view=operations>. That view projects the same report's
plans, attempts, retries, candidates, promotions, and source lifecycle for
provenance review; it is not the primary user workflow.

The SSURGO command creates a single-source `ssurgo_fixture_only` job. It reports exact snapshot/version provenance, fixture-only status, covered/uncovered AOI area, map-unit/component metrics, and hydric-soil attributes. It never selects latest data or claims regional SSURGO coverage. Sources without an active version, including PAD-US and FEMA in the current state, remain explicit unknown, quarantined, or unavailable outcomes. To use newly promoted data, create a new screening job; retry reuses the original snapshot. Active regional canonical environmental layers and regional tiling are not implemented.

Source ingestion is separately available as a candidate-first operator workflow. For example:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" ingest --source annual_nlcd --project-id PROJECT_ID
.venv/bin/screening --data-dir "$DATA_DIR" ingestion-runs
.venv/bin/screening --data-dir "$DATA_DIR" source-versions
.venv/bin/screening --data-dir "$DATA_DIR" candidates --status quarantined
.venv/bin/screening --data-dir "$DATA_DIR" candidate-status --candidate-id CANDIDATE_ID
.venv/bin/screening --data-dir "$DATA_DIR" promote-candidate --candidate-id CANDIDATE_ID
.venv/bin/screening --data-dir "$DATA_DIR" active-version --source annual_nlcd
```

Generic Annual NLCD and 3DEP candidates require their exact persisted AOI
scope for promotion. For example:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" promote-candidate \
  --candidate-id CANDIDATE_ID --project-id PROJECT_ID \
  --aoi-id AOI_ID --aoi-revision 1
.venv/bin/screening --data-dir "$DATA_DIR" active-version \
  --source annual_nlcd --project-id PROJECT_ID \
  --aoi-id AOI_ID --aoi-revision 1
```

Promotion rechecks the artifact checksum/size, source-version and run
lineage, AOI geometry hash, complete AOI footprint, native raster metadata,
and observation state. It is idempotent and preserves a prior AOI-scoped
active version when a replacement fails. SSURGO, PAD-US, and FEMA are not
promoted by this AOI-scoped raster slice; the Northern Colorado fixture
aliases and legacy unscoped fixture promotion remain unchanged.

The approved three-county Annual NLCD 2025 regional acquisition is a separate validation-only workflow:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" ingest-nlcd-regional
```

It requests only the exact Boulder/Larimer/Weld window from the official USGS/MRLC WCS in EPSG:5070 at nominal 30 m resolution, records the provider-snapped transform, dimensions, nodata, observed class domain, AOI/outside-AOI accounting, HTTP metadata, retrieval timestamp, byte size and checksum, and creates an inactive candidate. It does not download a national bundle, create an active version, add NLCD pixels to PostGIS, or interpret land-cover classes as constraints. The measured regional response is a padded rectangle, so outside-AOI pixels and nodata remain explicit unknown/non-observation states.

`ingest` creates an inactive candidate; promotion is a separate explicit step. `retry-ingestion --run-id RUN_ID` creates a new linked run and preserves the prior attempt. Candidate metadata, acquisition attempts, validations, decisions, the active-version pointer, and immutable job source snapshots are stored transactionally in a local SQLite catalog under the external data directory. Artifacts are rehashed at registration, promotion, and job snapshot/use boundaries. PAD-US remains quarantined/conditional and FEMA remains blocked; neither is acquired or promotable. This catalog is a local metadata/control store only; the separate optional PostGIS repository contains the representative SSURGO fixture under explicit snapshot/version linkage and does not activate it for regional screening.

The acquired regional SSURGO candidates can be checked without downloading or modifying them:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" validate-ssurgo-regional
```

This read-only validator writes per-package and aggregate QA under the external data directory. The current 19-package result has 13 package passes, 6 explicit failures (10 original invalid polygons and 2 survey-name discrepancies), and 19 package/AOI intersections. It does not repair, drop, clip, promote, or change the candidate catalog.

The retained packages can also be audited for discrepancies without changing raw files, candidates, or PostGIS:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" audit-ssurgo-regional-discrepancies
```

The current audit records diagnostic-only in-memory `make_valid` results for all 10 original invalid polygons: each derived geometry is valid, nonempty, polygonal, within the 0.1% area tolerance, and joinable to its source attributes. The two Wyoming naming differences are classified as harmless variations because the package, official lookup/SDA release, URL, checksum, and manifest identity agree; only the sizing record includes “Area.” No geometry is repaired, dropped, clipped, quarantined, staged, promoted, or written to PostGIS by this audit. The external report is the evidence record; candidates remain inactive/incomplete.

With the owner-approved repair policy, the acquired packages can be loaded into derived PostGIS staging without changing raw files or activating a source version:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" stage-ssurgo-regional \
  --database-url "$ESGP_POSTGIS_URL"
```

This stages all 19 packages, retains original and derived feature geometry plus QA lineage, and applies `make_valid` only to the 10 audited invalid polygons. The verified run loaded 123,196 features, 1,878 map units, and 7,404 components; all 10 repairs passed and none were quarantined. Staging is idempotent per source snapshot/version and remains `staging_only`; candidates remain inactive/incomplete and the existing SSURGO screening path remains fixture-only. The external staging report and manifest are the evidence record.

The completed staging result can be recorded as one inactive catalog candidate without re-downloading packages:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" materialize-ssurgo-regional-candidate
```

This creates one checksum-protected derived source version and ingestion run linked to all 19 package candidates, raw checksums, the synthetic regional snapshot, staging batch, repair audit, and QA reports. It remains `incomplete` / `conditionally_validated` with `partial` coverage and `not_promoted` status. Repeating the command returns the same candidate/version; it never advances the SSURGO active pointer. Complete regional coverage and production readiness remain unverified.

The inactive staged candidate can be measured without changing raw or staged data:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" analyze-ssurgo-regional-coverage \
  --candidate-id 9d77a86a-bdc7-4684-b977-1081f8ed484c \
  --database-url "$ESGP_POSTGIS_URL"
```

This read-only analysis records EPSG:5070 AOI/coverage, uncovered residuals, outside-AOI source area, per-survey-area contribution, package overlaps, and gap/seam diagnostic GeoJSON under the external data directory and links the aggregate checksum to the inactive candidate. It does not clip, dissolve, repair, deduplicate, promote, or consume the staged data for screening. Nonzero uncovered area remains unknown, not absence of a constraint; inspect the external report and manifest before any separate promotion decision.

An explicit `promote-candidate` attempt for this regional candidate is rejected with the measured SSURGO coverage reason and leaves the candidate `not_promoted`; the coverage reports and unknown-area state remain preserved.

The exports are a JSON source/result record, CSV with one row per source and provenance/state, and GeoJSON with the AOI plus valid SSURGO map-unit polygons produced by that run. NLCD is summarized in JSON/CSV and does not create pixel geometries; 3DEP may add one meaningful raster-footprint feature. Hydric ratings remain component-level soil data, not a wetlands inventory or regulatory wetland determination. The result is preliminary; missing or incomplete data are not treated as no constraint, and no composite score is calculated.

## Current limits

There is no deployed database, hosted API, asynchronous queue, deployment, or CI workflow yet. A bundled Leaflet static screening report and secondary operations view project one checked-in `report-aoi-run` demonstration; the development-only `screening serve` bridge is the first local live application bridge but does not replace the future API/worker surface. The primary map uses public OpenStreetMap tiles with attribution and does not expose environmental provider data beyond the checked-in report unless the local NLCD bridge is explicitly used. PostGIS is an optional local repository boundary with a validated Census regression AOI, representative fixture-only SSURGO tables, and derived regional SSURGO staging; NLCD and 3DEP fixture screening retain rasters externally and do not add pixel tables. Docker/psycopg availability is environment-dependent. Generic AOI creation, bounded generic NLCD acquisition, bounded 3DEP tile planning/acquisition, bounded generic SSURGO package acquisition, and local NLCD-only AOI screening are implemented. Generic SSURGO staging, mosaicking, regional coverage analysis for arbitrary AOIs, production coverage, and deployed API/worker operation remain future work. The live generic SSURGO smoke acquired one official DC001 package outside Northern Colorado on 2026-09-25; the result is validation-only evidence, not final source approval or production readiness. The 19 Northern Colorado package candidates and one derived regional candidate remain inactive; no active SSURGO version was created. Follow `docs/BACKLOG.md` for the next objective and `AGENTS.md` for project operating rules.
