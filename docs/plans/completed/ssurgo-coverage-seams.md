# SSURGO regional coverage and seam analysis

## Objective

Measure coverage and seam behavior for inactive candidate
`9d77a86a-bdc7-4684-b977-1081f8ed484c` using the existing 19-package
PostGIS staging result and the exact approved Boulder/Larimer/Weld AOI.

## Outcome

Completed on 2026-09-24. A read-only PostGIS analysis measured the AOI,
unioned staged coverage, uncovered residuals, package overlaps, outside-AOI
source area, and all 19 per-package contributions in EPSG:5070. It wrote
checksummed aggregate, per-package, gap, overlap, and seam reports outside
Git, recorded them in the external manifest, and persisted the validation
against the inactive candidate without changing staging rows, raw packages,
or the active-version pointer.

The measured union covered 99.999995599% of the AOI; 842.499 m² remained
uncovered. There were 43 diagnostic gap components, 9 cross-package overlap
pairs, and 30 small interior residuals that remain unknown rather than being
filled or attributed. The candidate remains incomplete/conditionally
validated/partial/not promoted. Deterministic fixture tests and the normal
repository quality gates were run.

## Non-goals preserved

- No download, source/staging geometry modification, repair, clipping,
  dissolve, promotion, source substitution, or screening behavior change.
- No interpretation of uncovered soil area as absence of an environmental
  constraint.
