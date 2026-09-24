# Regional SSURGO package parsing and validation

## Objective

Parse and validate only the 19 already acquired official SSURGO survey-area
ZIP candidates for the unchanged 2025 Boulder/Larimer/Weld AOI. Preserve raw
packages and source records, produce per-package and aggregate QA evidence,
and leave all candidates inactive/incomplete.

## Outcome

Completed 2026-09-24. The observed official package format was parsed without
modifying source bytes. All 19 candidates intersected the approved AOI; 13
packages passed and 6 failed. Failures comprise 10 original invalid
`soilmu_a` polygons in `CO075`, `CO618`, `CO644`, and `CO646`, plus package
name discrepancies for `WY621` and `WY721`. Aggregate counts were 123,196
`soilmu_a` records, 1,878 map-unit rows, 7,404 component rows, 7,372
non-empty `hydricrating` values, and 382 non-empty `hydricon` values. Raw
packages and all candidates remain unchanged and inactive/incomplete. QA was
written outside Git and the external manifest now points to the reports.

No regional canonical staging or promotion was attempted. Follow-up work
requires owner direction on the original invalid geometries and survey-name
discrepancies; no repair or substitution policy was inferred.
