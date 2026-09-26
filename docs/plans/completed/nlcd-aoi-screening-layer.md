# Completed plan: AOI-specific Annual NLCD screening layer

The local generic NLCD bridge now generates a checksum- and lineage-checked
AOI-specific RGBA display derivative after a successful exact-snapshot
screening run. It serves the derivative through job-scoped metadata and asset
routes. The frontend renders it with transparent outside-AOI/nodata pixels,
categorical legend, opacity control, AOI-on-top ordering, and a click identify
message using human-readable NLCD class names. The primary findings panel
shows observed class area and percentage summaries without changing screening
semantics or source maturity.

Validation completed with focused Python tests, frontend tests, a production
build, and the repository quality gates. The checked-in Washington, DC demo
remains the default fixture; generic jobs do not reuse its metrics or preview.
