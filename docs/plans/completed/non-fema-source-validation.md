# Non-FEMA source validation

## Objective

Acquire and validate representative official artifacts for PAD-US 4.1, Annual NLCD Collection 1.2 (2025), 3DEP 1/3 arc-second DEM, and SSURGO. Keep raw artifacts and manifest outside Git. Do not revisit the approved three-county boundary or source choices.

## Work completed

1. Inspected the pre-existing diff, source documentation, and external manifest; retained all earlier boundary and FEMA evidence.
2. Acquired official PAD-US service metadata and a five-feature Colorado GeoJSON response; acquired a 2025 NLCD WCS capabilities document and two small 2025 GeoTIFF clips; queried the official TNM API and downloaded one 3DEP tile; queried official NRCS SDA for the exact regional survey-area list, area-version metadata, a small component/hydric table, and map-unit polygon WKT. Also acquired the official nationwide soil-availability index ZIP (metadata only; not a soil dataset).
3. Recorded URLs, versions, retrieval date, paths, byte sizes, checksums, license records, and measured validation findings in the external `manifest.json`.
4. Updated `SOURCE_FEASIBILITY.md`, `PROJECT_STATE.md`, `ARCHITECTURE.md`, and `BACKLOG.md`. `DECISIONS.md` required no change: the owner-approved geography/source set and NWI exclusion were unchanged, and no new product decision was authorized.
5. Confirmed raw artifacts are outside the repository; no application code, schema, adapter, dependency, or deployment work was added.

## Outcome and stop condition

- The three-county 2025 Census boundary remains validated and unchanged.
- NLCD 2025 WCS sample, one 3DEP tile, and SSURGO regional/sample queries passed bounded file/service checks. NLCD native-grid/full-region size, exact polygon-intersecting 3DEP tile set, and full SSURGO survey-package bytes remain unmeasured.
- PAD-US official access/schema/sample query worked, but 3 of 5 returned geometries have ring self-intersections. Canonical handling requires owner approval: audited staging repair with raw preservation, or quarantine/rejection with possible coverage gaps. Recommendation and consequences are in `SOURCE_FEASIBILITY.md`.
- FEMA NFHL remains exactly: “Selected source; provider access blocked; technical suitability and effective/pending sample validation incomplete.”
- Milestone 1 is partially validated, not complete. Milestone 2 was not begun. No source was substituted and no geography was narrowed.

## Validation

Verified JSON/GeoJSON parsing; raster readability and metadata with Rasterio; PAD-US and SSURGO sample feature/polygon properties with Shapely; SSURGO attribute keys/domains and area inventory; 3DEP GeoTIFF and API metadata; SSURGO availability ZIP CRC. Final documentation-path, manifest, implementation-scope, and Git diff checks passed on 2026-09-22.
