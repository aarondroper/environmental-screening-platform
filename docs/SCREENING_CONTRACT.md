# Screening workflow and product contract — Milestone 2A / 2B

**Status:** The intended product contract remains broader than the implementation. Milestone 2B implements a local CLI/job-oriented subset for the Census boundary, NLCD, 3DEP, and SSURGO, plus optional PostGIS AOI, representative SSURGO fixture-only storage, bounded SSURGO fixture consumption, bounded snapshot-pinned NLCD/3DEP raster consumption, bounded generic NLCD/3DEP/SSURGO acquisition, and a bounded multi-source fixture orchestration job; see `PROJECT_STATE.md` for exact scope. It does not close Milestone 1, approve the final source set, or implement active regional environmental PostGIS source tables/API/queue/frontend behavior.

## 1. Product boundary

The platform provides preliminary, source-attributed environmental and physical screening for a user-submitted project AOI. The validated Northern Colorado Boulder/Larimer/Weld geography is a known-good regression/demo fixture and source-validation boundary, not a platform-wide containment requirement. It reports what selected dataset versions show, where they cover the AOI, and where they do not support a conclusion. It is not an environmental assessment, wetland delineation, flood determination, permit decision, legal opinion, engineering design, or regulatory clearance.

There is no composite risk/constraint score, pass/fail suitability verdict, invented regulatory threshold, or implication that missing, unavailable, pending, incomplete, or quarantined information means no constraint exists. Metrics remain separate by source and meaning.

## 2. Projects, AOIs, and screening runs

- A project is a durable named workspace for one consulting/planning case. Project metadata is descriptive, not an analytical input.
- A project may retain named AOIs. The primary MVP interaction is drawing a Polygon or MultiPolygon on the map; the API contract may accept equivalent GeoJSON geometry. The input CRS is WGS 84 longitude/latitude (EPSG:4326 / RFC 7946 coordinates).
- Reject empty, invalid, non-polygonal, non-WGS84, or three-dimensional AOIs with actionable validation errors. Do not silently repair or clip user AOIs. A project may explicitly select a named containment policy; the Northern Colorado regression policy requires containment by the complete approved 2025 three-county union, including its detached union components. The generic policy has no platform-wide geography boundary. Preserve holes and multipart structure.
- Editing an AOI creates a new immutable AOI revision. A screening run binds to exactly one AOI revision; changing the project AOI later never mutates an existing result.
- A screening request records its submission time, AOI revision, requested source set, and source-version snapshot. It is asynchronous; the request returns a job identifier rather than waiting for all spatial work.
- A run uses an internally consistent, pinned set of source versions. It must not silently combine an active version with a newer, partly acquired candidate. If a source has no usable version, retain its per-source unavailable/unknown outcome in the result instead of fabricating a zero.

Areas and area fractions are calculated in a suitable declared equal-area CRS (EPSG:5070 for the Northern Colorado fixture) and state their units. Distances and lengths, if later added, must likewise declare CRS/measurement semantics. Raster calculations preserve source grid, nodata, and resampling provenance; categorical NLCD must not use interpolating resampling.

## 3. Independent source and coverage states

Two different questions must be represented separately:

1. `validation_status` says how much evidence supports the acquired source artifact or release.
2. `coverage_status` says whether that source version supplies interpretable data over this particular AOI.

The source maturity vocabulary is fixed for the MVP:

| `validation_status` | Meaning |
| --- | --- |
| `validated` | The stated validation scope passed its checks. Always include `validation_scope`; a representative sample or tile does not prove full regional completeness. |
| `conditionally_validated` | Some checks passed, but a named limitation (such as quarantined candidates or unverified full coverage) prevents an unconditional source claim. List the condition and affected scope. |
| `access_blocked` | An authorized provider route could not deliver the needed metadata/data. This is an access state, not a source-quality judgment. |
| `failed` | An acquired candidate failed a required integrity, schema, coverage, or QA gate. Preserve the candidate and diagnostics; do not activate it. |
| `not_acquired` | No relevant acquisition/validation attempt has yet produced an artifact. |

Current controlled-progression maturity is:

