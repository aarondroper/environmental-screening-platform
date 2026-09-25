# Generic SSURGO package acquisition

## Outcome

Implemented and live-smoke-verified on 2026-09-25.

- Added `ingest-ssurgo` for persisted generic AOIs.
- Discovered survey areas through official NRCS SDA and joined `sacatalog`
  release metadata.
- Resolved official WSS package URLs dynamically and persisted a deterministic
  plan before package-body requests.
- Enforced survey-area and aggregate-byte limits using streamed provider
  `Content-Length` metadata.
- Recorded inactive SQLite candidates, acquisition attempts, source versions,
  checksums, sizes, HTTP metadata, AOI revision/geometry hashes, and ZIP
  structure validation.
- Preserved `ingest-ssurgo-regional` as the Northern Colorado regression alias.
- Added mocked/local tests and a live DC001 smoke outside Northern Colorado.

The live smoke acquired a 12,965,824-byte official DC001 package with SHA-256
`e5aa8a7b9b08aadedc0eec206fc06323ff37515e00b5e6fc756f2e6c7bba0989`. No
staging, repair, clipping, coverage analysis, promotion, or source-maturity
change was introduced.
