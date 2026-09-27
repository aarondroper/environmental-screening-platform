Project Context
===============

1\. Project Identity
--------------------

**Project name:** Environmental Screening & GeoData Operations Platform

**One-sentence description:**A production-style geospatial data platform that continuously ingests and validates authoritative environmental datasets, stores and serves them through a versioned PostGIS-backed architecture, and allows consultancy-style project areas to be screened against environmental constraints through a web application and API.

**Project type:**Self-directed portfolio / consulting showcase project and production-geospatial-engineering capstone.

**Intended audience / fictional client:**A small environmental, infrastructure, renewable-energy, land-planning, or engineering consultancy that repeatedly needs to:

*   maintain authoritative environmental GIS datasets;
    
*   create project study areas;
    
*   screen those areas against environmental constraints;
    
*   review results spatially;
    
*   produce standardized GIS and client-facing outputs.
    

The product should resemble an internal consultancy platform rather than a single-purpose public map.

**Geographic area:**Not yet selected.

The project should use **one contained country or region**, not attempt broad multi-country or global coverage.

The geography should ultimately be selected based on:

*   availability of several authoritative public environmental datasets;
    
*   multiple access methods suitable for demonstrating ETL;
    
*   licensing suitable for a public portfolio;
    
*   manageable data volumes;
    
*   realistic environmental-screening use cases.
    

**Current maturity/status:**Pre-development project-definition stage.

No ingestion pipeline, database, API, worker system, frontend, CI/CD configuration, or deployment has yet been implemented within this project context.

2\. Core Purpose
----------------

### Practical / fictional client problem

The fictional consultancy regularly receives new project areas and needs to answer a question approximately like:

> What environmental and physical constraints intersect or occur near this proposed development area, and can we generate a consistent preliminary screening result using our current authoritative datasets?

A user should be able to create a project area and run a standardized environmental screening.

A representative project might be:

> **North Ridge Solar Development**

with an AOI supplied by:

*   drawing a polygon; or
    
*   uploading a simple spatial boundary such as GeoJSON.
    

The system should then evaluate the AOI against a contained set of environmental datasets and return results such as:

*   area intersecting wetlands;
    
*   overlap with flood-hazard areas;
    
*   protected-area intersections or nearest distance;
    
*   woodland / land-cover overlap;
    
*   watercourse crossings or proximity;
    
*   terrain statistics such as mean slope or high-slope area.
    

The exact screening layers and metrics remain dependent on geography and source availability.

### Why the project exists

The broader portfolio already demonstrates or is intended to demonstrate:

*   environmental GIS analysis;
    
*   Earth observation;
    
*   spatial modelling;
    
*   3D geospatial visualization;
    
*   routing;
    
*   dashboards;
    
*   classical geospatial machine learning;
    
*   deep-learning feature extraction.
    

The major remaining gap is **production geospatial software and data engineering**.

The project therefore exists primarily to demonstrate:

> the system around geospatial analysis.

The important professional story is not merely:

> Data was downloaded, analysed, and shown on a map.

It is:

> External geospatial sources are reliably acquired, versioned, validated, transformed, stored, indexed, served, monitored, tested, refreshed, and deployed through a maintainable software system.

### Professional objective

A successful finished project should demonstrate the ability to build a complete production-style geospatial platform involving:

*   ETL;
    
*   data validation;
    
*   geospatial data modelling;
    
*   PostGIS;
    
*   API development;
    
*   asynchronous/background processing;
    
*   source versioning;
    
*   object storage;
    
*   Dockerized development;
    
*   automated testing;
    
*   CI/CD;
    
*   deployment;
    
*   observability;
    
*   geospatial web application development.
    

The project should establish that the developer can build **production systems around spatial analysis**, not just analyses themselves.

3\. Intended User Experience
----------------------------

The application should behave like an internal environmental-consulting platform.

### Primary analyst workflow

A likely user journey is:

1.  Log into or open the application, depending on whether authentication is retained in scope.
    
2.  View existing screening projects.
    
3.  Create a new project.
    
4.  Provide a study area by drawing a polygon or supplying a simple geospatial boundary.
    
5.  Start an environmental screening.
    
6.  See the screening enter a job lifecycle such as:
    
    *   queued;
        
    *   processing;
        
    *   complete;
        
    *   failed.
        
7.  Open the completed result.
    
8.  Review headline screening metrics.
    
9.  Inspect intersecting constraints on the map.
    
10.  Explore individual datasets / screening results.
    
11.  Download GIS or tabular outputs.
    
12.  Produce a concise screening summary/report if reporting remains in scope.
    

The product should communicate clearly that screening results are **preliminary environmental constraints**, not final regulatory, planning, engineering, or environmental-impact conclusions.

### Data-operations workflow

The product should also expose a separate operational view of the underlying geospatial data platform.

A data-source/admin page should allow a reviewer to understand:

*   which source datasets exist;
    
*   provider;
    
*   source/version;
    
*   last refresh;
    
*   current active version;
    
*   feature count;
    
*   processing status;
    
*   latest successful ingest;
    
*   latest error where applicable;
    
*   source CRS / normalized CRS where useful;
    
*   license/provenance information.
    

This is important because ETL and data engineering should be visible in the portfolio product rather than hidden entirely in repository scripts.

### Product feel

The platform should feel like:

*   an internal consultancy system;
    
*   reliable;
    
*   operational;
    
*   precise;
    
*   data-centric;
    
*   map-enabled.
    

It should **not** feel primarily like another analytical showcase map.

4\. Confirmed Scope
-------------------

### Core product scope

The intended contained product scope is approximately:

*   one geographic region;
    
*   roughly five external environmental datasets;
    
*   project/study-area creation;
    
*   one standardized screening workflow;
    
*   screening-job execution;
    
*   screening results;
    
*   map-based review;
    
*   a source/data-operations view;
    
*   API-backed architecture;
    
*   one background worker mechanism;
    
*   one PostgreSQL/PostGIS database;
    
*   automated CI/CD;
    
*   public or demonstrable deployment.
    

This is the principal scope boundary intended to keep the engineering architecture sophisticated while the user-facing product remains manageable.

