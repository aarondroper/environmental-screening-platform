# Project State

## Snapshot status

Verified on 2026-09-22 after Milestone 2B's first ETL vertical slice. This checkout now contains a small Python CLI/workflow and deterministic tests. It is a local prototype, not the deployed PostGIS/API/worker/web platform described by the product brief. Source maturity labels below remain bounded to their prior validation scopes; successful small-AOI smoke runs do not constitute final Milestone 1 source approval.

## Verified repository and Git state

- Canonical root: this directory, with `AGENTS.md` and `docs/`.
- Git: local repository on `master`, baseline before this work was `c6c834d`; no remote is configured. The coherent implementation/documentation commit is recorded in the Git history. No history was rewritten and no remote or push was created.
- Raw source responses and local workspace/project/job/export records are written under an external `--data-dir`; the CLI rejects a data directory within this repository. Raw artifacts are not Git inputs.
- Toolkit was inspected as an optional reference only. No toolkit import, dependency, symlink, submodule, or modification exists.

## Implemented Milestone 2B slice

| Area | Verified behavior | Boundary / not yet implemented |
| --- | --- | --- |
| Python package and CLI | `pyproject.toml`, editable install, `screening` entry point; commands for project creation, AOI revision, screening, status, retry, and export | No web/API entry point |
| Geography | Fetches official 2025 TIGER/Line county archive over HTTPS when no cached boundary exists; validates ZIP, CRS, GEOIDs 08013/08069/08123 and exact 3-component union; retains raw response by SHA-256 | Official route is the national county ZIP (about 84 MB), then only the three records are normalized; no silent boundary narrowing |
| Projects/AOIs | External JSON records; WGS84 Polygon/MultiPolygon validation; containment by the approved complete county union; immutable revisions and input hash | No account/auth model, uploads, map UI, or database persistence |
| Jobs | File-backed `queued → processing → completed/failed`, attempt records, immutable completed result, retry of failed jobs with the same AOI revision; independent provider failures become explicit source outcomes | Job execution is job-oriented but the CLI runs the worker synchronously; no queue, concurrent worker coordination, cancellation, or durable transactional database |
| Raw acquisition/provenance | HTTPS-only bounded requests, same-host redirects, bounded retries for selected transient HTTP/network failures, content-addressed raw bytes, append-only acquisition event records with URL/request, retrieval time, release, bytes, terms URL and checksum | Does not yet implement conditional requests, broad provider pagination, archival retention policy, source catalog, or promotion transactions |
| Annual NLCD | Live smoke passed for a 2025 WCS 1.0 AOI window; categorical class counts/estimated EPSG:5070 ground area, nodata and returned grid metadata | Source maturity remains representative-sample `validated`; live regional completeness/native Albers volume unverified; 16M-cell request limit, no multi-window mosaic |
| 3DEP | Live smoke passed for an AOI-clipped official ImageServer request; elevation distribution and 3×3 Horn slope on the returned 10 m EPSG:5070 grid | Source maturity remains representative-tile `validated`; response is bilinear-resampled, not raw tile bytes; tile IDs/underlying source-tile revisions are not captured; 12M-cell limit |
| SSURGO | Live SDA Post REST query returned AOI-clipped map-unit polygons and component hydric attributes; records `mukey`, `cokey`, `comppct_r`, `hydricrating`, `hydricon`; deduplicates repeated component rows; reports polygon coverage and component indicators | Source maturity remains representative-query `validated`; no survey-area release/version catalog or complete three-county package sizing; hydric indicators are soil information, not wetlands mapping/determination |
| PAD-US / FEMA | Both remain explicit source-result rows. PAD-US: `conditionally_validated`, unknown regional coverage and prior sample quarantine counts disclosed. FEMA: exact access-blocked wording retained, unavailable/unknown this run | No live PAD-US or FEMA acquisition/adapter; no substitute sources; no claim of regional PAD coverage or FEMA effective/pending validity |
| Result and exports | JSON result with source maturity, validation scope, acquisition provenance, coverage/observation/attempt/job status and metrics; CSV includes state, provenance, metrics and limitations; GeoJSON includes AOI plus valid clipped SSURGO map-unit findings | Raster layers are summarized, not emitted as finding geometries; GeoJSON is not yet a full mapped output for PAD-US/FEMA or rasters |

