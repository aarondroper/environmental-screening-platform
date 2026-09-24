# SSURGO regional discrepancy audit

## Outcome

Completed on 2026-09-24 against the 19 acquired SSURGO packages. The audit
produced external per-package and aggregate reports and updated the external
manifest without accessing PostGIS or changing raw packages, catalog state,
source maturity, or screening behavior.

- Ten original invalid `soilmu_a` polygons were diagnosed in EPSG:5070.
- Diagnostic-only in-memory `make_valid` results were valid, nonempty, and
  polygonal, within the 0.1% area tolerance, and attribute-joinable. No
  repaired geometry was written or accepted.
- Seventeen package identities were confirmed. `WY621` and `WY721` were
  classified as harmless naming variations because the package, official
  lookup/SDA release, URLs, checksums, and manifest identity agree; only the
  sizing names include “Area”.
- All 19 candidates remain inactive/incomplete. The aggregate report is under
  `/home/aarondroper/projects/environmental-screening-platform-data/ssurgo/regional-discrepancy-audit/`.

## Boundaries respected

The task did not download, modify, repair, drop, clip, quarantine, stage, or
promote any record and did not begin regional canonical coverage work. Owner
direction remains required before any derived geometry is used for staging.
