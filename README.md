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

All runtime records and raw source responses must live outside this repository. For example:

```bash
DATA_DIR=/home/aarondroper/projects/environmental-screening-platform-data/local-run
.venv/bin/screening --data-dir "$DATA_DIR" project-create --name "Example review" --aoi /path/to/aoi.geojson
.venv/bin/screening --data-dir "$DATA_DIR" screen --project-id PROJECT_ID
.venv/bin/screening --data-dir "$DATA_DIR" export --job-id JOB_ID --output-dir "$DATA_DIR/exports"
```

AOI input is GeoJSON WGS84 longitude/latitude with one valid Polygon or MultiPolygon fully inside the approved Boulder/Larimer/Weld 2025 county union. AOI changes create new immutable revisions. The first project creation automatically retrieves the official 2025 TIGER/Line national county ZIP if the external boundary cache is absent, then retains only the three approved counties in the runtime boundary. The official archive is about 84 MB; no other national environmental products are downloaded.

The `screen` command is job-oriented but currently executes the local worker synchronously. It requests bounded AOI windows from official NLCD and 3DEP services and makes a bounded NRCS SDA query. Large AOIs over the current per-request cell ceiling produce explicit source failures/unknown coverage; automatic tiled stitching is not implemented. PAD-US is shown as conditionally validated/incomplete with prior sample quarantine counts; FEMA is shown as access-blocked/unavailable. Neither is silently replaced.

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

`ingest` creates an inactive candidate; promotion is a separate explicit step. `retry-ingestion --run-id RUN_ID` creates a new linked run and preserves the prior attempt. Candidate metadata, acquisition attempts, validations, decisions, and the active-version pointer are stored transactionally in a local SQLite catalog under the external data directory. Artifacts are rehashed at registration and again before promotion. PAD-US remains quarantined/conditional and FEMA remains blocked; neither is acquired or promotable. This catalog is a local metadata/control store only: it does not load canonical spatial data to PostGIS, and the current `screen` job does not yet consume its active-version pointer.

The exports are a JSON source/result record, CSV with one row per source and provenance/state, and GeoJSON with the AOI plus valid SSURGO map-unit polygons produced by that run. Hydric ratings remain component-level soil data, not a wetlands inventory or regulatory wetland determination. The result is preliminary; missing or incomplete data are not treated as no constraint, and no composite score is calculated.

## Current limits

There is no PostGIS, database migration history, HTTP API, asynchronous queue, frontend, deployment, or CI workflow yet. Live small-AOI source requests are not final source approval, production validation, or regional coverage proof. Follow `docs/BACKLOG.md` for the next objective and `AGENTS.md` for project operating rules.
