# CLAUDE.md

Production-style geospatial data platform (portfolio capstone): versioned PostGIS
environmental datasets, async screening jobs, FastAPI, React/MapLibre, CI/CD.
The engineering system is the product; screening analysis stays simple and transparent.

## Read first
- `docs/PROJECT_CONTEXT.md` — authoritative purpose, scope, non-goals, decision boundaries.
  Where it says "not yet selected", `docs/DECISIONS.md` records what the owner has since decided.
- `docs/DECISIONS.md` — owner and development decisions (append new ones, keep them short).
- `docs/ARCHITECTURE.md` — components and data lifecycle; what exists vs planned.
- `docs/SOURCES.md` — the five datasets: access, licence, update behaviour, volume, known issues.

## Layout
- `backend/` — Python package `esp` (`src/esp/`), Alembic migrations, pytest suite.
- `frontend/` — Vite + React + TypeScript + MapLibre; Caddy serves the build and proxies `/api`.
- `docker-compose.yml` — db (PostGIS), migrate (one-shot), api, worker, web.
- `scripts/smoke.sh` — end-to-end check against a running stack (used by CI).

## Commands
```bash
docker compose up --build            # full stack → http://localhost:8090 (API docs: /api/docs)
docker compose up -d db              # just PostGIS for backend tests (port 5432, esp/esp)
docker compose run --rm api esp ingest ssurgo --areas CO644   # live ingest (US network only for some sources)
scripts/smoke.sh                     # e2e against a *fresh* stack; to keep local data use e.g.
                                     # COMPOSE_PROJECT_NAME=esp-smoke WEB_PORT=8091 DB_PORT=5433

cd backend
uv sync                              # install (uv manages .venv and uv.lock)
uv run python -m esp.worker          # worker outside docker (uvicorn esp.api.main:app for the API)
uv run pytest                        # needs PostGIS; ESP_TEST_DATABASE_URL overrides the admin URL
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run alembic revision -m "..."     # new migration (hand-write it; review any autogenerate)

cd frontend
npm ci && npm run dev                # dev server on :5173, proxies /api to :8000
npm run lint && npm run typecheck && npm test && npm run build
```
CI (`.github/workflows/ci.yml`) runs all of the above plus a compose smoke test.

## Conventions
- Walking skeleton first: extend working vertical slices; no abstractions, config, or docs
  ahead of code that needs them. Every milestone leaves compose, migrations, and tests green.
- Tests that touch the database run against real PostGIS (fresh database per test), not mocks.
- Tests never hit provider APIs; use small checked-in fixtures. FEMA and ScienceBase block
  non-US traffic (the owner's machine is outside the US), so live ingestion runs on US hosts
  (the VM or CI).
- Schema changes only through Alembic; migrations must upgrade on a fresh DB and downgrade.
- OWNER DECISIONS (scope, datasets, methodology/metrics/thresholds, auth, visual direction,
  cost, destructive removals) are asked, never assumed. Development decisions: choose, record
  in one line in `docs/DECISIONS.md` if non-obvious, move on.
- Screening output is preliminary and per-source; no composite scores or regulatory language.
  SSURGO hydric data is a soil indicator, never a wetland determination.
- Small coherent commits; verify by running before claiming something works.