### Environmental screening

The platform should intersect or otherwise spatially evaluate a project AOI against a small number of environmental constraints.

Candidate categories discussed include:

*   protected areas;
    
*   wetlands;
    
*   flood hazard;
    
*   hydrography / watercourses;
    
*   land cover / woodland;
    
*   terrain / slope.
    

The final set should be approximately five layers and should be determined after selecting the geography and auditing source data.

The project should not attempt to model every environmental planning constraint.

### Data ingestion

The platform should deliberately ingest **multiple external geospatial data formats / source types**.

Examples discussed include:

*   ArcGIS REST / Feature Services;
    
*   conventional REST APIs;
    
*   downloadable vector files;
    
*   GeoTIFF / COG raster sources;
    
*   potentially WFS or similar geospatial services.
    

The objective is to exercise genuinely different ETL patterns rather than build five identical download scripts.

### Raw-data preservation

Source acquisition should preserve raw source material or source snapshots rather than immediately overwrite a canonical production table.

A conceptual structure is:

source→ raw snapshot→ staging/validation→ normalized canonical data

Raw copies should include enough provenance to identify:

*   acquisition time;
    
*   source;
    
*   checksum;
    
*   version where available.
    

Object storage is the preferred conceptual location for raw files.

### Staging / normalization

A distinct staging or transformation layer should perform tasks such as:

*   schema normalization;
    
*   CRS normalization;
    
*   geometry validation/repair;
    
*   type normalization;
    
*   deduplication;
    
*   required-field validation;
    
*   other source-specific cleanup.
    

Invalid upstream data should not silently enter the active production dataset.

### PostGIS canonical store

Normalized spatial data should be loaded into PostgreSQL/PostGIS.

The database should represent concepts such as:

*   source datasets;
    
*   source versions;
    
*   ingestion runs;
    
*   project records;
    
*   project geometries;
    
*   screening jobs;
    
*   screening results;
    
*   normalized environmental datasets.
    

Exact table design remains an architecture decision.

### Dataset versioning

The data platform should retain enough metadata to know:

*   what dataset version is currently active;
    
*   when it was acquired;
    
*   whether ingestion succeeded;
    
*   whether a newer version exists;
    
*   which version a screening result used where practical.
    

Versioning is an important part of the platform concept.

### Data quality gates

Before a new source version is activated, the ingestion workflow should perform automated validation.

Candidate checks include:

*   required fields exist;
    
*   expected geometry type;
    
*   recognized CRS;
    
*   plausible spatial extent;
    
*   minimum feature counts;
    
*   geometry validity;
    
*   acceptable null rates;
    
*   plausible raster dimensions/resolution.
    

The exact thresholds should be source-specific.

A failed new version should not automatically replace the previously valid active version.

### Scheduled refresh

The system should support periodic checking / refresh of source data.

A conceptual workflow is:

scheduled trigger→ check source→ identify change→ acquire new version→ checksum→ stage/validate→ load→ QA→ promote new version if valid

If no upstream change exists, the process should be able to perform a no-op rather than unnecessarily rebuild everything.

The exact schedule is unresolved.

### Idempotent ingestion

Re-running an ingestion process should not create duplicate canonical features or dataset versions unnecessarily.

Retrying jobs should be safe.

Idempotency should be deliberately implemented and tested.

### Screening jobs

Environmental screening should use an asynchronous/background-job pattern rather than requiring a long-running request to remain open.

A likely workflow is:

create screening request→ return job identifier→ worker processes geospatial calculations→ update status→ persist results→ frontend retrieves completed result

The exact queue implementation remains an architecture decision.

### API

The platform should expose a proper backend API.

Likely API domains include:

*   projects;
    
*   study areas;
    
*   screening jobs;
    
*   screening results;
    
*   environmental datasets;
    
*   source / ingestion status.
    

FastAPI is the strongly preferred backend framework.

The API should expose documented request/response contracts.

OpenAPI documentation is expected as a natural consequence of the preferred FastAPI architecture.

### Frontend

A React + TypeScript frontend is strongly preferred.

MapLibre should provide the interactive mapping component.

The frontend should support:

*   project management;
    
*   AOI visualization;
    
*   screening status;
    
*   map-based constraint inspection;
    
*   result summaries;
    
*   source/data-operations status;
    
*   downloads.
    

### Reporting / exports

The intended consulting workflow includes downloadable outputs.

Current desired outputs include:

*   CSV screening summary;
    
*   GeoJSON and/or GeoPackage GIS output;
    
*   project boundary export;
    
*   concise screening report, potentially PDF.
    

GeoJSON/CSV-style export is core to the concept.

PDF and GeoPackage remain strong preferences rather than fully locked implementation requirements.

### Local development environment

The project should have a reproducible containerized local environment.

Docker Compose is the preferred development pattern.

Conceptual services include:

*   PostGIS;
    
*   API;
    
*   background worker;
    
*   queue;
    
*   object storage;
    
*   frontend.
    

Not every component must necessarily run in a dedicated container if a simpler architecture produces the same reproducibility.

### CI

Automated continuous integration is a central requirement.

Candidate checks include:

*   Python linting;
    
*   Python tests;
    
*   frontend linting/tests;
    
*   TypeScript typecheck;
    
*   database migration tests;
    
*   integration tests;
    
*   geospatial data-contract tests;
    
*   frontend production build;
    
*   container build.
    

The exact workflow should be defined during repository architecture.

### CD

Automated deployment from the main branch is strongly intended.

A successful main-branch workflow should conceptually:

*   pass CI;
    
*   build relevant artifacts/images;
    
*   apply or verify database migrations;
    
*   deploy backend/worker;
    
*   deploy frontend;
    
*   run health/smoke checks.
    

The exact hosting platform is not yet selected.

### Observability

The platform should include lightweight operational visibility.

This should cover at least some combination of:

*   structured application logs;
    
*   ingestion logs;
    
*   job status;
    
*   API health;
    
*   failed-ingest visibility;
    
*   data freshness.
    

Full production-scale observability infrastructure is not required.

5\. Explicit Non-Goals
----------------------

