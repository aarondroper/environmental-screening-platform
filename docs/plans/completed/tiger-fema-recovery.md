# TIGER/Line and FEMA source-validation recovery

## Objective

Recover exact official 2025 Census county geometries and retry approved FEMA NFHL access without changing the owner-selected geography/source set.

## Outcome — boundary validated; FEMA blocked; milestone remains open

- Preserved the earlier uncommitted documentation diff and TIGERweb sample.
- Downloaded the official Census 2025 TIGER/Line national county archive because the official directory did not offer a smaller state/county ZIP. The 83,989,800-byte archive passed ZIP CRC testing and remains outside Git. Extracted only GEOIDs `08013`, `08069`, and `08123` into a selected shapefile subset, with source projection and metadata.
- Verified 2025 release metadata, GEOID/name pairs, NAD83/EPSG:4269 CRS, readability, nonempty/valid geometries, expected multipart features, valid union, shared boundaries, no county-area overlap, bounding box, and area. The union is a three-component MultiPolygon: one connected main county body of about 7,390.088 sq mi and two detached TIGER components of 1.026734 and 0.090830 sq mi. Total EPSG:5070 area is about 7,391.206 sq mi, consistent with Census ALAND/AWATER sums. All parts remain in the approved extent; no geometry was repaired or dropped.
- Preserved FEMA’s earlier TLS reset. Retried NFHL service metadata/metadata XML/WSDL, official GIS/WMS documentation and endpoints, the FEMA GIS ArcGIS REST directory, product download servlet, and MSC routes. HTTPS and HTTP/1.1 requests to hazards/MSC routes reset during TLS or produced no usable response. `gis.fema.gov` REST directory responded over HTTPS (HTTP 200), but its FEMA folder listed no NFHL service; an NFHL folder query returned “folder not found.” The official directory metadata JSON files and all attempt details are in the external manifest. No FEMA NFHL effective or pending feature sample, metadata, jurisdiction, panel, or effective date was retrieved.
- Because FEMA remained access-blocked, the required stop rule was applied. PAD-US 4.1, Annual NLCD 2025, 3DEP, and SSURGO samples were not attempted; no MVP source is sample-validated and Milestone 2 was not begun.
- Updated `SOURCE_FEASIBILITY.md`, `PROJECT_STATE.md`, `ARCHITECTURE.md`, and `BACKLOG.md`. No decision was added: no source is being replaced and no owner product decision is inferred. The earlier TIGERweb GeoJSON remains explicitly diagnostic. No application code, schemas, adapters, infrastructure, dependencies, or toolkit coupling were introduced.
- Updated external manifest: `/home/aarondroper/projects/environmental-screening-platform-data/manifest.json`. Raw files remain outside the repository.

## Handoff

The exact county boundary gate is complete with its observed three-component topology retained. Milestone 1 remains open until official FEMA effective-data metadata/features become reachable and pass validation, followed by representative validation of the other four approved MVP sources. No source substitution or geographic narrowing is authorized. Milestone 2 remains gated.
