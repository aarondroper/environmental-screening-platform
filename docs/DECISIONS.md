# Decisions

Short records of decisions that `PROJECT_CONTEXT.md` left open. Owner decisions are marked.
Newest last.

**D1 — Stack (owner, per context).** Python/FastAPI, PostgreSQL/PostGIS with Alembic,
React + TypeScript + MapLibre, Docker Compose, GitHub Actions.

**D2 — Prototype reset (owner, 2026-09-27).** The earlier file-backed CLI prototype (SQLite
catalog, per-AOI on-demand acquisition and promotion, fixture modes, static Leaflet console)
and its process documents were removed. Reusable logic is in history at commit `197052d`.

**D3 — Region: Colorado statewide (owner, 2026-09-27).** Datasets are maintained as
versioned regional datasets for Colorado; AOIs outside the region are rejected with a clear
message. The region boundary is data (Census TIGER state boundary), so widening it later is a
data-load exercise, not a rewrite. Per-AOI on-demand acquisition from providers is not used.

**D4 — Sources (owner, 2026-09-27).** FEMA NFHL; PAD-US 4.1; Annual NLCD (2025 land cover);
USGS 3DEP 1 arc-second DEM; NRCS SSURGO hydric-soil information. NWI stays excluded
(redistribution terms unconfirmed). Details in `SOURCES.md`.
*Update 2026-09-27:* the planned manual PAD-US acquisition is unnecessary. FEMA and
ScienceBase block non-US traffic but serve US hosts normally (verified from a GitHub runner),
so all five sources are fully automated. Consequence: live ingestion runs on US
infrastructure (the VM or CI), never from a non-US development machine; tests use small
checked-in fixtures.

**D5 — Screening metrics (owner, 2026-09-27).** Per-source, no thresholds or composite score:
FEMA area/% of AOI by flood zone; PAD-US overlap area by GAP status and manager type, plus
nearest distance when not overlapping; NLCD area/% by class; SSURGO area/% by hydric-rating
class (soil indicator, not wetlands); 3DEP slope mean, median, p90, max.

**D6 — No authentication (owner, 2026-09-27).** Public demo; protected by AOI size limits and
rate limiting instead.

**D7 — Hosting at zero cost: Oracle Cloud Always Free (owner, 2026-09-27).** One Ampere A1
VM (2 OCPU / 12 GB / 200 GB block storage) runs the Compose stack behind Caddy (automatic
TLS). Accepted trade-offs: card verification at signup, possible regional ARM capacity
shortages, idle-reclamation policy (scheduled jobs keep the VM active), self-managed VM.

**D8 — Queue: PostgreSQL job table (development, owner-approved as free).** Workers claim jobs
with `SELECT … FOR UPDATE SKIP LOCKED`. No Redis: one fewer service, and job state commits
atomically with results.

**D9 — PostGIS image `imresamu/postgis` (development).** Multi-arch (amd64 + arm64) builds by
the docker-postgis maintainer; the official `postgis/postgis` image is amd64-only and would
not run on the ARM VM.

**D10 — Basemap: OpenFreeMap (development).** Free vector tiles, no API key.

**D11 — Interim region check and AOI limit (development, 2026-09-27).** AOIs must fall inside
Colorado's TIGER 2025 bounding box (the state's borders follow lines of latitude/longitude)
until the TIGER boundary is loaded as data; AOIs are limited to 250 km² for the public demo.
A 250 km² screening against real SSURGO data takes ~0.1 s, so the limit is about the
public demo's load, not performance.

**D12 — SSURGO hydric classes (development, within D5).** Map units are grouped by
`muaggatt.hydclprs` into the five classes NRCS Web Soil Survey uses for "Hydric Rating by
Map Unit" (100%, 66–99%, 33–65%, 1–32%, <1%) plus "Not rated"; no new thresholds.

**D13 — Validation gates are data-quality limits, not screening thresholds (development).**
E.g. ≤1% of source polygons repaired, polygon area within 1% of the survey-area boundary,
no more than a 10% feature drop versus the active version. A failing version is kept as
`failed` with its report; the active version is untouched.

