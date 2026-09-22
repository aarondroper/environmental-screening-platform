# Northern Colorado geography and source validation

> Historical outcome before D014. Its NWI-provisional source direction and owner decision request have been superseded by the revised MVP direction; consult the current `docs/SOURCE_FEASIBILITY.md` and `docs/DECISIONS.md`.

## Outcome

Completed agency-record validation on 2026-09-22. Confirmed the owner-selected working boundary definition as the 2025 Census polygons for Boulder (08013), Larimer (08069), and Weld (08123), approximately 7,391 sq mi including water. The area is suitable as a contained study region; the workspace could not retrieve geometries to run a topology check or create a local boundary sample. Identified candidate product vintages/endpoints, terms evidence, access and format/CRS characteristics, update behavior, ETL patterns, and FEMA jurisdiction/effective-date caveats in `docs/SOURCE_FEASIBILITY.md`.

The five source themes remain provisional. NWI’s May 2026 Data.gov record establishes public access but supplies no licence or downstream rights statement; its source contributions include non-federal partners. No data samples were downloaded or parsed. Four other sources have strong agency-record public-use evidence, but end-to-end/sample validation remains outstanding. The workspace could not resolve the Census host for a small direct query. The NWI rights question is owner-level and blocks Milestone 2; no replacement was made.

## Validation and handoff

- Updated project state, architecture, backlog, decision record, and the AGENTS navigation pointer to distinguish approved geography, provisional themes, release-level rights status, and sample-validation state.
- No application code, schemas, adapters, dependencies, or deployment infrastructure were added. Git metadata was not changed; `git status` and `git rev-parse` continue to fail because `.git/` is invalid.
- Owner decision requested: obtain release-specific USFWS redistribution clarification, or choose between owner-approved SSURGO hydric-soil information (a different theme), a four-source initial set, or another proposed source. Do not begin Milestone 2 until this and remaining representative-sample checks are complete.