This project should **not** become another advanced analytical modelling project.

The following are explicitly outside the intended focus:

*   machine learning;
    
*   deep learning;
    
*   satellite-image classification;
    
*   EO change detection;
    
*   3D visualization;
    
*   routing / least-cost-path analysis;
    
*   live telemetry;
    
*   chatbots / LLM features;
    
*   mobile field collection;
    
*   custom scientific modelling.
    

Those capabilities are represented by other portfolio projects.

### Infrastructure overengineering

The project should not introduce:

*   Kubernetes;
    
*   event-streaming infrastructure;
    
*   Kafka;
    
*   microservice proliferation;
    
*   distributed computing merely for appearance;
    
*   unnecessarily complex orchestration;
    
*   elaborate infrastructure-as-code without a demonstrated need.
    

Terraform is not currently required.

### Product scope

The project should not become:

*   a general-purpose GIS;
    
*   a national environmental data platform;
    
*   a full environmental-impact-assessment product;
    
*   a permitting platform;
    
*   a document-management system;
    
*   enterprise multi-tenancy;
    
*   a complex collaboration platform;
    
*   a billing SaaS application.
    

### Environmental scope

Do not ingest dozens of datasets merely to make the source catalog look substantial.

Approximately five well-chosen sources are sufficient.

### Authentication complexity

If authentication is included, it should remain simple.

Complex enterprise identity management, SSO, organization hierarchies, and fine-grained permission systems are outside scope.

6\. Professional / Portfolio Objectives
---------------------------------------

This project's primary purpose is to demonstrate **production geospatial software engineering**.

### ETL / data engineering

The project should demonstrate:

*   heterogeneous source ingestion;
    
*   pagination;
    
*   retries;
    
*   timeouts;
    
*   checksums;
    
*   source versioning;
    
*   schema validation;
    
*   CRS normalization;
    
*   geometry repair;
    
*   deduplication;
    
*   idempotent loads;
    
*   raw/staging/core separation;
    
*   source provenance;
    
*   scheduled refresh;
    
*   failure-safe dataset promotion.
    

### PostgreSQL/PostGIS

The project should demonstrate:

*   intentional database schema design;
    
*   spatial geometry columns;
    
*   GiST spatial indexes;
    
*   conventional indexes where appropriate;
    
*   migrations;
    
*   performant spatial intersection / proximity queries;
    
*   query analysis / profiling;
    
*   handling complex polygons where relevant.
    

Potential techniques such as ST\_Subdivide may be used if actual datasets justify them, but should not be added artificially.

### Backend development

Demonstrate:

*   FastAPI;
    
*   REST API design;
    
*   request/response schemas;
    
*   validation;
    
*   asynchronous job submission;
    
*   API documentation;
    
*   health/status endpoints;
    
*   error handling.
    

### Background processing

Demonstrate:

*   worker jobs;
    
*   queueing;
    
*   job state;
    
*   retries;
    
*   failure handling;
    
*   idempotency.
    

### DevOps / operational engineering

Demonstrate:

*   Docker;
    
*   reproducible local environment;
    
*   CI;
    
*   CD;
    
*   database migration automation;
    
*   deployment;
    
*   smoke tests;
    
*   health checks;
    
*   structured logging.
    

### Data quality

Demonstrate that data itself receives automated QA, not just application code.

This may include:

*   feature-count checks;
    
*   CRS checks;
    
*   schema contracts;
    
*   geometry validity;
    
*   spatial extent checks;
    
*   stale-data detection;
    
*   output completeness.
    

### Geospatial analysis

The screening analysis itself should demonstrate practical PostGIS/geospatial operations such as:

*   intersection;
    
*   overlap;
    
*   buffering / proximity;
    
*   area / length calculations;
    
*   raster sampling or zonal statistics where relevant.
    

The analysis should remain straightforward enough that it does not distract from the system-engineering objective.

### Frontend / web mapping

Demonstrate:

*   React;
    
*   TypeScript;
    
*   MapLibre;
    
*   project workflows;
    
*   job status;
    
*   maps;
    
*   data status;
    
*   downloads;
    
*   usable internal-product UX.
    

### Product thinking

Demonstrate the ability to identify which parts of a system should be:

*   synchronous;
    
*   asynchronous;
    
*   versioned;
    
*   cached/precomputed;
    
*   user-facing;
    
*   operational/admin-facing.
    

7\. Data and External Resources
-------------------------------

No geography or exact external data source has yet been selected.

Therefore, **no data source should currently be treated as verified for the project**.

### Required source mix

The final geography should provide approximately five authoritative/open environmental datasets representing several access patterns.

A desirable conceptual mix includes:

#### Protected areas

**Purpose:**Identify direct project overlap and/or nearest protected sites.

**Likely data type:**Vector polygons.

**Preferred access:**REST, ArcGIS Feature Service, or public download.

**Status:**Unselected.

#### Wetlands

**Purpose:**Calculate wetland area within the project AOI.

**Likely data type:**Vector polygons.

**Status:**Unselected.

#### Flood hazard

**Purpose:**Measure project-area exposure to mapped flood hazard.

**Likely data type:**Raster or vector hazard zones.

**Status:**Unselected.

#### Hydrography / watercourses

**Purpose:**Identify intersecting or nearby streams/rivers.

**Likely data type:**Vector lines.

**Status:**Unselected.

#### Land cover / woodland

**Purpose:**Calculate selected land-cover intersections.

**Likely data type:**Raster or vector.

**Status:**Unselected.

#### Terrain / DEM

A terrain dataset was discussed as another possible source, especially if it can provide slope metrics.

Because the intended contained MVP is approximately five datasets, DEM/terrain may replace rather than supplement another layer.

**Status:**Tentative.

### Source-selection requirements

Preferred datasets should have:

*   authoritative provider;
    
*   public/open access;
    
*   public portfolio-compatible licensing;
    
*   repeatable acquisition;
    
*   useful version/update metadata where possible;
    
*   realistic change/refresh behavior;
    
*   manageable scale;
    
*   useful geographic attributes.
    

### Source diversity