| Selected input | `validation_status` | Known validation scope and remaining boundary |
| --- | --- | --- |
| 2025 Census county boundary | `validated` | Exact three county features and three-component union checked; approved boundary only. |
| Annual NLCD Collection 1.2, 2025 | `validated` | Representative WCS sample and one official automated regional EPSG:5070 window passed bounded raster checks; the regional candidate remains inactive/validation-only and production refresh/readiness is not established. |
| 3DEP 1/3 arc-second | `validated` | One representative tile passed; regional inventory is a bounding-box estimate, not exact acquired coverage. |
| SSURGO | `validated` | Representative SDA relational/spatial sample passed; full survey-package scale is incomplete. Hydric soil is not a wetland inventory or determination. |
| PAD-US 4.1 | `conditionally_validated` | Five-feature Fee-layer sample only: two originally valid features accepted unchanged; three repaired candidates quarantined under the owner policy. Complete regional coverage and quarantine/gap statistics are unverified. |
| FEMA NFHL | `access_blocked` | “Selected source; provider access blocked; technical suitability and effective/pending sample validation incomplete.” |

Coverage status is evaluated per source version and AOI, independently of maturity:

- `complete`: evidence supports source coverage across the requested AOI for the named product/status/time slice.
- `partial`: coverage is known for some, but not all, of the AOI; report covered and unresolved extents/fractions only where their boundaries are actually known.
- `unknown`: coverage cannot be established from the acquired metadata or data.
- `unavailable`: the source/request could not be accessed for this run.
- `not_assessed`: no AOI-specific coverage evaluation has been performed.

Represent source temporal/status dimensions separately (for example FEMA `effective` versus `pending`, or NLCD year/release); do not overload coverage or maturity fields with them. A maturity value of `validated` never implies `coverage_status=complete` for every AOI.

## 4. Observation outcomes and unknown-area behavior

Each source/AOI outcome and each reported feature/metric must use an explicit observation state. The user-facing labels below distinguish the otherwise-confusable cases:

| State | Meaning and display rule |
| --- | --- |
| `constraint_observed` | One or more accepted, queryable source features/cells intersect the AOI. Report the source-defined category and measured metric; do not assign an overall risk level. |
| `no_constraint_observed` | A successful query found no relevant features/classes **only within an AOI area known to be covered by a fit-for-purpose source version with complete applicable QA**. Display “none observed in [source/version]”; never present it as universal absence. |
| `data_observed` | A descriptive source measurement (for example land-cover classes, elevation, or soil map-unit/component attributes) was successfully acquired and summarized. It is not necessarily a constraint observation. |
| `nodata` | A raster query encountered source-declared or non-finite nodata cells. Valid cells remain separately reported; nodata is unknown, not an absence observation. |
| `not_covered` | The source's mapped/product footprint does not cover some or all of the AOI, or the provider explicitly marks it unmapped/not studied. That area is unknown, not a negative result. |
| `unavailable` | Acquisition/query failed or access is blocked for this run. Do not emit a zero metric; show that no source observation was available. |
| `pending_data` | Information is explicitly pending, proposed, or not yet effective. Report in a separate pending section; never merge it into effective conditions or treat pending absence/presence as effective status. |
| `incomplete_source` | The acquired version/sample is partial, stale, truncated, still being validated, or otherwise insufficient for a complete AOI conclusion. State the known reason and extent if available. |
| `geometry_quarantined` | A relevant source record was retained raw but withheld from accepted staging because its geometry failed the approved QA policy. Do not count it as absent and do not calculate a definitive overlap from its invalid shape. Expose its source ID and QA reason; affected location/area is unknown unless independently established. |
| `not_assessed` | No valid source-specific calculation was attempted. Do not display an empty value as zero. |

A numeric metric must carry its valid-data/coverage denominator and observation state. Zero is valid only for a completed calculation over known applicable coverage. If coverage is partial, metrics refer only to the covered portion and state that explicitly; do not silently divide by total AOI area. If a quarantined shape may affect a query, mark the affected source result incomplete even when other accepted features were measured.

## 5. Per-source screening metric contract

Metrics below are the intended transparent MVP measures. The final values are conditional on each source's version, coverage, fields, and QA. Do not invent domain thresholds.

### FEMA NFHL

