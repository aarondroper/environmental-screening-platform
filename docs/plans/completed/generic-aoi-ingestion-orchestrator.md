# Generic multi-source AOI ingestion orchestrator

## Outcome

Implemented the bounded `ingest-aoi` parent workflow for persisted immutable
AOI revisions. The workflow writes deterministic source plans before provider
access, persists parent runs in the external SQLite catalog, dispatches the
existing generic NLCD/3DEP/SSURGO adapters independently, records child
attempt/candidate/provenance summaries, and leaves all candidates inactive.

The CLI supports explicit source selection, per-source artifact/byte limits,
total byte limits, dry-run planning, and idempotent retries of failed or
incomplete source entries. Focused mocked tests cover all-success and partial
failure, checksum error retention, AOI hash provenance, deterministic/no-
network dry runs, retry history, and retry idempotence.

## Validation

- Focused tests: passed.
- Ruff and mypy: passed.
- Full suite: passed with the existing integration/fixture skips; the five
  repository-wide formatting discrepancies remain pre-existing and are
  reported separately.
- No source promotion, FEMA/PAD-US acquisition, screening change, or raw
  artifact was introduced.
