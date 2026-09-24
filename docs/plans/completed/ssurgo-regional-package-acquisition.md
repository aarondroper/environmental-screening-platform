# Automated regional SSURGO package acquisition

## Outcome

Completed on 2026-09-24. The workflow resolved the existing sizing record for
the unchanged Boulder/Larimer/Weld 2025 AOI, acquired all 19 official NRCS
survey-area ZIP packages, and recorded one SQLite ingestion run, acquisition
attempt, source version, and inactive candidate per survey area. Provider-
reported `Content-Length` matched each measured local artifact; all 19 ZIPs
passed CRC and expected spatial/tabular package-structure checks.

The external batch record and manifest are under
`/home/aarondroper/projects/environmental-screening-platform-data/ssurgo/`.
Raw packages remain outside Git. The candidates are incomplete and
`not_promoted`; no active SSURGO version was created. The existing SSURGO SDA
fixture adapter, PostGIS schema, screening behavior, source scope, PAD-US, and
FEMA were unchanged.

## Validation

- Deterministic mocked acquisition tests cover all 19 packages, malformed ZIP
  retention, provider-size mismatch, content-addressed version reuse, and
  absence of promotion.
- `pytest`, Ruff, mypy, CLI help, documentation checks, and `git diff --check`
  were run for the completed change.
- This task validates acquisition and ZIP containers only. It does not parse
  the package contents, establish clipped regional coverage, or make SSURGO
  production-ready.