- For validated effective data: report intersecting effective flood-zone feature count and overlap area / percentage by source-defined flood-zone codes and relevant subtypes, with community, panel, database/revision, and effective-date lineage.
- Pending features and their effective dates remain a distinct `pending_data` view, not combined with effective overlap metrics.
- Preserve mapped/unmapped/not-studied status. An unmapped or unserved area is `not_covered`/`unknown`, never hazard-free. A failed provider request is `unavailable`, not zero flood area.
- No risk classification, insurance conclusion, flood elevation inference, or regulatory determination.

### PAD-US 4.1

- Report accepted intersecting protected-area feature counts and overlap area/percentage, grouped by available source-defined categories/ownership/management and public-access fields. Retain feature identifiers and release provenance.
- Distinguish per-feature overlap totals from the unique union area to avoid double-counting overlapping designations; name each measure explicitly. Do not infer legal protection beyond the source's attributes.
- Mark coverage incomplete wherever the regional package is not verified or relevant geometries are quarantined. Quarantined candidates are identified with source IDs/reasons but do not contribute accepted intersection area; do not imply their area is zero or infer their exact AOI overlap from invalid geometry.

### Annual NLCD Collection 1.2, 2025

- Report pixel counts and estimated ground area/percentage by the versioned NLCD class code/name table, plus valid-pixel and nodata/unknown area.
- Preserve collection, year, grid/CRS, cell size, nodata, request/window, and resampling metadata. Class areas use the delivered/native grid semantics and appropriate ground-area calculation; categorical values are never interpolated.
- A land-cover class is not a wetland delineation, habitat determination, or regulatory finding. Class 90 does not independently establish wetlands.

For the current bounded raster path, the explicit `nlcd_fixture_only` mode consumes only the external GeoTIFF named by the immutable job snapshot's exact `source_snapshot_id` and `source_version_id`. `screening_status=observed` means valid pixels were summarized; `screening_status=nodata` means nodata cells were encountered and the nodata count remains explicit; `uncovered` means the raster footprint does not intersect the AOI. `source_status=fixture_only` is mandatory for this representative screening path. The separate `ingest-nlcd-regional` acquisition requests the exact approved three-county window from the official WCS in EPSG:5070 at nominal 30 m, retains the provider-snapped affine transform and exact dimensions, and validates the official class domain, nodata, AOI footprint coverage, and outside-AOI pixel accounting before creating an inactive candidate. Raster coverage area is the AOI intersection with the raster footprint in EPSG:5070; valid/nodata pixel area is an estimated cell-area summary, not a parcel-scale delineation. No categorical resampling is performed, and no active regional source is implied.

The AOI-agnostic `ingest-nlcd` acquisition path uses the persisted immutable AOI revision and its geometry hash to build the same native WCS contract for any valid WGS84 Polygon/MultiPolygon. It records the selected AOI revision, exact request parameters, source collection/year, raster transform/dimensions/nodata, HTTP metadata, size, retrieval time, checksum, and inactive candidate lineage. The request is bounded by a cell ceiling and fails explicitly before HTTP when exceeded; client clipping and tiling are not implemented. The Northern Colorado command remains a regression/fixture alias, and neither path changes NLCD maturity or creates an active version.

### USGS 3DEP 1/3 arc-second

- Report elevation min/max/mean and selected distribution quantiles over valid AOI cells; report valid/nodata coverage and vertical datum/units.
- A derived slope summary may report min/median/mean/quantiles in degrees using a declared neighborhood algorithm (proposed 3×3 Horn derivative on a metric grid), grid resolution, edge/nodata handling, and processing version. Do not apply an undocumented slope threshold or terrain-suitability label.
- Record tile identifiers, publication/modified dates, checksums, CRS/datum, clipping/window and resampling. Regional tile inventory estimates must be labeled estimates until polygon-intersecting tiles are enumerated.

For the current bounded 3DEP path, the explicit `3dep_fixture_only` mode consumes only the external DEM named by the immutable job snapshot's exact `source_snapshot_id` and `source_version_id`. `screening_status=observed` means valid elevation cells were summarized; `nodata` preserves nodata-cell counts and any valid-cell metrics; `uncovered` means the DEM footprint does not intersect the AOI. Elevation values are reported in the raster's declared units and datum when present, otherwise those fields remain null with a warning; no conversion, slope, aspect, flood, landslide, or suitability interpretation is added. A single meaningful raster-footprint feature may be exported for a covered result; pixel geometries are never fabricated.

