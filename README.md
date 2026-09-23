# Environmental Screening & GeoData Operations Platform

This repository currently contains the first local ETL/screening slice described in [the project state](docs/PROJECT_STATE.md). It is a prototype and source maturity remains limited to the scopes described in [source feasibility](docs/SOURCE_FEASIBILITY.md) and the [screening contract](docs/SCREENING_CONTRACT.md).

## Local setup

Use Python 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/mypy src
```

The local PostGIS boundary is optional and is not required for the deterministic test suite. It uses the pinned `postgis/postgis:16-3.4` image, an external bind-mounted data directory, and credentials supplied through the environment; no credentials are committed. With Docker and the optional client installed:

```bash
export POSTGIS_USER=screening
export POSTGIS_PASSWORD='set-a-local-password'
export POSTGIS_DB=screening
export ESGP_POSTGIS_DATA_DIR=/home/aarondroper/projects/environmental-screening-platform-data/postgis
export ESGP_POSTGIS_URL='postgresql://screening:set-a-local-password@localhost:5432/screening'
.venv/bin/python -m pip install -e '.[dev,postgis]'
docker compose up -d postgis
.venv/bin/screening --data-dir "$DATA_DIR" postgis-migrate
```

The boundary loader requires explicit SQLite-owned identifiers and preserves all three 2025 Census county components while storing their canonical union. For an approved external artifact, use `postgis-load-boundary` with the exact `source_snapshot_id` and `source_version_id`; the loader records the EPSG:4269 source geometry, EPSG:4326 canonical geometry, and EPSG:5070 analysis-area metadata. The PostGIS volume and source artifact remain outside Git.

All runtime records and raw source responses must live outside this repository. For example:

```bash
DATA_DIR=/home/aarondroper/projects/environmental-screening-platform-data/local-run
.venv/bin/screening --data-dir "$DATA_DIR" project-create --name "Example review" --aoi /path/to/aoi.geojson
.venv/bin/screening --data-dir "$DATA_DIR" screen --project-id PROJECT_ID
.venv/bin/screening --data-dir "$DATA_DIR" export --job-id JOB_ID --output-dir "$DATA_DIR/exports"
```

AOI input is GeoJSON WGS84 longitude/latitude with one valid Polygon or MultiPolygon fully inside the approved Boulder/Larimer/Weld 2025 county union. AOI changes create new immutable revisions. The first project creation automatically retrieves the official 2025 TIGER/Line national county ZIP if the external boundary cache is absent, then retains only the three approved counties in the runtime boundary. The official archive is about 84 MB; no other national environmental products are downloaded.

The `screen` command creates a new source snapshot for the requested AOI and currently executes the local worker synchronously. The worker processes only the exact active versions captured at job creation; it does not acquire a newer candidate during execution. Sources without an active version, including PAD-US and FEMA in the current state, remain explicit unknown, quarantined, or unavailable outcomes. To use newly promoted data, create a new screening job; retry reuses the original snapshot. The optional PostGIS boundary now includes a fixture-only SSURGO map-unit/component load; active regional canonical environmental layers and regional tiling are not implemented.

Source ingestion is separately available as a candidate-first operator workflow. For example:

```bash
.venv/bin/screening --data-dir "$DATA_DIR" ingest --source annual_nlcd --project-id PROJECT_ID
.venv/bin/screening --data-dir "$DATA_DIR" ingestion-runs
.venv/bin/screening --data-dir "$DATA_DIR" source-versions
.venv/bin/screening --data-dir "$DATA_DIR" candidates --status quarantined
.venv/bin/screening --data-dir "$DATA_DIR" candidate-status --candidate-id CANDIDATE_ID
.venv/bin/screening --data-dir "$DATA_DIR" promote-candidate --candidate-id CANDIDATE_ID
.venv/bin/screening --data-dir "$DATA_DIR" active-version --source annual_nlcd
```

`ingest` creates an inactive candidate; promotion is a separate explicit step. `retry-ingestion --run-id RUN_ID` creates a new linked run and preserves the prior attempt. Candidate metadata, acquisition attempts, validations, decisions, the active-version pointer, and immutable job source snapshots are stored transactionally in a local SQLite catalog under the external data directory. Artifacts are rehashed at registration, promotion, and job snapshot/use boundaries. PAD-US remains quarantined/conditional and FEMA remains blocked; neither is acquired or promotable. This catalog is a local metadata/control store only; the separate optional PostGIS repository contains the representative SSURGO fixture under explicit snapshot/version linkage and does not activate it for regional screening.

The exports are a JSON source/result record, CSV with one row per source and provenance/state, and GeoJSON with the AOI plus valid SSURGO map-unit polygons produced by that run. Hydric ratings remain component-level soil data, not a wetlands inventory or regulatory wetland determination. The result is preliminary; missing or incomplete data are not treated as no constraint, and no composite score is calculated.

## Current limits

There is no deployed database, HTTP API, asynchronous queue, frontend, deployment, or CI workflow yet. PostGIS is an optional local repository boundary with a validated Census AOI and representative fixture-only SSURGO tables; Docker/psycopg availability is environment-dependent. Live small-AOI source requests and the SSURGO fixture load are not final source approval, production validation, or regional coverage proof. Follow `docs/BACKLOG.md` for the next objective and `AGENTS.md` for project operating rules.
