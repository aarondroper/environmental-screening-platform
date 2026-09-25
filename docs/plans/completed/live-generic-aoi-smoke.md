# Live generic AOI NLCD and 3DEP smoke

## Objective

Run both AOI-agnostic acquisition commands against one small non-Northern
Colorado WGS84 AOI and record measured provenance, validation, and inactive
candidate results outside Git.

## Outcome

Completed on 2026-09-25 using a deterministic Washington, DC-area Polygon
(`-77.041,38.900` to `-77.039,38.902`) under the generic AOI policy. The
persisted AOI geometry hash is
`216677406ea7cb6817db15c205ae9c4c952e425985dddf2149219eece6506fbc`.

- Generic NLCD reached the official WCS. Its first very-small-window response
  was retained as a failed candidate because its transform was approximately
  28.31 m × 30.59 m. A minimum 20 km bounded provider window was added for
  small generic AOIs; a regression test covers request padding. The rerun
  passed with EPSG:5070, approximately 30 m cells, nodata 250, observed
  classes 22/23/24, complete AOI footprint coverage, 863,154 bytes, and
  SHA-256 `6bc353d127a2a7d5a66c8152cfea099f271275e172d0924c18470fc0d93a6c4e`.
- Generic 3DEP queried TNM Access, selected one official `n39w078` product,
  and acquired/validated the 500,034,664-byte native EPSG:4269,
  1/3-arc-second GeoTIFF with nodata `-999999` and complete AOI footprint
  coverage. Its SHA-256 is
  `8c67738d7c829e9f408958b61fb2526df94a645d89805389c248dac84a9f3d18`.
- The external manifest records both successful artifacts, the retained NLCD
  failure, the 3DEP plan, URLs, request parameters, sizes, retrieval metadata,
  checksums, and catalog lineage. Both source active-version pointers remain
  empty. Generated records contain no Northern Colorado fixture identifiers or
  metadata.
- Full tests passed with optional external/PostGIS checks reported separately;
  Ruff lint, mypy, CLI help, documentation path checks, and `git diff --check`
  passed. Repository-wide formatting still reports five pre-existing unrelated
  files.

## Limits

This is one live AOI smoke only. It does not establish regional completeness,
source maturity, production readiness, activation, mosaicking, SSURGO
generalization, or screening behavior.
