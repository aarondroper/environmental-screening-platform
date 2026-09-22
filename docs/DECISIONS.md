# Decisions

## Purpose

This record preserves the consequential product and architecture directions that should survive across development sessions. It does not record trivial implementation choices. The checkout has no usable Git history or dated decision evidence, so these entries are current governance declarations carried by the project documents, not claims about when or by whom a historical decision was made. “Alternatives considered” describes the documented contrast for the direction, not an independently verified meeting record.

## D001 — Make production geospatial engineering the project focus

**Status:** Confirmed project decision; historical date not recorded.

**Decision:** Build an Environmental Screening & GeoData Operations Platform rather than another standalone analytical map.

**Rationale:** The portfolio already covers environmental analysis, Earth observation, modelling, routing, dashboards, and visualization. The remaining gap is a production system around geospatial data: acquisition, validation, versioning, storage, APIs, workers, deployment, and operations.

**Alternatives considered:** A dedicated ETL demonstration or another analytical environmental map.

**Consequences:** The product must contain a real backend, PostGIS, background processing, reproducible ingestion, quality gates, and deployment. Analysis remains deliberately transparent and modest.

## D002 — Use preliminary environmental screening as the product use case

**Status:** Confirmed project decision; historical date not recorded.

**Decision:** Users create project areas and run preliminary screening against maintained environmental datasets.

**Rationale:** This creates a realistic consultancy workflow and a coherent reason to maintain several sources without requiring complex scientific modelling.

**Alternatives considered:** A generic geospatial data catalog or an environmental-impact-assessment product.

**Consequences:** Results must be framed as preliminary constraints, not regulatory, planning, engineering, or environmental-impact conclusions. Metrics should be understandable physical measures.

## D003 — Contain the geography and limit the source set

**Status:** Confirmed direction; geography and MVP source direction selected by D013 and D014, artifact validation remains pending.

**Decision:** Use one contained country or region and approximately five external environmental datasets.

**Rationale:** This provides enough technical and environmental variety to demonstrate a real platform while keeping ingestion, storage, cost, and screening feasible for a portfolio project.

**Alternatives considered:** Multi-country/global coverage or dozens of datasets.

**Consequences:** Geography and source direction are selected through evidence-based feasibility work. The owner-selected geography is recorded in D013; the current five-source direction is recorded in D014. Exact artifacts still require reuse/access and representative-data validation. New layers require an explicit scope decision rather than being added for catalog size.

## D004 — Deliberately use heterogeneous source types

**Status:** Confirmed project direction; exact interfaces unresolved.

**Decision:** The selected sources should exercise multiple realistic acquisition patterns where feasible, such as paginated REST/ArcGIS services, downloadable vector data, and raster assets.

**Rationale:** Repeatedly downloading identical files would not demonstrate the intended breadth of production ETL.

**Alternatives considered:** Five sources using one uniform format or protocol.

**Consequences:** Source adapters and validation must accommodate real differences. Diversity must remain subordinate to source quality, licensing, maintainability, and project feasibility.

## D005 — Separate raw, staging, and canonical data

**Status:** Confirmed architecture decision; implementation pending.

**Decision:** Preserve raw source snapshots, process them through staging/validation, and promote normalized data into canonical PostGIS structures.

**Rationale:** Separation enables provenance, reproducibility, auditability, source-specific cleanup, and safe updates.

**Alternatives considered:** Directly overwriting one production table from each source.

**Consequences:** The project needs object storage or an equivalent raw archive, ingestion metadata, validation boundaries, retention decisions, and more than one processing stage.

## D006 — Version datasets and gate promotion

**Status:** Confirmed architecture decision; implementation pending.

**Decision:** Dataset versions and ingestion runs are first-class concepts. A candidate version must pass source-specific checks before becoming active, and a failed update must not replace the previous valid version.

**Rationale:** HTTP success or parse success does not establish that upstream geospatial data is usable. Failure-safe promotion is central to platform credibility.

**Alternatives considered:** Always replacing the active table after a successful download/parse.

**Consequences:** The schema, ingestion code, tests, and operations UI must expose statuses, checks, active/superseded versions, and failures.

## D007 — Prefer transparent metrics over a composite environmental score

**Status:** Confirmed analytical direction; exact metrics unresolved until source selection.

**Decision:** Report per-dataset physical metrics such as overlap area, percentage, counts, lengths, distances, or terrain statistics. Do not invent an overall weighted environmental-risk score.

**Rationale:** The platform's primary objective is production engineering, and individual metrics are easier to explain, validate, and audit than an arbitrary composite.

**Alternatives considered:** A single overall constraint or environmental-risk score.

**Consequences:** Screening results must preserve source-specific definitions and limitations. Any threshold or regulatory interpretation requires evidence and owner review.

## D008 — Use Python/FastAPI/PostGIS with React/TypeScript/MapLibre

**Status:** Confirmed/strongly preferred stack direction; implementation pending.

**Decision:** Use Python for backend and geospatial processing, FastAPI for the API, PostgreSQL/PostGIS for spatial storage, React + TypeScript for the frontend, and MapLibre for mapping.

**Rationale:** This stack fits the geospatial workload, supports typed API contracts, and aligns with the portfolio's technical direction while keeping the system self-contained.

