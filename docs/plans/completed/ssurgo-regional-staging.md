# Regional SSURGO staging

## Outcome

Completed on 2026-09-24 using only the 19 acquired official survey-area ZIPs.
Migration `003_ssurgo_regional_staging.sql` and the `stage-ssurgo-regional`
CLI provide derived PostGIS staging with package, map-unit, component, and
feature lineage. The live run loaded 123,196 features, 1,878 map units, and
7,404 components; all 10 audited invalid polygons passed the approved repair
policy and none were quarantined.

Original geometries, attributes, raw packages, checksums, and external audit
reports were preserved. The 19 SQLite candidates remain inactive/incomplete,
the staging rows are explicitly `staging_only`, and no active SSURGO version
was created. Live tests verified provenance, quarantine retention, idempotent
reload, and transaction rollback without partial records.

## Boundaries respected

No package was redownloaded or modified. The existing fixture-only screening
path, source scope, FEMA/PAD-US states, and hydric-soil semantics were not
changed. Regional staging is not production promotion or final Milestone 1
source approval.