The AOI-agnostic `ingest-3dep` acquisition path uses the persisted immutable AOI revision to query the official TNM Access products endpoint with a WGS84 bounding box. It records an explicit deterministic plan before downloading, selects one official dated 1/3-arc-second GeoTIFF per intersecting tile, and creates a separate inactive candidate/run/version record for each tile. Each candidate retains the tile identifier, product/release metadata, request parameters, response metadata, checksum, AOI revision and geometry hash, native raster metadata, and footprint coverage. The path validates the native EPSG:4269 geographic grid at 1/3 arc-second resolution with nodata `-999999`; outside-AOI, nodata, and uncovered areas remain unknown. Bounded tile and inventory limits fail explicitly, and no clipping, resampling, mosaicking, substitution, promotion, or terrain-derived interpretation is performed. This acquisition path does not change the `3dep_fixture_only` screening mode or the source maturity label.

### Bounded unified fixture workflow

The explicit `screen-fixtures` mode loads one validated immutable Census AOI revision and snapshots exactly five environmental source IDs in this order: `ssurgo`, `annual_nlcd`, `3dep`, `padus`, and `fema_nfhl`. It runs only the existing fixture-only SSURGO, NLCD, and 3DEP processors. PAD-US and FEMA are retained as status-only results: PAD-US remains `conditionally_validated` with `snapshot_status=quarantined`, and FEMA remains `access_blocked` with `snapshot_status=blocked`. No candidate or newer source version is substituted.

The lifecycle `job_status` may be `completed` even when individual sources are unavailable, incomplete, quarantined, or blocked; `overall_status` then reports `partial`, `product_status` reports `fixture_only`, and `job_outcome` plus `source_status_matrix` list successful, blocked, quarantined, incomplete, and unavailable sources. This separates execution completion from evidence completeness. A source failure does not erase other source results. The matrix carries each source's snapshot/version IDs, maturity, coverage, observation, availability, product/attempt status, checksum/byte size where available, and reason.

### NRCS SSURGO

- Report intersecting map-unit identifiers/names and mapped map-unit overlap area; summarize component-level hydric-rating values (`Yes`, `No`, `Unranked/NULL`) with `mukey`, `cokey`, and `comppct_r` lineage.
- If an area-weighted component-share summary is used, label it explicitly as a generalized map-unit/component estimate; component shares are not spatially delineated within each map unit. Do not label the estimate “wetland area” or use it to assert wetland presence/absence.
- Preserve survey-area symbols, release/revision metadata, map-unit/component joins, scale limitations, and unknown/unranked values. Hydric-soil indicators are soil information only, not a wetland inventory or regulatory wetland determination.

For the current bounded PostGIS path, `source_status=fixture_only` is mandatory. `screening_status=observed` means source hydric attributes are present in intersecting component records; `no_indicator_observed` means the fixture covers the queried area but no qualifying hydric attribute is present; `uncovered` means no promoted fixture geometry intersects the AOI. These statuses describe the fixture query only and never imply wetlands presence or absence.

## 6. Result and provenance structure

Every completed screening result is an immutable snapshot tied to a project, AOI revision, job, and pinned source set. At minimum, result metadata contains:

- result ID, project ID, AOI ID/revision, input geometry hash, submission/completion timestamps, calculation-contract version, and overall job outcome;
- screening mode when applicable, including the explicit `ssurgo_fixture_only`, `nlcd_fixture_only`, and `3dep_fixture_only` modes;
- source-level state: source ID, `validation_status`, validation scope, `coverage_status`, observation state, temporal/product status, metrics, warnings, and reasons for missing/partial metrics;
- source-specific status where applicable, including `source_status=fixture_only`, plus the exact source snapshot and source-version identifiers;
- source-version lineage: provider and dataset name, release/product year, source item/layer/feature IDs, source URL and actual acquisition URL/request parameters, retrieval time, publisher/effective/revision time when supplied, format, source CRS/grid/datum, terms/attribution URL, and source-declared completeness;
- raw snapshot/object key (outside the analytical result if stored separately), byte size, checksum, parser/adapter version, staging transform/repair operation, validation report/checks, input/output feature counts, accepted/quarantined counts, and canonical version ID when promotion has occurred;
- metric definition, value, units, numerator, denominator, covered/unknown area or cell count, method/version, and rounding/display precision.

