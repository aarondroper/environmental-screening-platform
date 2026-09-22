# Screening workflow and product contract — Milestone 2A

**Status:** Design contract only; no application behavior, schema, API, adapter, or export is implemented. This contract advances product design under the owner's controlled 2A authorization; it does not close Milestone 1 or approve the final source set.

## 1. Product boundary

The platform provides preliminary, source-attributed environmental and physical screening for proposed project areas in the owner-approved Boulder, Larimer, and Weld County geography. It reports what selected dataset versions show, where they cover the AOI, and where they do not support a conclusion. It is not an environmental assessment, wetland delineation, flood determination, permit decision, legal opinion, engineering design, or regulatory clearance.

There is no composite risk/constraint score, pass/fail suitability verdict, invented regulatory threshold, or implication that missing, unavailable, pending, incomplete, or quarantined information means no constraint exists. Metrics remain separate by source and meaning.

## 2. Projects, AOIs, and screening runs

- A project is a durable named workspace for one consulting/planning case. Project metadata is descriptive, not an analytical input.
- A project may retain named AOIs. The primary MVP interaction is drawing a Polygon or MultiPolygon on the map; the API contract may accept equivalent GeoJSON geometry. The input CRS is WGS 84 longitude/latitude (EPSG:4326 / RFC 7946 coordinates).
- Reject empty, invalid, non-polygonal, or out-of-bound AOIs with actionable validation errors. Do not silently repair or clip user AOIs. The AOI must be contained by the complete approved 2025 three-county union, including its detached union components. Preserve holes and multipart structure.
- Editing an AOI creates a new immutable AOI revision. A screening run binds to exactly one AOI revision; changing the project AOI later never mutates an existing result.
- A screening request records its submission time, AOI revision, requested source set, and source-version snapshot. It is asynchronous; the request returns a job identifier rather than waiting for all spatial work.
- A run uses an internally consistent, pinned set of source versions. It must not silently combine an active version with a newer, partly acquired candidate. If a source has no usable version, retain its per-source unavailable/unknown outcome in the result instead of fabricating a zero.

Areas and area fractions are calculated in a suitable equal-area CRS (EPSG:5070 for this geography) and state their units. Distances and lengths, if later added, must likewise declare CRS/measurement semantics. Raster calculations preserve source grid, nodata, and resampling provenance; categorical NLCD must not use interpolating resampling.

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
| Annual NLCD Collection 1.2, 2025 | `validated` | Representative WCS GeoTIFF sample passed; complete regional source-grid coverage/volume is not established. |
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

### USGS 3DEP 1/3 arc-second

- Report elevation min/max/mean and selected distribution quantiles over valid AOI cells; report valid/nodata coverage and vertical datum/units.
- A derived slope summary may report min/median/mean/quantiles in degrees using a declared neighborhood algorithm (proposed 3×3 Horn derivative on a metric grid), grid resolution, edge/nodata handling, and processing version. Do not apply an undocumented slope threshold or terrain-suitability label.
- Record tile identifiers, publication/modified dates, checksums, CRS/datum, clipping/window and resampling. Regional tile inventory estimates must be labeled estimates until polygon-intersecting tiles are enumerated.

### NRCS SSURGO

- Report intersecting map-unit identifiers/names and mapped map-unit overlap area; summarize component-level hydric-rating values (`Yes`, `No`, `Unranked/NULL`) with `mukey`, `cokey`, and `comppct_r` lineage.
- If an area-weighted component-share summary is used, label it explicitly as a generalized map-unit/component estimate; component shares are not spatially delineated within each map unit. Do not label the estimate “wetland area” or use it to assert wetland presence/absence.
- Preserve survey-area symbols, release/revision metadata, map-unit/component joins, scale limitations, and unknown/unranked values. Hydric-soil indicators are soil information only, not a wetland inventory or regulatory wetland determination.

## 6. Result and provenance structure

Every completed screening result is an immutable snapshot tied to a project, AOI revision, job, and pinned source set. At minimum, result metadata contains:

- result ID, project ID, AOI ID/revision, input geometry hash, submission/completion timestamps, calculation-contract version, and overall job outcome;
- source-level state: source ID, `validation_status`, validation scope, `coverage_status`, observation state, temporal/product status, metrics, warnings, and reasons for missing/partial metrics;
- source-version lineage: provider and dataset name, release/product year, source item/layer/feature IDs, source URL and actual acquisition URL/request parameters, retrieval time, publisher/effective/revision time when supplied, format, source CRS/grid/datum, terms/attribution URL, and source-declared completeness;
- raw snapshot/object key (outside the analytical result if stored separately), byte size, checksum, parser/adapter version, staging transform/repair operation, validation report/checks, input/output feature counts, accepted/quarantined counts, and canonical version ID when promotion has occurred;
- metric definition, value, units, numerator, denominator, covered/unknown area or cell count, method/version, and rounding/display precision.