The project should deliberately avoid choosing five sources that all use exactly the same technical interface.

A useful platform should exercise several patterns such as:

*   paginated REST;
    
*   ArcGIS Feature Service;
    
*   downloadable file;
    
*   raster asset;
    
*   versioned data release.
    

This diversity is a professional objective, not a requirement to use every possible protocol.

### Raw object storage

Raw downloaded datasets should be preserved in object storage with metadata such as:

*   acquisition timestamp;
    
*   source identifier;
    
*   checksum;
    
*   original filename;
    
*   source version if available.
    

S3-compatible storage is strongly preferred.

Cloudflare R2 has been mentioned as a possible hosted option.

MinIO is a likely local-development analogue.

Neither is yet confirmed.

8\. Analytical / Scientific Methodology
---------------------------------------

The project intentionally uses a **simple, transparent environmental-screening methodology**.

Its sophistication should come from production engineering rather than scientific modelling.

### Screening principle

Each project AOI should be evaluated independently against each selected environmental source.

Results should use understandable physical metrics rather than arbitrary composite scores.

Examples include:

**Protected areas**

*   overlap area;
    
*   percent of project area;
    
*   nearest protected-area distance if no intersection.
    

**Wetlands**

*   overlap area;
    
*   percent of project area.
    

**Flood hazard**

*   exposed area;
    
*   percent of project area;
    
*   potentially hazard class distribution if the source has categorical severity.
    

**Hydrography**

*   intersecting watercourse count;
    
*   line length inside the AOI;
    
*   nearest watercourse distance where appropriate.
    

**Land cover / woodland**

*   area by selected land-cover category;
    
*   percentage of project area.
    

**Terrain**

*   mean slope;
    
*   maximum or high-percentile slope;
    
*   area above a defined slope threshold if such a threshold is explicitly justified.
    

The exact screening rules depend on final sources.

### No composite environmental score

No overall environmental "risk score" has been selected.

The platform should favor transparent individual constraint metrics over an invented weighted summary.

### Spatial operations

Likely operations include:

*   ST\_Intersects;
    
*   intersection geometry;
    
*   area calculations;
    
*   distance/proximity;
    
*   length calculations;
    
*   potentially raster zonal/statistical operations.
    

The exact implementation may occur in PostGIS, Python, or a combination based on performance and dataset structure.

### Dataset version linkage

Where practical, a screening result should retain which active dataset versions were used.

This is important for reproducibility.

### Re-screening

Whether older projects automatically re-screen when a source dataset changes is unresolved.

The system should at minimum preserve enough provenance to know when results were created and what data versions they used.

### Data quality methodology

New source versions should not be activated solely because download/parse succeeded.

They should pass source-specific checks before promotion.

The previous good version should remain available if the new version fails validation.

### Analytical owner review

Owner review will be needed when selecting:

*   final environmental datasets;
    
*   screening metrics;
    
*   proximity distances if used;
    
*   any slope or hazard thresholds;
    
*   any categorization language.
    

Codex should not invent regulatory or environmental thresholds without evidence.

9\. Technical Direction
-----------------------

### Confirmed / strongly preferred stack

#### Backend language

**Python**

Used for:

*   ETL;
    
*   data validation;
    
*   spatial processing;
    
*   API/backend;
    
*   worker jobs.
    

#### Backend API

**FastAPI** is the strongly preferred framework.

Reasons already established include:

*   typed request/response models;
    
*   OpenAPI documentation;
    
*   suitability for a Python geospatial stack;
    
*   straightforward API development.
    

#### Database

**PostgreSQL + PostGIS**

This is a core part of the project rather than an optional résumé technology.

The platform should use PostGIS for:

*   normalized spatial storage;
    
*   project geometries;
    
*   screening records;
    
*   source metadata;
    
*   spatial queries.
    

#### Database migration tooling

**Alembic** is the strongly preferred migration system.

The repository should demonstrate explicit schema evolution rather than manual database setup.

#### Geospatial processing

Likely Python tools include:

*   GeoPandas;
    
*   GDAL;
    
*   Rasterio;
    
*   Shapely;
    
*   PyProj;
    
*   SQL/PostGIS functions.
    

Exact library usage should follow source formats.

#### Frontend

**React + TypeScript**

#### Mapping

**MapLibre**

#### Background processing

A lightweight worker/queue architecture is strongly preferred.

**Redis** was proposed as the likely queue/support service.

The exact Python worker implementation is unresolved.

There is no requirement for Kafka or a heavyweight distributed system.

#### Object storage

S3-compatible object storage is strongly preferred for raw source snapshots.

Potential implementation:

*   MinIO locally;
    
*   R2 or equivalent in hosted deployment.
    

This remains an architecture decision rather than a confirmed provider choice.

#### Local development

**Docker Compose** is strongly preferred.

The intended local environment should make it easy to start the application and supporting services reproducibly.

#### CI/CD

**GitHub Actions** is the preferred CI/CD platform.

The project should use it for both:

*   pull-request validation;
    
*   main-branch deployment workflows.
    

### Database architecture

A conceptual schema includes entities such as:

*   projects;
    
*   project\_areas;
    
*   datasets;
    
*   dataset\_versions;
    
*   ingestion\_runs;
    
*   normalized environmental source tables;
    
*   screening\_jobs;
    
*   screening\_results.
    

Exact table naming and normalization remain development decisions.

### Database performance

The project should intentionally demonstrate:

*   GiST spatial indexes;
    
*   appropriate B-tree/index design;
    
*   query profiling;
    
*   migrations;
    
*   spatial query optimization.
    

Use advanced techniques only where actual query plans justify them.

### ETL architecture

Preferred conceptual structure:

external sources→ source catalog→ ingestion workers→ raw object storage→ staging / validation→ canonical PostGIS tables→ active dataset version

The system should support source-specific ingestion adapters rather than one giant hard-coded script if that can be achieved without unnecessary abstraction.

### Idempotency

ETL and background workflows should be safe to retry.

Examples:

*   same source version should not duplicate records;
    
*   same ingestion run should not blindly append duplicate features;
    
*   screening-job retries should not create inconsistent duplicate results.
    

