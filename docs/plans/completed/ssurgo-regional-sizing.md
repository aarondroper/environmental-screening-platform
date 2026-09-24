# Regional SSURGO survey-area and package sizing

## Objective

Validate the official NRCS SSURGO survey areas intersecting the unchanged
2025 Boulder/Larimer/Weld boundary and document package/release size evidence
without acquiring full packages or changing application behavior.

## Outcome

Completed on 2026-09-24 at provider-metadata level.

- The exact official 2025 Census union was rechecked as a valid three-component
  MultiPolygon in EPSG:4269, with an EPSG:5070 area of approximately
  7,391.206 square miles.
- The official NRCS SDA intersection function returned all 19 intersecting
  survey symbols. Current catalog release metadata and grouped map-unit counts
  were confirmed.
- Official Web Soil Survey cache URLs were generated from each area symbol,
  current release date, and template suffix. All 19 guarded GET probes returned
  HTTP 200, `application/.zip`, and provider-reported Content-Length values.
- The provider-reported compressed total is 394,959,419 bytes (376.663 MiB).
  No package body was downloaded, so no package checksum or archive-integrity
  claim is made.
- External sizing evidence is recorded at
  `/home/aarondroper/projects/environmental-screening-platform-data/ssurgo/ssurgo_regional_sizing_2026-09-24.json`
  and in the external manifest.
- SSURGO remains representative/fixture-validated and not production-ready.
  Full archive integrity, extracted volume, county-clipped canonical coverage,
  and complete regional source approval remain open.

## Validation

- External manifest JSON parsed successfully.
- The sizing record JSON parsed successfully.
- The approved boundary and existing raw artifacts remained outside Git.
- The PostGIS container was inspected read-only; no database command or write
  was performed by this task.
- Documentation/link and `git diff --check` validation is recorded at handoff.