Missing values are null with a reason and state, never silently coerced to zero. Exact provider acquisition requests and hashes must be sufficient to identify the acquired source snapshot, subject to provider stability and terms. Store pending/effective FEMA product provenance as separate source-version records.

## 7. Asynchronous job states and failure semantics

The request path validates authorization-independent input shape and project/AOI references, pins AOI/source versions, creates a job, and returns promptly. The worker transitions `queued → processing → completed` or `queued/processing → failed`.

- `completed` means a valid result snapshot was persisted. It may contain source-level `unavailable`, `incomplete_source`, `pending_data`, or `geometry_quarantined` outcomes and warnings; these do not by themselves erase successful metrics from other sources.
- `failed` means an execution/system failure prevented a valid result snapshot from being committed. Record a safe actionable error and preserve per-source attempt diagnostics.
- Per-source acquisition/processing failures are isolated where possible; they do not silently invalidate successful independent source calculations.
- Retry attempts are idempotent against the same AOI revision and pinned source version set. A retry must not overwrite a prior completed result; a new source snapshot requires a new screening run/version reference.
- Job status exposes queued/processing/completed/failed, timestamps, retry/attempt information, and source-level outcomes. Cancellation and user-configurable retry controls are not part of this contract yet.

## 8. Exports and user presentation

- Minimum exports remain CSV summary and GeoJSON spatial findings. An export carries project/AOI identity, source/version and retrieval dates, metric definitions/units, coverage and observation states, warnings, and preliminary-use limitations.
- GeoJSON includes only geometries valid for output; quarantined original geometries are not exported as accepted findings. Include a separate QA/quarantine listing or explicit identifiers/reasons when the source result includes quarantines.
- Missing/unavailable/pending/incomplete states must remain explicit in CSV and JSON; do not omit a source row or serialize unknown as numeric zero.
- GeoPackage and PDF remain optional product decisions and are not implemented here. Exports obey source redistribution terms and preserve attribution.

## 9. Preliminary-screening notice

Every result view and export must state in plain language that this is preliminary screening based on named dataset versions and dates. Data may be incomplete, generalized, delayed, unavailable, or unsuitable for parcel-scale conclusions. Absence of a mapped feature is not proof of absence on the ground. The result is not a wetland delineation, jurisdictional determination, FEMA flood determination, permit decision, or substitute for agency consultation and qualified professional review. SSURGO hydric indicators are not wetlands mapping. No composite suitability score or regulatory threshold is produced.

## 10. Source-specific adapter contracts (design only)

All adapters are project-owned code to be implemented later; this document does not assert production readiness. Acquisition must be automated from official provider services/packages in the eventual application. The external artifacts and manifest currently available are fixtures for repeatable acquisition/validation tests only, not a permanent manual-download input path.

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
| Annual NLCD C1.2 2025 | Automatically request official year-specific regional WCS/tile windows or official tile assets; capture collection/year, exact grid and request bounds. | Verify native grid/CRS, categorical class domains, nodata, coverage, and reproducible window alignment; regional clipping must not fetch a national historical bundle. Current representative service sample does not prove full regional coverage. |
| USGS 3DEP 1/3 arc-second | Use the official TNM inventory to derive exact intersecting tiles and immutable item URLs; acquire only the required dated tiles/windows and clip/window in staging. | Verify tile IDs/dates/checksums, CRS, horizontal/vertical datum, units, resolution, nodata and coverage. Do not treat the current bounding-box byte sum as exact polygon-intersection inventory. |
| NRCS SSURGO | Automatically query official SDA or obtain official survey-area packages for intersecting survey areas; preserve each survey-area release and related mapunit/component tables/geometry. | Verify per-SSA revisions, `mukey`/`cokey` relationships, `hydricrating`, `hydricon`, `comppct_r`, null population, CRS/scale and AOI coverage. Hydric attributes remain soil indicators, never wetlands mapping/determination. |

## 11. Approval boundary and remaining validation

Milestone 2A defines the contract under explicit source-maturity states; it does **not** constitute final source approval or permit application implementation. Final Milestone 1 approval remains open for:

1. **PAD-US 4.1:** acquire the complete official regional package, enumerate all features intersecting the unchanged approved boundary, apply the already approved repair policy, and report actual regional accepted/quarantined counts and coverage implications.
2. **FEMA NFHL:** establish an official technical access path and validate county/community coverage, effective/pending feature samples, schema, CRS, panels, and dates.

NLCD, 3DEP, and SSURGO remain at their documented representative validation scopes; their incomplete regional sizing/coverage details must remain visible in source and per-AOI status. No source is substituted or removed by this contract.