**Alternatives considered:** Static-only hosting or a frontend without a real backend/spatial database.

**Consequences:** A static-only architecture cannot satisfy the project's purpose. Exact libraries, route design, schema, and deployment runtime remain implementation decisions.

## D009 — Use asynchronous/background processing for screenings

**Status:** Confirmed architecture direction; queue/worker library unresolved.

**Decision:** Screening requests create jobs and return identifiers; a worker performs the spatial calculations and persists status/results.

**Rationale:** This demonstrates realistic job architecture and avoids tying potentially expensive spatial work to a long-lived HTTP request.

**Alternatives considered:** Performing all screening synchronously inside the request lifecycle.

**Consequences:** The system needs a queue or equivalent, job states, retries, failure handling, idempotency, and frontend status UX.

## D010 — Keep infrastructure proportional and observability lightweight

**Status:** Confirmed scope decision; hosting details unresolved.

**Decision:** Use Dockerized local development, automated CI/CD, health checks, structured logs, and source/job status without introducing Kubernetes, Kafka, microservice proliferation, or unnecessary infrastructure-as-code.

**Rationale:** The project should demonstrate engineering judgment and operational awareness, not complexity for appearance.

**Alternatives considered:** Distributed or enterprise infrastructure patterns.

**Consequences:** The deployed architecture should remain a small coherent application with a limited number of processes/services. New infrastructure requires a demonstrated need and an explicit decision.

## D011 — Keep the project self-contained and use the toolkit only as an optional reference

**Status:** Current repository policy; historical origin/date not recorded.

**Decision:** `~/projects/geospatial-project-toolkit`, when available, may be consulted for reusable engineering patterns, but the project must not depend on it at runtime or modify it during ordinary work.

**Rationale:** The toolkit can improve consistency without obscuring project ownership or coupling independent repositories.

**Alternatives considered:** Importing toolkit code directly, using a submodule, or making the project depend on the toolkit repository.

**Consequences:** Adapted implementations become project-owned code. Project requirements, tests, and decisions override generic toolkit patterns.

## D012 — Base the project on US datasets; supersede the England recommendation

**Status:** Owner decision recorded 2026-09-22; narrowed by D013.

**Decision:** The platform must be based on United States datasets. The former England geography/source recommendation is superseded and must not be treated as approved or as the working source set.

**Rationale:** The owner changed this fundamental product decision and requested US-focused feasibility research.

**Alternatives considered:** None recorded; this entry records the owner’s direction, not a reconstructed decision process.

**Consequences:** The initial geography/source research was superseded by later owner direction recorded in D013. Final source clearance is still required before Milestone 2.

## D013 — Select Northern Colorado and initially approve five provisional source themes

**Status:** Owner direction recorded 2026-09-22; geography remains selected. The initial source proposal below was superseded by D014.

**Decision:** Use the union of Boulder, Larimer, and Weld counties, Colorado, as the working study geography. Provisionally pursue USFWS NWI, FEMA NFHL, USGS PAD-US, Annual NLCD, and USGS 3DEP. Do not consider these source choices final until the exact releases, terms, access, formats, scale, and representative samples are validated. NWI redistribution terms are explicitly unresolved. If NWI cannot be cleared, do not silently substitute a source; obtain owner approval for a replacement or other scope change.

**Rationale:** The owner selected the Northern Colorado Front Range and endorsed these source themes for continued validation.

**Alternatives considered:** The owner has not selected an alternative NWI source. SSURGO hydric-soil information and proceeding with four sources are documented as options in `SOURCE_FEASIBILITY.md`, not adopted decisions.

**Consequences:** The source list below is historical and is not the current MVP. Continue source/release validation under D014. Do not initialize, replace, or repair the invalid Git metadata without explicit authorization.

## D014 — Remove NWI from MVP and select SSURGO hydric-soil information instead

**Status:** Owner decision recorded 2026-09-22; source direction selected, final artifacts remain subject to validation.

**Decision:** The current MVP source direction is FEMA NFHL, USGS PAD-US, Annual NLCD, USGS 3DEP, and NRCS SSURGO using hydric-soil information where appropriate. NWI is superseded for the MVP because its exact release-specific redistribution terms could not be confirmed. SSURGO is the selected replacement source. This decision does not make SSURGO a wetlands inventory: hydric-soil indicators are not regulatory wetland determinations, and results must not imply jurisdictional-wetland presence or absence. Do not silently substitute another source if SSURGO’s actual package validation fails.

**Rationale:** The owner selected this revised source set after NWI redistribution terms remained unresolved. SSURGO has a public-domain-marked catalogue record and supplies distinct soil information with hydric component attributes.

**Alternatives considered:** NWI as a future optional source after rights clearance, another owner-approved environmental source, or fewer than five MVP sources. None is approved as a replacement for SSURGO at this time.

**Consequences:** Validate the exact SSURGO packages, component attributes, source scale, access and volume for all intersecting survey areas, together with the other four selected sources, before Milestone 2. Preserve component-level hydric values and unknowns. Milestone 2 remains gated on representative artifact and boundary validation; Git metadata remains untouched absent explicit authorization.
