# Source-version records and safe promotion

## Objective

Add durable, queryable acquisition/ingestion/candidate/version lineage and explicit safe promotion without changing the project’s local-prototype operating model or requiring a database service.

## Outcome — completed 2026-09-22

- Added a backend-neutral `SourceRepository` with a local SQLite catalog outside Git. It stores ingestion/retry runs, acquisition attempts, release/checksum source versions, candidate artifact/validation/coverage/error records, promotion decisions, and active-version pointers.
- Existing Census, NLCD, 3DEP, and SSURGO adapters can be invoked as candidate-first ingestions: the acquisition callback persists the raw artifact/version and an `incomplete` candidate before parsing/validation, then finalizes that same record. PAD-US remains conditional with quarantined candidates recorded; FEMA remains access-blocked. Neither has an acquisition adapter or can be promoted.
- Promotion runs transactionally, verifies source/run/validation/coverage/quarantine eligibility, checks artifact path containment and re-hashes bytes before activation, and preserves prior source-version records. Failed retries do not alter the active pointer. Repeated decisions are idempotent; identical source/release/checksum uses one version record.
- Added CLI commands for ingestion, linked retry, run/version/candidate inspection, explicit promotion, and active-version lookup.
- Centralized release-plus-checksum version IDs so acquisition provenance and catalog records use the same stable identity; retained actual media type and request parameters in provenance records.
- Current screening still uses the existing on-demand adapter flow and does not yet consume active catalog versions. SQLite is a local metadata/control repository only; PostGIS canonical spatial storage, schema migrations, and spatial promotion remain future work.
- Validation: 32 deterministic tests passed; Ruff, mypy on `src`, CLI help, no-network FEMA/PAD-US CLI smokes, Markdown relative-link check, and `git diff --check` passed. No network source artifacts were acquired.

## Implementation notes

The toolkit’s documented hashing, provenance, and validate-before-promote guidance informed project-owned code. No toolkit code was copied into runtime use, no coupling was added, and the toolkit was not modified.
