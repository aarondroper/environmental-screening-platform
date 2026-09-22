# Source acquisition and validation

> Historical first attempt. Its outcome is superseded for Census boundary acquisition by `tiger-fema-recovery.md`; it remains accurate as the earlier task snapshot.

## Objective

Acquire small official-source artifacts outside Git and validate the approved 2025 three-county boundary and five MVP sources before Milestone 2.

## Outcome — incomplete; blocked at validation gate

- Confirmed the canonical repository and clean starting Git state; created `/home/aarondroper/projects/environmental-screening-platform-data/` outside Git.
- Retrieved only the three-county GeoJSON query from the official Census TIGERweb ACS 2025 Counties layer (requested `outSR=4326`): 375,820 bytes. GEOIDs/names and vintage match. Shapely checks found each geometry valid, but their union is a valid `MultiPolygon` with three disconnected components. This generalized web-map geometry does not pass the boundary gate and is not the canonical TIGER/Line geometry. The national 80 MB TIGER/Line archive was not downloaded.
- FEMA NFHL metadata request resolved and connected but TLS reset before HTTP (curl 35). FEMA public-page/MSC routes returned access denial/reset. No FEMA metadata or features were acquired; this is an access blocker, not evidence of source unsuitability.
- Per the task stop condition, PAD-US, Annual NLCD, 3DEP, and SSURGO were not attempted. No MVP source passed artifact-level validation. Milestone 2 was not begun.
- External artifact inventory and SHA-256 are recorded in `/home/aarondroper/projects/environmental-screening-platform-data/manifest.json`.
- Updated source feasibility, project state, architecture, and backlog to report measured results and the resumption gate. No decision entry was added because no new owner decision was made. No application code, schemas, adapters, infrastructure, or dependencies were added.

## Resume gate

The exact TIGER/Line boundary was subsequently acquired and validated; see `tiger-fema-recovery.md` and the current `SOURCE_FEASIBILITY.md`. Retry official FEMA NFHL access, then acquire and validate bounded samples for all five approved sources. Keep the owner-approved geography and source set unchanged. Start Milestone 2 only after every required source gate passes.