Missing values are null with a reason and state, never silently coerced to zero. Exact provider acquisition requests and hashes must be sufficient to identify the acquired source snapshot, subject to provider stability and terms. Store pending/effective FEMA product provenance as separate source-version records.

Milestones 2B.2–2B.3 persist a local metadata subset of this lineage in an external-directory SQLite catalog: ingestion runs/retries, acquisition attempts, checksum/release source versions, candidate artifact paths, candidate validation/coverage/error records, promotion decisions, a per-source active-version pointer, and immutable per-job source snapshots. Candidate acquisition is distinct from activation; failed or incomplete candidates remain queryable and cannot promote. Job creation resolves the active pointer for every requested source before processing. Retries reuse those snapshot rows; a new job is required for a fresh source snapshot. Milestone 2B.5 separately stores a representative SSURGO candidate and fixture-only canonical rows in PostGIS using the same explicit snapshot/version identifiers; this is not an active source version or proof of regional coverage.

Generic Annual NLCD and 3DEP candidates may be promoted only for the exact
project/AOI revision that acquired and validated them. The promotion decision
must match the persisted AOI geometry hash and source-version checksum/size,
the acquisition run lineage, complete AOI footprint, native raster contract,
and zero disqualifying AOI nodata or quarantined observations. These sources
use an AOI-scoped active pointer; a later promotion for the same AOI does not
change an existing job snapshot, and an active pointer cannot be resolved for
a different AOI revision. Incomplete, unavailable, failed, nodata-containing,
or otherwise ineligible candidates remain inactive with explicit reasons.

The generic `screen-active` workflow accepts one or both of `nlcd` and `3dep`
for a persisted project and immutable AOI revision. It resolves only the
matching AOI-scoped active pointer, persists the complete source snapshot
before processing, and reads the promoted artifact named by that snapshot.
Missing, unavailable, incomplete, or rejected active state remains an explicit
source result; no legacy global pointer, fixture path, raw acquisition
candidate, or newer version is substituted. NLCD reports valid/nodata pixels,
class counts/percentages, coverage, native raster metadata, and source year.
3DEP reports valid/nodata cells, elevation summaries, coverage, native raster
metadata, and declared units/datum where available. Retry reuses the same
immutable snapshots and a later promotion affects only a newly created job.

## 7. Asynchronous job states and failure semantics

The target request path validates input and references, pins AOI/source versions, creates a job, and returns promptly. The Milestone 2B CLI currently creates a file-backed job and invokes the local worker synchronously (job-oriented, not a separate asynchronous queue service). It transitions `queued → processing → completed` or `queued/processing → failed`.

- `completed` means a valid result snapshot was persisted. It may contain source-level `unavailable`, `incomplete_source`, `pending_data`, or `geometry_quarantined` outcomes and warnings; these do not by themselves erase successful metrics from other sources.
- `failed` means an execution/system failure prevented a valid result snapshot from being committed. Record a safe actionable error and preserve per-source attempt diagnostics.
- Per-source acquisition/processing failures are isolated where possible; they do not silently invalidate successful independent source calculations.
- Retry attempts are idempotent against the same AOI revision and pinned source version set. A retry must not overwrite a prior completed result; a new source snapshot requires a new screening run/version reference.
- Job status exposes queued/processing/completed/failed, timestamps, retry/attempt information, and source-level outcomes. Cancellation and user-configurable retry controls are not part of this contract yet.

## 8. Exports and user presentation

