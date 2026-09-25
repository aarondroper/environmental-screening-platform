# Environmental Screening & GeoData Operations Platform

## Document purpose and status

This is the product brief for a portfolio and consulting-showcase project. It describes the intended product scope, not a claim that the application has already been implemented. The current factual repository state is maintained separately in `docs/PROJECT_STATE.md`.

## Project purpose

Build a small but authentic production-style geospatial platform that continuously acquires, validates, versions, and serves authoritative environmental datasets, then allows a consultancy-style user to screen project areas against those datasets.

The central portfolio story is production geospatial engineering: the system around spatial analysis, including ETL, provenance, data quality, PostGIS, APIs, background processing, testing, deployment, and operational visibility.

## Client problem and target user

The fictional client is a small environmental, infrastructure, renewable-energy, land-planning, or engineering consultancy that repeatedly receives proposed development areas and needs a consistent preliminary answer to:

> What environmental and physical constraints intersect or occur near this proposed area according to our currently maintained authoritative datasets?

The primary user is an analyst or consultant who needs to create a project area, run a screening, inspect results on a map, and download useful outputs. A secondary user is a reviewer or system operator who needs to understand source provenance, versions, freshness, ingestion status, and failures.

## Primary use cases

1. Create a screening project and define its study area by drawing a polygon; simple spatial upload may be added if retained after scoping.
2. Submit a preliminary environmental screening and receive a job identifier.
3. Observe queued, processing, completed, or failed job status.
4. Review transparent per-dataset metrics and mapped constraint features.
5. Inspect the source datasets and versions underlying a result.
6. Download tabular and spatial outputs, with a concise report if that capability is retained.
7. Review source refresh state, latest successful ingestion, feature counts or equivalent, and failures through a data-operations view.

## Intended deliverable

The finished deliverable is a deployed, publicly demonstrable web application backed by a documented API, PostGIS database, background worker, versioned geospatial ingestion system, automated tests, CI/CD, and lightweight operational visibility.

The application should feel like an internal environmental-consulting platform: reliable, precise, restrained, operational, and map-enabled. It should not present itself as a regulatory decision system or as a general-purpose GIS.

## In-scope capabilities

- User-submitted project AOIs bounded by source/provider capability; Northern Colorado remains the known-good regression/demo geography for the initial source direction.
- Approximately five real public/open environmental datasets.
- Heterogeneous source ingestion, such as paginated REST or ArcGIS services, downloadable vector files, and raster assets where justified.
- Raw source snapshots with acquisition metadata and checksums.
- Staging and validation before canonical activation.
- Versioned canonical environmental data in PostgreSQL/PostGIS.
- Project and study-area management.
- Asynchronous screening jobs with status, retries, failure handling, and idempotency.
- Transparent spatial metrics such as overlap area, percentage, counts, lengths, distances, or terrain statistics, depending on final sources.
- SSURGO hydric-soil information may support a clearly labeled soil indicator only; it is not a wetlands inventory or regulatory determination and must not imply jurisdictional-wetland presence or absence.
- FastAPI backend with documented request/response contracts.
- React + TypeScript frontend with MapLibre mapping.
- Source/data-operations view.
- CSV and web-friendly spatial export at minimum; GeoPackage and concise PDF remain desired but are not hard commitments.
- Docker Compose local development environment.
- Automated tests, geospatial/data-contract checks, GitHub Actions CI, automated deployment, health checks, and structured logs.

## Explicit non-goals

This project is not intended to become:

- a machine-learning, deep-learning, EO change-detection, or satellite-classification project;
- a 3D visualization, routing, least-cost-path, telemetry, chatbot, or mobile field-collection project;
- a national or global environmental data platform;
- a full environmental-impact-assessment, permitting, regulatory, or legal-decision product;
- a general-purpose GIS, document-management system, billing SaaS, or enterprise multi-tenant platform;
- a Kubernetes, Kafka, microservice-heavy, or infrastructure-complexity demonstration;
- a catalog of dozens of datasets chosen only to make the product appear larger;
- a complex enterprise IAM or SSO implementation.

## Important constraints

- Northern Colorado (Boulder, Larimer, and Weld counties) remains the owner-selected regression/demo geography, and the five-source MVP direction (FEMA NFHL, PAD-US, Annual NLCD, 3DEP, and SSURGO hydric-soil information) remains owner-selected. The platform AOI contract accepts user-submitted geometries, subject to source-specific coverage and request limits. Exact regional artifacts, representative data characteristics, final access behavior, and actual package scale remain bounded by the validation record before the source set is finalized. NWI is outside the MVP because release-specific redistribution terms could not be confirmed.
- Every public source must permit the intended acquisition, display, and redistribution behavior.
- Screening results must be described as preliminary constraints, not final regulatory, planning, engineering, or environmental-impact conclusions.
- SSURGO soil/hydric attributes must never be described as mapped wetlands, wetland presence/absence, or jurisdictional wetland determinations.
- New source versions must pass source-specific quality gates before becoming active; the last valid version must remain usable after a failed update.
- ETL and screening jobs must be safe to retry and must not create unnecessary duplicates.
- Hosted operation should remain affordable and computationally modest.
- Local setup should be reproducible with documented Docker Compose workflows.
- The system should demonstrate real engineering without hiding every important decision behind an opaque managed service.
- Authentication, report generation, GeoPackage export, exact refresh schedules, object-storage provider, queue implementation, and deployment provider remain open decisions.

## Portfolio, business, and product goals

The project should close the portfolio gap between analytical geospatial projects and production geospatial software. It should make it credible to say:

> I can build the production engineering system around geospatial data—not only analyse data and make maps.

The product should demonstrate sound judgment about what is synchronous versus asynchronous, what is versioned, how source failures are isolated, how spatial data is indexed and queried, and how an operational system is tested and deployed.

## Definition of overall success

The project succeeds when a user can create an AOI, submit and observe an asynchronous screening, review mapped and summarized results, inspect source/version provenance, and download useful outputs through a deployed application.

Behind that workflow, the platform must demonstrably ingest heterogeneous real sources, preserve provenance, validate and normalize data, maintain safe versioned PostGIS datasets, execute idempotent spatial processing, expose a real API, run background jobs, provide migrations, support reproducible local development, pass meaningful automated checks, deploy automatically, and expose enough health/status information to diagnose failures.

The final result should feel like a small but authentic internal platform that a consultancy could plausibly use for preliminary screening—not a decorative architecture diagram around a simple map.