### Source catalog

The application/database should maintain metadata such as:

*   provider;
    
*   source URL or identifier;
    
*   license;
    
*   source type;
    
*   current active version;
    
*   last checked;
    
*   last successful ingestion;
    
*   status.
    

The exact schema remains a development decision.

### API architecture

Likely API resource areas include:

*   projects;
    
*   project AOIs;
    
*   screenings;
    
*   screening status/results;
    
*   datasets;
    
*   dataset status;
    
*   system health.
    

Exact routes should be designed during API architecture work.

### CI workflow

The intended pull-request pipeline should include the relevant subset of:

*   Python lint;
    
*   Python tests;
    
*   TypeScript lint;
    
*   frontend tests;
    
*   typecheck;
    
*   database migration test;
    
*   API/integration tests;
    
*   geospatial data-contract tests;
    
*   production frontend build;
    
*   container build.
    

Not every possible check must be implemented immediately, but automated quality gates are a core project requirement.

### CD workflow

The intended deployment workflow should:

*   trigger from approved main-branch changes;
    
*   build artifacts/images;
    
*   apply or validate migrations safely;
    
*   deploy services;
    
*   run smoke/health checks.
    

Rollback behavior and hosting-specific details remain unresolved.

### Testing strategy

The project should include several layers of tests.

#### Unit tests

For:

*   parsers;
    
*   transforms;
    
*   schema normalization;
    
*   checksums;
    
*   geometry-handling logic;
    
*   screening calculations.
    

#### Database tests

For:

*   migrations;
    
*   spatial queries;
    
*   constraints;
    
*   indexes where useful.
    

#### Integration tests

For:

*   ingestion into a test database;
    
*   API requests;
    
*   screening-job workflows.
    

#### Geospatial contract tests

Examples:

*   expected CRS;
    
*   valid geometry;
    
*   plausible feature counts;
    
*   known test-AOI intersection result;
    
*   expected raster resolution;
    
*   required fields.
    

#### Frontend tests

For important product workflows and application build correctness.

### Authentication

Simple authentication has been identified as potentially valuable because it would make project ownership and admin/data-source views more realistic.

However, authentication is **not yet confirmed as a hard MVP requirement**.

If included, it should remain minimal, potentially with simple analyst/admin roles.

### Deployment

Exact hosting is unresolved.

Requirements are:

*   affordable;
    
*   reasonable for a portfolio;
    
*   capable of hosting the API/worker/database;
    
*   compatible with automated deployment;
    
*   publicly demonstrable.
    

A purely static host is not sufficient because this project is intentionally intended to demonstrate backend and operational engineering.

10\. UX / Visual Direction
--------------------------

### Product character

The application should look like a credible internal environmental consultancy product.

It should not resemble:

*   a generic developer admin panel;
    
*   a flashy startup SaaS;
    
*   another public-facing story map.
    

### Visual tone

The broader portfolio preferences apply:

*   minimal;
    
*   clean;
    
*   editorial;
    
*   professional;
    
*   restrained;
    
*   geospatially focused;
    
*   little unnecessary visual chrome.
    

Avoid obvious "AI" or overly templated dashboard aesthetics.

### Primary product areas

The application will likely require at least three conceptual areas:

#### Projects

For:

*   project list;
    
*   project creation;
    
*   AOI;
    
*   screening runs;
    
*   project results.
    

#### Screening result

For:

*   map;
    
*   constraint layers;
    
*   summary metrics;
    
*   per-dataset findings;
    
*   exports.
    

#### Data / operations

For:

*   source catalog;
    
*   dataset versions;
    
*   freshness;
    
*   ingestion state;
    
*   failures.
    

Exact navigation structure is unresolved.

### Map behavior

The screening-result map should:

*   emphasize the project AOI;
    
*   show the relevant constraint features;
    
*   avoid overwhelming the user with every source simultaneously;
    
*   make individual screening findings inspectable.
    

### Job-state UX

Asynchronous screening should communicate statuses clearly.

Examples:

*   queued;
    
*   processing;
    
*   completed;
    
*   failed.
    

The UI should provide useful failure information without exposing raw internal stack traces.

### Data-source status

The operations view should make pipeline reliability visually understandable.

Potential status information includes:

*   Healthy;
    
*   Refreshing;
    
*   Failed;
    
*   Stale.
    

Exact labels and visual conventions remain unresolved.

### Operational visibility

A compact system/data-health interface is desirable.

It should not turn into a full observability dashboard.

### Accessibility / responsiveness

The application should follow normal accessibility expectations.

Desktop/laptop is the primary use case.

The UI should remain usable on smaller screens, but full mobile parity with a desktop consultancy workflow is not currently a core requirement.

11\. Constraints
----------------

### Hard project constraints

The project should:

*   remain geographically contained;
    
*   use roughly five external environmental datasets;
    
*   use real public/open geospatial sources;
    
*   demonstrate heterogeneous ETL;
    
*   use PostGIS;
    
*   expose a real backend API;
    
*   include background/asynchronous processing;
    
*   implement automated testing;
    
*   implement CI;
    
*   implement CD;
    
*   be deployable and publicly demonstrable;
    
*   remain feasible as a portfolio project;
    
*   avoid becoming another complex analytical/modeling project.
    

### Hosting constraints

The project should remain reasonably inexpensive to operate.

Unlike predominantly static portfolio projects, some ongoing backend/database cost may be justified here because demonstrating production infrastructure is the point.

The architecture should still avoid unnecessary always-on services.

### Reproducibility

A developer should be able to create a working local environment using documented setup and Docker Compose.

### Data licensing

Every external source used in the public project must permit the intended use / display / redistribution.

### Security

The project should follow sensible application-security practices appropriate to its scope.

It does not need enterprise-grade security certification.

Secrets should not be committed.

### Computational scope

Screening should remain small enough to run with modest hosted resources.

Environmental layers should be optimized/indexed rather than solved by scaling hardware.

### Portfolio suitability

The system should make its engineering sophistication understandable to someone evaluating the public repository.

Important infrastructure should not be hidden behind a fully managed black box where the implemented engineering cannot be inspected.

