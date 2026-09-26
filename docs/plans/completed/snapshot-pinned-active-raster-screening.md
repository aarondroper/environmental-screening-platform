# Snapshot-pinned active NLCD/3DEP screening

## Outcome

Implemented `screen-active` for one or both generic Annual NLCD and 3DEP
sources. The workflow requires exact AOI-scoped active pointers, persists
immutable source snapshots before processing, reads only promoted artifact
paths, and preserves explicit unknown/incomplete/unavailable states.

The existing raster processors now support an explicit active-AOI result
status and window large native rasters to the AOI while retaining full source
metadata. Exports include project/AOI geometry-hash, snapshot, active/source
version, candidate/run, checksum, and raster provenance. Fixture commands and
Northern Colorado aliases remain unchanged.

## Validation

- Focused active-screening tests passed, including source isolation, missing
  and unpromoted states, retry snapshot reuse, later-promotion isolation, and
  JSON/CSV/GeoJSON lineage.
- The retained Washington, DC NLCD/3DEP artifacts passed the opt-in active
  screening smoke without redownload or provider access.
- Full quality gates were run; known repository-wide formatter failures remain
  unchanged and are reported in the handoff.