### External live-smoke evidence

The small live AOI used for the end-to-end smoke was approximately 0.00948 km² near Boulder. Raw responses and generated project/job/export records remain outside Git under `/home/aarondroper/projects/environmental-screening-platform-data/milestone-2b-e2e/`.

| Pathway | Artifact/result evidence | Scope |
| --- | --- | --- |
| Census 2025 | Existing official archive checksum verified: 83,989,800 bytes, SHA-256 `9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763`; parser returned exact three GEOIDs, EPSG:4269, valid MultiPolygon, 3 components, 7,391.206 sq mi | Existing external raw artifact was used as an integration fixture to avoid a redundant national download. The automatic HTTPS acquisition path is implemented; no second network download was needed for this smoke |
| Annual NLCD | 2,194-byte GeoTIFF, SHA-256 `cbbc679daf3a162c25dd9728e2c501b20bfc4cc3914bc71c254d5244e43ceabf`; EPSG:3857 WCS grid, 3×4 uint8 cells, nodata 250, valid class cells 21/22/23 | Exact 2025 window; tiny AOI only |
| 3DEP | 66,750-byte GeoTIFF, SHA-256 `55eb009fcb4cdaa11984f2c9b3ee9979d0cce4f9bf051afcf554bad76b795cb6`; EPSG:5070, 10×12 float32 at about 9.98 m, nodata -999999 with none in AOI | One 10 m regional image-service window; not regional completeness |
| SSURGO | 1,893-byte JSON response, SHA-256 `3e8000875664a7fc5ca63e05745075bb7a24d0979535ed6e05d854139802474b`; 3 map units, 6 component rows, 100% AOI polygon coverage | One tiny SDA AOI query; returned hydric ratings were source component values, not wetland results |

The end-to-end job completed and produced JSON, CSV, and GeoJSON exports. The same run listed PAD-US as conditionally validated/incomplete and FEMA as access blocked/unavailable. This is evidence that these small requests and parsing paths executed on 2026-09-22, not evidence of production reliability, final source approval, refresh repeatability, regional completeness, or legal redistribution review.

## Selected sources and unresolved validation

Owner-approved geography remains Boulder County (08013), Larimer County (08069), and Weld County (08123). Owner-approved MVP source direction remains FEMA NFHL, PAD-US 4.1, Annual NLCD Collection 1.2 (2025), 3DEP 1/3 arc-second, and NRCS SSURGO hydric-soil information. NWI is excluded. See `SOURCE_FEASIBILITY.md` for evidence and terms.

- Census boundary validation is complete for the exact 2025 three-county union. All three components are retained.
- NLCD, 3DEP and SSURGO passed the bounded external smoke above, but the source maturity scopes remain the representative validations already documented.
- PAD-US remains `conditionally_validated`; full regional package acquisition, coverage and quarantine-gap analysis remain unresolved. The prior five-feature sample had two unchanged accepted features and three repaired candidates quarantined; their impact on this AOI is not known.
- FEMA NFHL remains **Selected source; provider access blocked; technical suitability and effective/pending sample validation incomplete.** No effective/pending or mapped/unmapped jurisdiction sample was used in this run.
- Final Milestone 1 source approval remains open for full regional PAD-US validation and FEMA official access/effective-pending validation. Milestone 2B does not approve or replace sources.

## Current development frontier

Milestone 2B's first local ETL path is implemented and smoke-tested for Census, NLCD, 3DEP, and SSURGO at the scopes above. The immediate frontier is hardening the source snapshot/version and coverage behavior and completing GIS findings/export boundaries without overstating any source. The next recommended work unit is a focused persistence/versioning slice: record source-version and validation-run entities with safe candidate promotion semantics, while keeping project/result output repeatable and source failures visible. A PostGIS/API/queue/web platform, deployment, and production source refresh remain future work.

No composite score, regulatory determination, wetland finding, FEMA flood determination, or safety/suitability conclusion is implemented or permitted. Missing, unavailable, pending, incomplete, or quarantined data are never serialized as zero/absence. The full three-county region is not narrowed.