12\. Quality and Credibility Requirements
-----------------------------------------

The project must feel like a **real geospatial software system**, not a decorative architecture diagram surrounding a simple map.

### ETL credibility

Ingestion should genuinely handle realistic concerns such as:

*   retries;
    
*   paging;
    
*   changed data;
    
*   validation;
    
*   failures;
    
*   idempotency;
    
*   source metadata.
    

### Data lineage

A reviewer should be able to understand:

*   where a source came from;
    
*   when it was fetched;
    
*   which version is active;
    
*   whether it passed QA;
    
*   which data underpinned a screening.
    

### Database credibility

PostGIS should be used intentionally.

The project should show:

*   spatial indexes;
    
*   sensible schema;
    
*   migrations;
    
*   query profiling;
    
*   efficient spatial calculations.
    

### Data quality

A source should not be activated simply because HTTP returned 200.

Source-specific validation should detect obvious breakage or anomalous data.

### Failure safety

If a new ingestion fails:

*   failure should be recorded;
    
*   the previous valid version should remain usable;
    
*   the system should not silently promote broken data.
    

### Reproducibility

Local setup, database schema, migrations, and source ingestion must be reproducible.

### Testing

CI should test meaningful system behavior, not only superficial linting.

Particularly valuable tests include:

*   migrations against a fresh database;
    
*   ingestion of representative fixture data;
    
*   geometry validity;
    
*   screening results for known test geometry;
    
*   idempotent reruns;
    
*   API workflow integration.
    

### Deployment credibility

Main-branch deployment should be automated enough to credibly qualify as CI/CD rather than manual copying to a host.

### Observability

Failures should be discoverable from logs/status rather than requiring local debugging against production.

### Realistic claims

The screening product should be described as preliminary environmental screening.

It should not claim to replace:

*   regulatory review;
    
*   environmental impact assessment;
    
*   site survey;
    
*   professional planning/legal advice.
    

### Visual quality

The web application should be polished enough that the sophisticated backend is paired with a credible frontend experience.

13\. Intended Final Deliverables
--------------------------------

### External-source ingestion framework

A reproducible system capable of ingesting approximately five selected environmental datasets from multiple source types.

### Raw-source archive

Versioned/source-attributed raw files stored outside Git, with metadata/checksums.

### Staging and data-validation layer

Code for:

*   schema checks;
    
*   spatial checks;
    
*   geometry repair;
    
*   CRS normalization;
    
*   data-quality gates.
    

### PostGIS database

A versioned database schema supporting:

*   source catalog;
    
*   dataset versions;
    
*   ingestion runs;
    
*   canonical environmental layers;
    
*   projects/AOIs;
    
*   screening jobs/results.
    

### Database migrations

A reproducible migration history using Alembic or the finalized equivalent.

### Background processing system

A worker/queue system supporting:

*   screening jobs;
    
*   likely ingestion jobs;
    
*   job status;
    
*   retries;
    
*   idempotency.
    

### Backend API

A documented FastAPI service providing access to:

*   projects;
    
*   screenings;
    
*   results;
    
*   dataset/source information;
    
*   system health/status.
    

### Screening engine

A transparent geospatial screening workflow that returns physical/interpretable metrics for the selected environmental layers.

### Interactive web application

A React/TypeScript + MapLibre application supporting:

*   project management;
    
*   AOI creation/viewing;
    
*   screening execution/status;
    
*   results map;
    
*   constraint summaries;
    
*   source/data status;
    
*   downloads.
    

### Data operations view

A user-visible interface for inspecting:

*   source datasets;
    
*   active versions;
    
*   refresh state;
    
*   feature counts or equivalent;
    
*   ingestion health.
    

### Exports

At minimum, useful tabular/geospatial export of screening results.

Desired forms include:

*   CSV;
    
*   GeoJSON and/or GeoPackage;
    
*   project boundary.
    

A concise PDF screening report is strongly desired but not yet a hard requirement.

### Dockerized local environment

A documented Docker Compose environment sufficient to run the principal system components locally.

### Automated tests

Coverage across:

*   ingestion;
    
*   data transforms;
    
*   geospatial calculations;
    
*   database/migrations;
    
*   API;
    
*   background jobs;
    
*   frontend;
    
*   integration paths.
    

### CI

A GitHub Actions-based pull-request validation workflow.

### CD

An automated main-branch deployment pipeline with post-deploy health/smoke validation.

### Logging / health mechanisms

Enough operational tooling to make ingestion and application failures visible.

### Public repository

A clean repository demonstrating production engineering decisions.

It should include:

*   architecture documentation;
    
*   setup;
    
*   migrations;
    
*   source configuration;
    
*   test strategy;
    
*   CI/CD;
    
*   deployment documentation.
    

### Deployed application

A publicly demonstrable version of the platform.

### Portfolio case-study material

Enough material to explain:

*   client problem;
    
*   system architecture;
    
*   ETL;
    
*   PostGIS design;
    
*   source versioning;
    
*   data QA;
    
*   async processing;
    
*   API;
    
*   CI/CD;
    
*   application workflow;
    
*   lessons / limitations.
    

14\. Current Decisions
----------------------

**Decision:** The project will be an Environmental Screening & GeoData Operations Platform rather than another standalone analytical map.**Rationale:** The existing portfolio already demonstrates analysis and visualization; this project exists to demonstrate production geospatial engineering.

**Decision:** Preliminary environmental screening is the application use case.**Rationale:** It creates a realistic reason for maintaining several environmental datasets, running spatial queries, supporting projects, and generating repeatable outputs without requiring complex scientific modelling.

**Decision:** The product should use one contained geography and roughly five environmental datasets.**Rationale:** This provides enough technical variety to demonstrate ETL without allowing the data catalog to expand indefinitely.

**Decision:** The system should ingest heterogeneous geospatial source types.**Rationale:** Production ETL competence is better demonstrated by several realistic ingestion patterns than by repeated processing of identical file types.

**Decision:** Raw, staging, and canonical/core data should be conceptually separated.**Rationale:** This enables reproducibility, auditability, validation, and safe source updates.

