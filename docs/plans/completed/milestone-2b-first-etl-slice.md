# Milestone 2B — first ETL vertical slice

## Objective

Implement a small project-owned, job-oriented screening pipeline that preserves raw acquisition provenance, validates/normalizes data, computes transparent per-source metrics, records unknown/failure states, and exports a documented result for Census, Annual NLCD, 3DEP, and SSURGO while keeping PAD-US/FEMA maturity visible.

## Outcome — completed 2026-09-22

- Read the project contract/governance and relevant toolkit acquisition, publication, and raster-validation patterns. Adapted only bounded HTTPS acquisition, content hashes, append-only acquisition events, atomic JSON records, and explicit raster metadata checks. No toolkit code was copied into runtime imports; toolkit was not modified.
- Added a self-contained Python 3.12 CLI/package with external file-backed projects, immutable WGS84 AOI revisions, job status/attempt/retry records, and JSON/CSV/GeoJSON exports. No API, database, queue service, deployment, or frontend was added.
- Implemented official 2025 TIGER/Line boundary parsing and automated acquisition; NLCD 2025 WCS regional windows; 3DEP ImageServer AOI windows and transparent elevation/Horn-slope summaries; NRCS SDA clipped SSURGO mapunit geometry and component hydric indicators.
- Kept raw response bytes outside Git, content-addressed by SHA-256, with request/version/terms metadata and size limits. Unknown, unavailable, pending, incomplete, and quarantined states remain distinct; only fully covered, fully validated scope may be classified as no constraint observed.
- Kept PAD-US conditionally validated and regionally incomplete with its five-feature prior QA counts exposed; its current AOI impact remains unknown. Kept FEMA exactly access-blocked/unavailable, without a substitute.
- Ran a live 0.00948 km² Boulder-area end-to-end job using the already acquired Census ZIP as an integration fixture and official NLCD, 3DEP, and SDA requests. It completed and exported all three formats. Exact checksums and bounded measurements are in `docs/PROJECT_STATE.md`; raw evidence and outputs remain in the external data directory.
- Deterministic suite: 20 tests pass; Ruff, mypy, CLI help, and `git diff --check` pass. No raw artifacts were added to Git. Milestone 1 final source approval remains open; this implementation does not claim regional completeness or production readiness.

## Follow-up

Next recommended vertical slice: durable source-version and ingestion-run records with safe candidate promotion, built on the planned PostGIS/local-foundation work rather than extending the temporary JSON persistence model.
