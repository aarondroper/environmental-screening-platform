# User-provided AOI loading

## Outcome

Implemented the frontend-only AOI loading slice. The primary workspace now
accepts a local GeoJSON file or pasted GeoJSON, validates a nonempty WGS84
Polygon/MultiPolygon, computes bounds and SHA-256 geometry provenance, and fits
the Leaflet map to the loaded geometry. A replacement AOI clears the recorded
Washington, DC metrics and display derivatives and presents all source pathways
as not evaluated until a future AOI-bound screening run exists.

## Verification

- Frontend unit tests: 30 passed.
- Frontend production build: passed.
- The recorded DC demonstration remains the default/reset state.
