# Screening shell density pass

## Objective

Make the primary workspace read as a compact planner-facing screening tool rather than a report or debug dashboard.

## Scope

- Consolidate project/AOI identity, status, and primary actions into one header row.
- Limit primary navigation to Screening, Reports, and Data sources.
- Keep the map at roughly two-thirds of the desktop workspace with a single compact source-summary region beside it.
- Collapse the map layer control by default while keeping the AOI rendered and source availability truthful.
- Preserve the current Leaflet map, metrics, source states, exports, operations route, and secondary provenance details.
- Give mobile a map-first layout with the summary as a bottom-sheet-like region.

## Outcome

Completed 2026-09-26. The primary screening workspace now has a compact
single-row header, a roughly 67/33 desktop map-summary split, collapsed layer
availability control, compact expandable source rows, three primary tabs, and
a map-first mobile layout. Technical identifiers remain in secondary details
or the separate operations route. Frontend tests, production build, repository
quality checks, and manual desktop/mobile preview review passed for the
recorded Washington, DC demonstration.
