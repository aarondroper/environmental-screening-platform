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

**Walking skeleton complete, with one dataset end to end.** NRCS SSURGO survey-area
packages are acquired, stored as checksummed raw snapshots, validated, and promoted as a
versioned PostGIS dataset. A user draws or uploads an AOI; an asynchronous worker screens it
against the pinned dataset version; the web app shows per-class hydric-soil metrics and the
clipped soil map units on a MapLibre map. CI runs lint, type checks, tests against PostGIS,
and an end-to-end smoke test of the whole Compose stack. The remaining four datasets,
statewide coverage, exports, and deployment are next; see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

Requires Docker with Compose v2.

```bash
docker compose up --build
```

- App: http://localhost:8090
- API docs: http://localhost:8090/api/docs
- Health: http://localhost:8090/api/health

Load data (a live download from USDA; ~45 s for Larimer County Area), then screen an AOI in
the app:

```bash
docker compose run --rm api esp ingest ssurgo --areas CO644
```

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
