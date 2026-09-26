# Primary screening workspace

## Outcome

Implemented the map-centric primary frontend around the recorded Washington,
DC report. The full-viewport shell now keeps the real Leaflet AOI map central,
shows a persistent truthful layer-availability panel, presents compact
independent source findings, and provides secondary reports/exports,
data-source, and activity/provenance tabs. NLCD and 3DEP are explicitly
metrics-only in the fixture; SSURGO, PAD-US, and FEMA retain their recorded
incomplete, conditional, unknown, or unavailable states. The operations console
remains available at `?view=operations`.

Validation completed:

- frontend tests: 18 passed;
- production build: passed;
- desktop and mobile browser review: completed against the static preview;
- existing Leaflet AOI loading/error behavior preserved;
- no backend, catalog, CLI, source, screening, or provider behavior changed.
