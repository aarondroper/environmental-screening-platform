# Environmental Screening & GeoData Operations Platform

A production-style geospatial data platform. It ingests and validates authoritative
environmental datasets for Colorado, keeps them as versioned datasets in PostGIS, and lets a
consultancy-style user screen a project area against them through an asynchronous job, an
API, and a map-based web app.

The analysis is deliberately simple and transparent: per-dataset overlap areas,
percentages, distances, and slope statistics. There is no composite risk score. Results are
**preliminary screening information**, not regulatory, legal, engineering, or wetland
determinations.

## Status

**Phase 0 (foundation).** The Compose stack (PostGIS, migrations, FastAPI, Caddy + React/MapLibre)
starts from a fresh clone, and CI runs lint, type checks, tests against PostGIS, and a
compose smoke test. Ingestion, versioned datasets, and screening jobs come next. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for what exists and what is planned.

## Quick start

Requires Docker with Compose v2.

```bash
docker compose up --build
```

- App: http://localhost:8080
- API docs: http://localhost:8080/api/docs
- Health: http://localhost:8080/api/health

Development commands (backend with `uv`, frontend with `npm`) are in [CLAUDE.md](CLAUDE.md).

## Stack

Python 3.12 · FastAPI · SQLAlchemy/GeoAlchemy2 · Alembic · PostgreSQL 17 + PostGIS 3.6 ·
React 19 + TypeScript · MapLibre GL · Caddy · Docker Compose · GitHub Actions

## Data sources

FEMA National Flood Hazard Layer, USGS PAD-US 4.1, Annual NLCD 2025, USGS 3DEP 1 arc-second
DEM, and NRCS SSURGO hydric-soil information. Access methods, licences, and volumes are in
[docs/SOURCES.md](docs/SOURCES.md).

## Documentation

- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md): purpose, scope, and non-goals
- [docs/DECISIONS.md](docs/DECISIONS.md): decisions taken since
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): components and data lifecycle
- [docs/SOURCES.md](docs/SOURCES.md): dataset evidence