- Minimum exports remain CSV summary and GeoJSON spatial findings. An export carries project/AOI identity, source/version and retrieval dates, metric definitions/units, coverage and observation states, source-specific status, warnings, and preliminary-use limitations. NLCD and 3DEP raster metrics and raster metadata are included in JSON and CSV; 3DEP may include one source-footprint feature, but no pixel geometries are fabricated for GeoJSON. The bounded unified fixture export additionally carries the nested per-source result structure and source-status matrix in JSON, repeated matrix metadata in one-row-per-source CSV, and GeoJSON metadata.
- GeoJSON includes the AOI and only valid source geometries produced by the run. The current slice exports clipped SSURGO map-unit polygons, not component hydric ratings as spatially delineated features. Raster sources are summarized, not emitted as raster files. Quarantined original geometries are not exported as accepted findings. Include a separate QA/quarantine listing or explicit identifiers/reasons when an acquired source result includes per-AOI quarantines; a prior sample quarantine does not imply that the current AOI is affected.
- Missing/unavailable/pending/incomplete states must remain explicit in CSV and JSON; do not omit a source row or serialize unknown as numeric zero.
- GeoPackage and PDF remain optional product decisions and are not implemented here. Exports obey source redistribution terms and preserve attribution.

## 9. Preliminary-screening notice

Every result view and export must state in plain language that this is preliminary screening based on named dataset versions and dates. Data may be incomplete, generalized, delayed, unavailable, or unsuitable for parcel-scale conclusions. Absence of a mapped feature is not proof of absence on the ground. The result is not a wetland delineation, jurisdictional determination, FEMA flood determination, permit decision, or substitute for agency consultation and qualified professional review. SSURGO hydric indicators are not wetlands mapping. No composite suitability score or regulatory threshold is produced.

## 10. Source-specific adapter contracts (design only)

All adapters are project-owned code. Initial automated adapters now exist for Census TIGER/Line, Annual NLCD, 3DEP, and SSURGO; they remain a local prototype, not production-ready or regional approval. The SSURGO PostGIS fixture loader consumes an externally retained validation artifact only for the bounded fixture path; `ingest-ssurgo` separately discovers current survey areas through official SDA and acquires official WSS packages as inactive, package-validation-only candidates. PAD-US and FEMA have no acquisition adapter in this slice. Acquisition must be automated from official provider services/packages; external artifacts are fixtures only, not a permanent manual-download input path.

### Common adapter boundary

Each adapter must expose the equivalent of:

1. **Discover/describe:** enumerate candidate release/version, URL/endpoint, temporal/effective status, format, CRS/grid, schema, license/attribution, and provider metadata.
2. **Acquire:** perform bounded automatic requests/downloads with timeouts, safe retries, pagination/windowing, stable request capture, and explicit HTTP/provider error classification.
3. **Preserve raw:** store exact response/package bytes and relevant sidecars/metadata immutably before parsing; compute SHA-256 and size; never overwrite a prior raw version.
4. **Parse/normalize:** produce staging records while preserving source IDs/attributes; record CRS transforms, clip/window, nodata, field maps, and repair operations.
5. **Validate:** return machine-readable checks, scope, extents/coverage, counts, geometry/raster checks, version/terms evidence, and `validation_status`; separate feature quarantine from source-version status.
6. **Promote candidate:** only the coordinator may atomically activate a candidate after required gates pass. A failed, access-blocked, or conditionally validated candidate cannot silently replace the last validated version. Lack of coverage remains unknown.

An adapter reports `access_blocked` for provider access failure, `not_acquired` when not attempted, `failed` when acquired data fail mandatory checks, `conditionally_validated` when an explicitly limited candidate remains usable only with visible conditions, and `validated` only for its recorded validation scope. Network success alone is never a validation pass.

### Selected-source acquisition contracts