**Decision:** Raw source snapshots and provenance should be preserved.**Rationale:** The platform should demonstrate data lineage rather than treating upstream sources as ephemeral.

**Decision:** PostgreSQL/PostGIS is a core technology for this project.**Rationale:** Unlike other portfolio applications where static assets may be more appropriate, this project specifically exists to demonstrate production spatial database engineering.

**Decision:** Source datasets should be versioned and new versions should pass data-quality gates before activation.**Rationale:** Reliable geospatial operations require protection against broken or unexpectedly changed upstream data.

**Decision:** Ingestion and screening workflows should be idempotent.**Rationale:** Retrying automated data processes must not corrupt or duplicate production data.

**Decision:** Environmental screening should use transparent physical metrics rather than an invented composite score.**Rationale:** The analytical workflow should remain credible and understandable while the engineering system remains the project's primary focus.

**Decision:** FastAPI is the preferred API framework.**Rationale:** It integrates naturally with the Python geospatial stack and supports typed APIs and OpenAPI documentation.

**Decision:** Screening should use asynchronous/background jobs.**Rationale:** This demonstrates realistic job architecture and avoids tying potentially expensive spatial processing to long-lived web requests.

**Decision:** React, TypeScript, and MapLibre are the preferred frontend stack.**Rationale:** They provide a professional interface consistent with the broader portfolio while keeping the project's focus on geospatial software engineering.

**Decision:** Dockerized local development is part of the intended project.**Rationale:** Reproducibility of the full application stack is an important production-engineering capability.

**Decision:** CI and CD are core requirements rather than optional polish.**Rationale:** Automated testing/build/deployment is one of the principal portfolio gaps this project is intended to close.

**Decision:** Geospatial/data validation should be included in CI or pipeline quality gates.**Rationale:** Production spatial systems need tests around data contracts and geometry, not only application code.

**Decision:** Observability should remain lightweight.**Rationale:** Logs, health, job status, and freshness should demonstrate operational awareness without turning the project into an SRE platform.

**Decision:** ML, EO, 3D, and routing should not be added.**Rationale:** Those competencies are already represented elsewhere and would distract from the platform-engineering objective.

**Decision:** Kubernetes and complex microservice infrastructure are out of scope.**Rationale:** The system should demonstrate good engineering judgment, not infrastructure complexity for its own sake.

15\. Rejected or Superseded Directions
--------------------------------------

### Another analytical environmental map

Not selected.

The portfolio already contains multiple projects following the pattern:

data→ analysis→ map/application.

This project instead focuses on:

external systems→ production data platform→ operational application.

### Dedicated generic ETL demo

A standalone ETL-only project was previously considered unnecessary.

The screening platform replaces that idea by embedding ETL within a realistic geospatial product.

### Static-only architecture

Not selected for this project.

Static architecture remains appropriate for several other portfolio projects, but this capstone intentionally requires:

*   backend API;
    
*   PostGIS;
    
*   worker processing;
    
*   operational data workflows.
    

### ML / AI features

Not selected.

Machine learning is covered by the Landslide Susceptibility AI and Solar PV Inventory AI projects.

### Earth observation

Not selected as a project focus.

The system may ingest raster datasets, but should not become another EO-processing project.

### 3D functionality

Not selected.

3D is already represented elsewhere in the portfolio.

### Infrastructure routing

Not selected.

Routing is represented by the Infrastructure Corridor Optimizer.

### Kubernetes

Explicitly unnecessary.

### Kafka / event streaming

Explicitly unnecessary.

A lightweight queue is sufficient.

### Microservice-heavy architecture

Not selected.

The system should remain a coherent small application with a limited number of processes/services.

### Large multi-tenant SaaS

Not selected.

The fictional consultancy use case does not require enterprise SaaS complexity.

### Dozens of environmental datasets

Not selected.

Approximately five well-chosen external sources are sufficient.

### Complex enterprise IAM

Not selected.

Simple authentication may be useful, but sophisticated identity infrastructure would not strengthen the primary portfolio objective enough to justify its scope.

16\. Open Questions and Decision Boundaries
-------------------------------------------

### Final geography

**Type:** RESEARCH NEEDED, then OWNER DECISION

Select a region with:

*   several authoritative environmental sources;
    
*   varied access methods;
    
*   clear public licensing;
    
*   manageable data scale;
    
*   realistic screening use cases.
    

### Exact environmental datasets

**Type:** RESEARCH NEEDED, then OWNER DECISION

Approximately five sources should be selected after auditing geography and access methods.

### Final screening metrics

**Type:** OWNER DECISION after source research

Metrics should be transparent and source-specific.

Codex should not invent regulatory thresholds.

### DEM / slope inclusion

**Type:** OWNER DECISION after research

Terrain is useful but may replace rather than supplement one of the five principal datasets.

### AOI creation mechanism

**Type:** DEVELOPMENT DECISION / OWNER REVIEW

Drawing is strongly expected.

Whether file upload is included in the MVP should be determined during product-scoping.

### Authentication

**Type:** OWNER DECISION

Simple authentication and analyst/admin roles could strengthen the realism of the system, but authentication is not yet a confirmed hard requirement.

### Object-storage provider

**Type:** DEVELOPMENT DECISION

S3-compatible storage is preferred.

Potential choices include:

*   Cloudflare R2;
    
*   another S3-compatible hosted service.
    

MinIO is a likely local-development choice if object storage is retained.

### Queue / worker implementation

**Type:** DEVELOPMENT DECISION

Redis is the preferred lightweight queue dependency.

The exact worker library/pattern has not been selected.

### Dataset promotion architecture

**Type:** DEVELOPMENT DECISION

The mechanism for atomically marking a validated dataset version active should be designed carefully.

### Source update detection

**Type:** RESEARCH NEEDED / DEVELOPMENT DECISION

Depending on the source, update detection may use:

*   release/version metadata;
    
*   timestamps;
    
*   ETags;
    
*   checksums;
    
*   full-download comparison.
    

### Screening result versioning

**Type:** DEVELOPMENT DECISION

The system should preserve source-version provenance.

