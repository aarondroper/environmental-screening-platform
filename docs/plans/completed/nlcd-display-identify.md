# Plan: repair AOI-specific NLCD display and identify

## Outcome

Completed 2026-09-26. The browser derivative now keeps native EPSG:5070
metadata separate from a north-up EPSG:4326 display grid. The categorical
display uses nearest-neighbor reprojection, explicit display bounds and
transform metadata, and transparent AOI/nodata masking. The preview schema was
incremented to 2 and the checked-in demonstration derivative was regenerated
from its retained external source artifact.

The map now installs an identify handler for the job-scoped NLCD preview and a
fallback map-click handler before the preview finishes loading. Valid pixels
report the Annual NLCD year, human-readable class, code, and AOI membership;
outside-AOI and nodata states are explicit; canvas/read failures are visible
instead of silently disabling identify.

## Evidence

Real local bridge job `27a5c1fa-e7d9-4523-aa95-177ca45b87ea` for the Colorado
AOI returned a 957 × 722 EPSG:4326 display raster whose bounds matched its
axis-aligned transform. Source snapshot/version/checksum and AOI revision/hash
matched through the report, metadata endpoint, and served PNG. The actual
interior PNG pixel identified as class 23, Developed Medium Intensity; the
outside-AOI path returned `Outside the loaded AOI.`. That source artifact had
zero AOI nodata cells, so the nodata message was verified with the deterministic
fixture and identify tests.

## Validation

Full Python tests, frontend tests/build, Ruff, Ruff format check, mypy, CLI
help, documentation-link validation, and `git diff --check` passed.