| Source | Automated acquisition and staging contract | Required source-specific gates / limitations |
| --- | --- | --- |
| FEMA NFHL | Query/download official NFHL metadata and effective products; acquire pending products separately; capture per-community and per-panel records and dates. Never rely on a user manually downloading files. | Validate schema/CRS, jurisdiction and panel coverage, effective date and status. Keep pending/effective distinct. Unknown/unmapped/unavailable areas stay unknown. Current state is `access_blocked`; no production adapter is proven. |
| PAD-US 4.1 | Prefer the official complete state geodatabase or a complete authorized regional package; version the package and all included feature classes. If official service extraction is used later, prove it contains every required layer/feature and is complete for the region; do not treat the currently observed Fee-only service as the whole package. | Preserve raw geometry/attributes. Run deterministic `make_valid` only in staging; enforce nonempty/valid/polygonal output, unchanged attributes, absolute area delta ≤0.1% in EPSG:5070, and no unexpected topology/component-count change. Quarantine every failure visibly. Current status is `conditionally_validated`; full regional coverage is unverified. |
| Annual NLCD C1.2 2025 | Implemented: the existing fixture adapter uses WCS 1.0.0 GetCoverage for the advertised offering and 2025 time position; `ingest-nlcd` builds a bounded request from any persisted AOI revision; `ingest-nlcd-regional` remains the exact Northern Colorado regression window. | Parse and validate the one-band `uint8` GeoTIFF, EPSG:5070, approximately 30 m regular transform, nodata 250, dimensions, official class domain, AOI footprint/coverage, valid/nodata pixels and outside-AOI accounting. Record exact request/final URL, time, transform, dimensions, HTTP metadata, bytes, checksum and catalog lineage. Candidates remain inactive and validation-only; no national bundle, PostGIS pixel table, active version, refresh scheduler, clipping/tiling, or production claim exists. |
| USGS 3DEP 1/3 arc-second | Implemented prototype: the existing ImageServer `exportImage` AOI window remains the fixture/smoke path; `ingest-3dep` adds official TNM Access inventory planning and independent native tile acquisition for any persisted AOI. | Validate TIFF, native EPSG:4269 CRS, 1/3-arc-second grid, band, dimensions, datatype, transform, nodata, footprint and cells; preserve tile/release/request/checksum/AOI provenance. Bounded tile and inventory limits reject excessive requests. No clipping, resampling, mosaicking, promotion, terrain derivation, or full-regional production claim is made. |
| NRCS SSURGO | Implemented prototypes: the official SDA Post REST `GetClippedMapunits` query for the existing fixture-only screening path, and generic `ingest-ssurgo` survey-area discovery plus official WSS ZIP acquisition for persisted AOIs. The generic path persists a deterministic bounded plan and inactive candidates. | For query screening, verify required headers/values, valid polygonal geometry, CRS, and coverage. For package acquisition, validate official release metadata, URL/HTTP/checksum/size provenance, ZIP CRC, and expected spatial/tabular package structure. No generic package is staged, repaired, clipped, coverage-measured, promoted, or used for screening in this slice. Hydric attributes are soil indicators, never wetlands mapping/determination. |

## 11. Approval boundary and remaining validation

Milestone 2A defines the contract under explicit source-maturity states; the owner separately authorized a controlled Milestone 2B implementation before final source approval. That authorization does **not** close Milestone 1 or allow the implementation to imply complete source coverage. Final Milestone 1 approval remains open for:

1. **PAD-US 4.1:** acquire the complete official regional package, enumerate all features intersecting the unchanged approved boundary, apply the already approved repair policy, and report actual regional accepted/quarantined counts and coverage implications.
2. **FEMA NFHL:** establish an official technical access path and validate county/community coverage, effective/pending feature samples, schema, CRS, panels, and dates.

NLCD now has one measured regional acquisition candidate, but source maturity remains at the documented representative/fixture validation scope and the candidate is not active. 3DEP and SSURGO remain at their documented representative validation scopes; their incomplete regional sizing/coverage details must remain visible in source and per-AOI status. No source is substituted or removed by this contract.

### AOI ingestion orchestration contract

`ingest-aoi` is a bounded acquisition command, not a screening or promotion operation. It accepts a persisted immutable AOI revision and a selected subset of `nlcd`, `3dep`, and `ssurgo`. Before any provider request it writes a deterministic plan containing the AOI geometry hash, source order, adapter, official planning endpoint, per-source limits, and total byte limit, then creates one parent control-plane run. Each selected source executes through its existing adapter and retains independent child attempts/candidates. A source failure, checksum mismatch, unavailable endpoint, rejected limit, or incomplete coverage is preserved in the parent summary and cannot erase another source's success.

The parent summary reports planned/acquired artifact counts, measured bytes, child run and candidate identifiers, validation statuses, checksums/provenance, warnings, and unknown coverage. `--dry-run` persists only planning metadata and performs no network acquisition. A retry references the same parent plan and immutable AOI geometry hash, selects only failed/incomplete sources, preserves previous attempts/candidates, and is idempotent for the same parent/source retry request. All candidates remain inactive and unpromoted. This contract does not acquire FEMA or PAD-US, create a composite result, alter screening metrics, or interpret missing coverage as absence of a constraint.
