# Geography and source feasibility

> Historical research only. Its England recommendation and S1–S5 set were superseded by the owner’s US-based product decision on 2026-09-22. Do not treat them as the working geography/source set or as owner-approved.

## Objective

Complete the research and recommendation work for Backlog Milestone 1 without implementing ingestion or locking owner-level scope.

## Evidence used

- Repository and governance inspection, including the invalid Git baseline.
- The toolkit pattern inventory and bounded-acquisition reference, consulted without copying code or creating coupling.
- Current provider records and technical documentation for Natural England, the Environment Agency, Ordnance Survey, and UKCEH.

## Outcome

- Recommended England as the contained geography.
- Documented S1–S5 candidate sources in the then-current `docs/SOURCE_FEASIBILITY.md`, which has since been replaced by US-only research.
- Recorded provider access, formats, CRS, update/version evidence, licence/attribution constraints, acquisition shape, candidate metrics, and known limitations.
- Recommended OS Terrain 50 for the initial broad terrain layer, with Environment Agency 2m LiDAR retained as a higher-cost alternative.
- Updated project state, architecture, backlog, and AGENTS.md to point to the feasibility record.
- No ingestion code, source fixture, dependency, or toolkit implementation was added.

## Historical acceptance status

At the time, research and recommendation deliverables were complete but Milestone 1 awaited approval of England/S1–S5, the PHI licence/update issue, OS attribution terms, and terrain resolution. That pending recommendation was superseded by the US-based owner decision recorded on 2026-09-22; these are no longer current project decisions.