Whether completed screenings remain immutable or may be explicitly re-run on newer data remains unresolved.

### Scheduled ingestion frequency

**Type:** DEVELOPMENT DECISION

Should reflect actual upstream source-update frequency rather than use an arbitrary schedule.

### Report generation

**Type:** OWNER DECISION

A concise PDF screening report is attractive and realistic but not yet mandatory.

### GIS export format

**Type:** DEVELOPMENT DECISION / OWNER REVIEW

CSV plus a web-friendly spatial format are expected.

GeoPackage would be valuable for professional GIS handoff if implementation remains straightforward.

### Hosting provider(s)

**Type:** RESEARCH NEEDED / DEVELOPMENT DECISION

Need affordable deployment capable of:

*   containers/backend;
    
*   worker;
    
*   managed Postgres/PostGIS;
    
*   static frontend;
    
*   object storage;
    
*   GitHub Actions integration.
    

### Infrastructure as code

**Type:** DEVELOPMENT DECISION

Terraform is explicitly not required.

Use only if deployment complexity later justifies it.

### Production monitoring tooling

**Type:** DEVELOPMENT DECISION

Structured logs and health checks are required conceptually.

Third-party observability services are optional.

### Testing depth

**Type:** DEVELOPMENT DECISION

The project should prioritize meaningful end-to-end/system tests over chasing arbitrary coverage percentages.

17\. Development Priorities
---------------------------

1.  **Select and validate the geographic/data environment.**Choose the study region and approximately five external sources, verifying access methods, licensing, update behavior, formats, and data volumes.
    
2.  **Define the screening workflow.**Establish project/AOI behavior, per-dataset screening metrics, output structure, and preliminary-screening limitations.
    
3.  **Design the production data architecture.**Define source catalog, raw storage, staging, dataset versions, canonical PostGIS schemas, ingestion records, projects, jobs, and results.
    
4.  **Establish the reproducible local platform.**Create the containerized PostGIS/API/worker/supporting-service development environment and migrations.
    
5.  **Implement source ingestion and provenance.**Build source adapters, raw snapshots, checksums, metadata, idempotency, and source-specific handling.
    
6.  **Implement validation and safe dataset promotion.**Add schema/spatial quality checks and ensure failed versions cannot replace valid active data.
    
7.  **Implement the screening engine.**Build transparent PostGIS/Python spatial calculations using the active canonical datasets.
    
8.  **Implement asynchronous job processing.**Add queueing, worker execution, status, retries, failure handling, and idempotency.
    
9.  **Implement the backend API.**Expose projects, screenings, results, datasets, statuses, and health information.
    
10.  **Build automated tests and CI.**Cover application code, migrations, ingestion, spatial contracts, integration behavior, and frontend builds.
    
11.  **Build the web application.**Implement project/AOI workflows, screening-job state, map results, summaries, exports, and the data-operations view.
    
12.  **Implement refresh scheduling and operational visibility.**Add source refresh workflows, freshness/status displays, structured logs, and health checks.
    
13.  **Add professional outputs.**Implement GIS/tabular exports and a report if retained.
    
14.  **Establish CD and hosted deployment.**Automate build, migration, deployment, and post-deployment smoke checks.
    
15.  **Validate, optimize, and document.**Review PostGIS query performance, failure scenarios, source-update behavior, security, UX, and architectural documentation.
    
16.  **Prepare the portfolio case study.**Present the system architecture and operational engineering as prominently as the final UI.
    

18\. Definition of Project Success
----------------------------------

The Environmental Screening & GeoData Operations Platform is successful when it demonstrates a complete, credible production geospatial system rather than merely a map backed by preprocessing scripts.

Functionally, the completed project should allow a user to:

*   create or define a project AOI;
    
*   submit a preliminary environmental screening;
    
*   observe asynchronous processing;
    
*   review mapped and summarized screening results;
    
*   inspect the source datasets underlying those results;
    
*   download useful outputs.
    

The data platform should:

*   ingest multiple real external geospatial sources;
    
*   preserve raw source provenance;
    
*   validate and normalize data;
    
*   maintain versioned canonical datasets in PostGIS;
    
*   reject bad upstream updates safely;
    
*   perform idempotent processing;
    
*   support scheduled refresh;
    
*   retain enough lineage to reproduce screening results.
    

The software platform should include:

*   a real API;
    
*   spatial database;
    
*   background jobs;
    
*   migrations;
    
*   Dockerized development;
    
*   automated tests;
    
*   CI;
    
*   automated deployment;
    
*   health/status visibility.
    

Professionally, the project should make it credible to say:

> I can build the production engineering system around geospatial data—not only analyse data and make maps.

It should visibly demonstrate competence in:

*   geospatial ETL;
    
*   Python;
    
*   PostgreSQL/PostGIS;
    
*   spatial SQL;
    
*   API development;
    
*   data contracts;
    
*   versioning/provenance;
    
*   asynchronous processing;
    
*   Docker;
    
*   testing;
    
*   CI/CD;
    
*   deployment;
    
*   observability;
    
*   React/TypeScript;
    
*   MapLibre;
    
*   production geospatial architecture.
    

The final result should feel like a small but authentic internal platform an environmental consultancy could actually use.

19\. Context Confidence / Gaps
------------------------------

The **project purpose, portfolio role, application concept, engineering emphasis, high-level architecture, ETL philosophy, PostGIS role, API/worker requirement, CI/CD objective, data-quality philosophy, scope constraints, and deployment philosophy are sufficiently established** to initialize repository governance and begin architectural/data-source feasibility work.

The most important unresolved areas are:

*   geographic region;
    
*   exact five source datasets;
    
*   precise access methods;
    
*   screening metrics;
    
*   final raw-storage provider;
    
*   queue/worker implementation;
    
*   authentication inclusion;
    
*   deployment platform;
    
*   report inclusion;
    
*   GIS export format;
    
*   refresh frequencies;
    
*   exact source-update detection strategy.
    

These are implementation and feasibility decisions rather than evidence that the product concept is incomplete.

The initial development phase should therefore focus on **source validation and platform architecture**, not additional feature ideation.